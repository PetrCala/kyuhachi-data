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
from onsen_scraper.hours import DAYS, parsed_hours_doc  # noqa: E402


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
    assert len(plan) == 148
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
    for hid, e in CURATED.items():
        assert set(e["closed"]) <= set(bf._ABBR), hid
        if e["publish"]:
            assert e["window"] and all(TIME.match(t) for t in e["window"]), hid
        for ov in e["overrides"].values():
            assert ov is None or all(TIME.match(t) for t in ov), hid


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
            assert set(x) == {"en", "ja"}, hid
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
