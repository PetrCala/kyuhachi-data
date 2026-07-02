"""Tests for publishing structured businessHours.schedule.

Covers the Firestore typed-value encoder (`sched_val`) and the offline backfill
plan built from the snapshot DB. Fully offline — no network, no auth, no writes.
`apply.py` / `backfill_schedule.py` live in non-package dirs, so we add them to
sys.path (same trick as test_catalog_diff_soft_removal)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "publisher"))

import apply  # noqa: E402  (publisher/apply.py — the surgical publisher)
import backfill_schedule as bf  # noqa: E402
from onsen_scraper.hours import DAYS, last_entry_caption, parsed_hours_doc  # noqa: E402


def test_sched_val_null_for_unstructured():
    assert bf.sched_val(None) == {"nullValue": None}


def test_sched_val_open_all_week():
    sched = parsed_hours_doc("10:00～22:00\n無休")["schedule"]
    val = bf.sched_val(sched)
    fields = val["mapValue"]["fields"]
    assert set(fields) == set(DAYS)
    assert fields["monday"] == {"mapValue": {"fields": {
        "opens": {"stringValue": "10:00"}, "closes": {"stringValue": "22:00"}}}}


def test_sched_val_weekday_closed_encodes_null_day():
    sched = parsed_hours_doc("10:00～22:00\n火曜休")["schedule"]
    fields = bf.sched_val(sched)["mapValue"]["fields"]
    assert fields["tuesday"] == {"nullValue": None}          # closed → null
    assert fields["monday"]["mapValue"]["fields"]["opens"]["stringValue"] == "10:00"


def test_apply_does_not_encode_schedule():
    # businessHours.schedule is owned solely by backfill_schedule.py (the curated
    # parse); apply.py no longer carries a schedule encoder, so an hours-text
    # change updates raw + adultFee but never ships a regex-derived grid.
    assert not hasattr(apply, "sched_val")


def test_backfill_plan_over_snapshot():
    plan = bf.build_plan()
    # One row per snapshot onsen — derive the expected set from the baseline rather
    # than hard-coding a count, so a `promote` that grows the snapshot (new onsens)
    # doesn't break this *post*-promote check (the publish job runs it after promote).
    import sqlite3
    con = sqlite3.connect(f"file:{bf.SNAPSHOT_DB}?mode=ro", uri=True)
    snap_ids = {r[0] for r in con.execute("select id from onsens")}
    con.close()
    assert {p[0] for p in plan} == snap_ids
    structured = [p for p in plan if p[3] is not None]
    # The snapshot yields a structured schedule for the open-all + weekday-closed
    # onsens (see hours_report); the rest stay raw-only. Sanity-bound it.
    assert 40 <= len(structured) <= 80
    # Every structured schedule encodes cleanly to a 7-day Firestore map.
    for _oid, _kid, _name, sched, _reason in structured:
        fields = bf.sched_val(sched)["mapValue"]["fields"]
        assert set(fields) == set(DAYS)


# --- curated (hand/LLM-parsed) dataset --------------------------------------- #

import json  # noqa: E402

CURATED = json.loads((REPO / "data" / "hours_curated.json").read_text())["onsens"]


def test_curated_covers_every_snapshot_onsen():
    import sqlite3
    con = sqlite3.connect(f"file:{REPO/'data'/'snapshot.db'}?mode=ro", uri=True)
    snap = {str(r[0]) for r in con.execute("select id from onsens")}
    con.close()
    assert set(CURATED) == snap  # exactly the 148, no more, no fewer


def test_curated_entries_wellformed():
    import re
    TIME = re.compile(r"^\d{2}:\d{2}$")

    def ok_window(v):  # [o,c] or [[o,c], ...] — every time HH:MM
        wins = bf.norm_windows(v)
        return bool(wins) and all(len(w) == 2 and all(TIME.match(t) for t in w) for w in wins)

    for hid, e in CURATED.items():
        assert set(e["closed"]) <= set(bf._ABBR), hid
        if e["publish"]:
            assert ok_window(e["window"]), hid
        for ov in e["overrides"].values():
            assert ov is None or ok_window(ov), hid


def test_expand_curated_open_all_and_weekday():
    # open-all (無休)
    s = bf.expand_curated({"publish": True, "window": ["10:00", "21:30"],
                           "closed": [], "overrides": {}})
    assert s["monday"] == {"opens": "10:00", "closes": "21:30"}
    assert all(v is not None for v in s.values())
    # weekday closed
    s = bf.expand_curated({"publish": True, "window": ["10:00", "22:00"],
                           "closed": ["tue"], "overrides": {}})
    assert s["tuesday"] is None and s["monday"]["opens"] == "10:00"
    # per-day override
    s = bf.expand_curated({"publish": True, "window": ["08:00", "19:00"],
                           "closed": ["wed"], "overrides": {"tue": ["08:00", "16:00"]}})
    assert s["tuesday"] == {"opens": "08:00", "closes": "16:00"}
    assert s["wednesday"] is None
    # not published → None
    assert bf.expand_curated({"publish": False, "window": None,
                              "closed": [], "overrides": {}}) is None


def test_curated_exceptions_wellformed():
    for hid, e in CURATED.items():
        assert isinstance(e["exceptions"], list), hid
        for x in e["exceptions"]:
            assert set(x) - {"rule"} == {"en", "ja"}, hid
            assert x["en"].strip() and x["ja"].strip(), hid


def test_exc_and_conf_encoders():
    val = bf.exc_val([{"en": "Open on public holidays", "ja": "祝日は営業"}])
    vals = val["arrayValue"]["values"]
    assert vals[0]["mapValue"]["fields"]["en"]["stringValue"] == "Open on public holidays"
    assert vals[0]["mapValue"]["fields"]["ja"]["stringValue"] == "祝日は営業"
    assert bf.exc_val([])["arrayValue"]["values"] == []
    assert bf.conf_val("medium") == {"stringValue": "medium"}


def test_irregular_onsen_carries_confirm_exception():
    # raw/irregular onsens get an honest "confirm" caption (no grid).
    assert CURATED["10"]["publish"] is False
    assert any("不定休" in x["ja"] for x in CURATED["10"]["exceptions"])


def test_last_entry_promoted_to_caption():
    # 最終受付 (last entry) is otherwise buried in raw / "show original text". It's
    # surfaced as a normal exception caption and listed FIRST — a hard entry cutoff
    # decides whether a trip is worth making, so it earns top billing among the tips.
    assert CURATED["1"]["exceptions"][0] == {"en": "Last entry by 21:00", "ja": "最終受付 21:00"}
    # bath-specific cutoff (bath closes 20:00 but last entry is 19:30 / 19:00) spelled out.
    assert CURATED["57"]["exceptions"][0] == {
        "en": "Last entry: main bath 19:30, family bath 19:00",
        "ja": "最終受付 大風呂19:30・家族風呂19:00",
    }
    # 171's last entry equals its close time and is already shown — no duplicate caption.
    assert not any(x["ja"].startswith("最終受付") for x in CURATED["171"]["exceptions"])
    # Every last-entry caption is the lead exception and well-formed; 67 single-time + 1 split.
    total = 0
    for hid, e in CURATED.items():
        idxs = [i for i, x in enumerate(e["exceptions"]) if x["ja"].startswith("最終受付")]
        for i in idxs:
            assert i == 0, hid
            assert e["exceptions"][i]["en"].lower().startswith("last entry"), hid
        total += len(idxs)
    assert total == 68


def test_every_source_last_entry_is_captioned():
    # Durability guard: any onsen whose SOURCE states a clean single 最終受付 cutoff
    # must carry the matching caption, so a future recurate-hours pass (or a new
    # onsen) can't silently re-bury it. Scales past the hard-coded set above — it
    # derives the requirement straight from the snapshot, so an onsen that newly
    # gains a 最終受付 is flagged until it's curated. Mirrors recurate-hours
    # `validate`'s guard. (Per-bath/per-day cutoffs return None and are hand-curated.)
    import sqlite3
    con = sqlite3.connect(f"file:{REPO/'data'/'snapshot.db'}?mode=ro", uri=True)
    raws = {str(i): bh for i, bh in con.execute("select id, business_hours from onsens")}
    con.close()
    missing = [
        hid for hid, e in CURATED.items()
        if (cap := last_entry_caption(raws.get(hid))) is not None
        and cap not in e["exceptions"]
    ]
    assert not missing, f"source states 最終受付 but no caption: {sorted(missing, key=int)}"


# --- schema extension: windows / rule / lastEntry / confidence cap ------------ #
# docs/hours-schema.md — all additive; a single-window, rule-less, no-lastEntry
# entry must encode byte-identically to the pre-extension output.

def test_single_window_encoding_unchanged():
    # Legacy shape guarantee: no `windows` key on single-window days, no `rule`
    # field on plain captions — the published docs stay byte-identical.
    s = bf.expand_curated({"publish": True, "window": ["10:00", "21:30"],
                           "closed": ["tue"], "overrides": {}})
    assert s["monday"] == {"opens": "10:00", "closes": "21:30"}   # exactly, no windows key
    fields = bf.sched_val(s)["mapValue"]["fields"]
    assert set(fields["monday"]["mapValue"]["fields"]) == {"opens", "closes"}
    exc = bf.exc_val([{"en": "Open on public holidays", "ja": "祝日は営業"}])
    assert set(exc["arrayValue"]["values"][0]["mapValue"]["fields"]) == {"en", "ja"}


def test_multi_window_expand_encode_roundtrip():
    # hid-38 shape: two sessions + a MWF override with an exclusion gap.
    e = {"publish": True, "window": [["07:00", "10:30"], ["14:30", "22:00"]],
         "closed": ["sun"], "overrides": {"mon": [["08:30", "11:00"], ["13:00", "20:00"]]}}
    s = bf.expand_curated(e)
    # opens/closes mirror the FIRST window (legacy readers show one true window)…
    assert s["tuesday"]["opens"] == "07:00" and s["tuesday"]["closes"] == "10:30"
    # …and the full truth ships in `windows`.
    assert s["tuesday"]["windows"] == [{"opens": "07:00", "closes": "10:30"},
                                       {"opens": "14:30", "closes": "22:00"}]
    assert s["monday"]["windows"][1] == {"opens": "13:00", "closes": "20:00"}
    assert s["sunday"] is None
    # Firestore encode → decode round-trips exactly.
    assert bf.live_schedule({"schedule": bf.sched_val(s)}) == s


def test_rule_encoding_roundtrip():
    exceptions = [
        {"en": "Closed the 1st Wednesday each month (2nd Wed in Jan & May)",
         "ja": "毎月第1水曜休（1・5月は第2水曜）",
         "rule": {"kind": "monthlyWeekday", "weeks": [1], "weekday": "wednesday",
                  "exceptMonths": [1, 5]}},
        {"en": "Closed the 5th, 15th & 25th each month", "ja": "毎月5・15・25日休",
         "rule": {"kind": "monthlyDay", "days": [5, 15, 25]}},
        {"en": "Irregular closing days — confirm before visiting",
         "ja": "不定休 — 事前にご確認ください", "rule": {"kind": "irregular"}},
        {"en": "Open on public holidays", "ja": "祝日は営業"},   # no rule → unchanged
    ]
    assert bf.live_exceptions({"exceptions": bf.exc_val(exceptions)}) == exceptions


def test_published_confidence_caps_published_irregular_at_low():
    # The cap engages exactly when an irregular entry claims a grid — an
    # unpublished irregular entry (raw fallback + confirm caption) passes
    # through, so extending the schema alone changes no published doc.
    assert bf.published_confidence(
        {"status": "irregular", "confidence": "high", "publish": True}) == "low"
    assert bf.published_confidence(
        {"status": "irregular", "confidence": "high", "publish": False}) == "high"
    assert bf.published_confidence(
        {"status": "structured", "confidence": "high", "publish": True}) == "high"
    assert bf.published_confidence(
        {"status": "monthly", "confidence": "medium", "publish": True}) == "medium"


def test_last_entry_val_roundtrip():
    assert bf.le_val("21:00") == {"stringValue": "21:00"}
    assert bf.le_val(None) == {"nullValue": None}
    assert bf.live_last_entry({"lastEntry": bf.le_val("21:00")}) == "21:00"
    assert bf.live_last_entry({"lastEntry": bf.le_val(None)}) is None
    assert bf.live_last_entry({}) is None


def test_curated_last_entry_is_evidence_based():
    # businessHours.lastEntry may only state what the source text states
    # (docs/hours-schema.md): a curated `lastEntry` must equal the mechanically
    # detected single 最終受付 cutoff. Vacuous until the lastEntry backfill lands,
    # but locks the evidence gate from day one.
    import sqlite3
    from onsen_scraper.hours import single_last_entry
    con = sqlite3.connect(f"file:{REPO/'data'/'snapshot.db'}?mode=ro", uri=True)
    raws = {str(i): bh for i, bh in con.execute("select id, business_hours from onsens")}
    con.close()
    bad = [hid for hid, e in CURATED.items()
           if e.get("lastEntry") is not None
           and single_last_entry(raws.get(hid)) != e["lastEntry"]]
    assert not bad, f"lastEntry without source evidence: {sorted(bad, key=int)}"


def test_curated_fixes_known_bugs():
    # 151/224: the 翌日休 spurious-Sunday cases must be Tue-only / Thu-only now.
    s151 = bf.expand_curated(CURATED["151"])
    assert s151["sunday"] is not None and s151["tuesday"] is None
    s224 = bf.expand_curated(CURATED["224"])
    assert s224["sunday"] is not None and s224["thursday"] is None
    # 元湯 (11): annual-only closure → now published open-all-week (no weekly closed day).
    s11 = bf.expand_curated(CURATED["11"])
    assert CURATED["11"]["publish"] is True
    assert all(v is not None for v in s11.values())
