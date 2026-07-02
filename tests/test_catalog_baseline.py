"""Tests for roadmap item B — the `catalog` baseline adapter and the no-op-aware
backfills that read live before writing.

Two capabilities, both built on the shared paginated live read
(publisher/firestore_rest.fetch_collection):

  Part 1  catalog_diff.load_catalog() — project the published Firestore /onsens onto
          the diff's snake_case FIELDS, decode typed values, map kyuhachiId → hid.
  Part 2  backfill_*.split_writes() — partition the plan into (to_write, current) by
          reading the live value, so a re-run PATCHes only what actually changed and
          bumps the catalog version only when at least one write happens.

Fully offline — the REST/live-read layer is monkeypatched; no network, no auth, no
writes. `catalog_diff` lives in the skill dir and the publisher scripts in a
non-package dir, so both are added to sys.path (same trick as the sibling tests)."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "publisher"))
sys.path.insert(0, str(REPO / ".claude" / "skills" / "catalog-diff"))

import catalog_diff as cd  # noqa: E402
import firestore_rest as fr  # noqa: E402


# --- Part 1: load_catalog() --------------------------------------------------

def _sval(s):
    return {"stringValue": s}


def test_load_catalog_projects_camelcase_and_maps_hid(monkeypatch, tmp_path):
    """A published doc (camelCase, nested businessHours.raw) projects onto the
    parser's snake_case CATALOG_FIELDS, keyed by hid via the inverted id map."""
    idmap = {"1": "kid-A", "2": "kid-B"}
    map_path = tmp_path / "onsen-id-map.json"
    map_path.write_text(json.dumps(idmap), encoding="utf-8")
    monkeypatch.setattr(cd, "ID_MAP", map_path)

    live = {
        "kid-A": {
            "prefecture": _sval("福岡県"),
            "address": _sval("筑紫野市湯町1-14-5"),
            "phone": _sval("092-922-2119"),
            "businessHours": {"mapValue": {"fields": {
                "raw": _sval("10:00~21:30\n無休"),
                "schedule": {"nullValue": None}}}},
            "admissionFee": _sval("大人 350円"),
            "springQuality": _sval("単純温泉"),
            "websiteUrl": _sval("http://hakatayu.jp/"),
            # published-but-not-projected fields (derived / generated) are ignored:
            "nameKana": _sval("はかたゆ"),
            "adultFee": {"integerValue": "350"},
            "imageUrl": _sval("https://storage/…webp"),
        },
        "kid-B": {"prefecture": _sval("大分県")},   # sparse doc — missing fields → None
        "kid-orphan": {"prefecture": _sval("?")},    # kid not in id map → skipped entirely
    }
    monkeypatch.setattr(fr, "token", lambda: "TOK")
    monkeypatch.setattr(fr, "fetch_collection", lambda coll, tok, page_size=300: live)

    cat = cd.load_catalog()

    assert set(cat) == {1, 2}                                  # orphan (no hid) dropped
    # camelCase → snake_case, and the nested businessHours.raw is pulled out flat.
    assert cat[1]["business_hours"] == "10:00~21:30\n無休"
    assert cat[1]["admission_fee"] == "大人 350円"
    assert cat[1]["website_url"] == "http://hakatayu.jp/"
    assert set(cat[1]) == set(cd.CATALOG_FIELDS)               # only the projected fields
    assert "nameKana" not in cat[1] and "adultFee" not in cat[1]
    assert cat[2]["address"] is None                           # absent field → None


def test_catalog_fields_are_the_material_source_fields():
    # The catalog only republishes source-authored MATERIAL fields; the muted
    # descriptive fields and the rehosted imageUrl are intentionally NOT projected.
    assert set(cd.CATALOG_FIELDS) == cd.MATERIAL
    assert not (set(cd.CATALOG_FIELDS) & cd.MUTED)


def test_diff_over_catalog_fields_ignores_muted_noise():
    """Narrowing the compared field set (as main() does for --baseline catalog) keeps
    unpublished muted fields from firing as spurious volatile modifications."""
    base = {1: {"prefecture": "福岡県", "covid_measures": None, "efficacy": None}}
    live = {1: {"prefecture": "福岡県", "covid_measures": "新しい注意書き", "efficacy": "美肌の湯"}}
    idmap = {"1": "kid-A"}

    # Full FIELDS: the muted deltas surface as a (low-signal) volatile modification…
    full = cd.diff(base, live, idmap)
    assert full["modified"] and full["modified"][0]["severity"] == "volatile"

    # …but over CATALOG_FIELDS only the published fields are compared → no change.
    narrowed = cd.diff(base, live, idmap, fields=cd.CATALOG_FIELDS)
    assert narrowed["modified"] == []


def test_diff_over_catalog_fields_still_catches_material_drift():
    base = {1: {"prefecture": "福岡県", "admission_fee": "大人 350円"}}
    live = {1: {"prefecture": "福岡県", "admission_fee": "大人 500円"}}
    out = cd.diff(base, live, {"1": "kid-A"}, fields=cd.CATALOG_FIELDS)
    assert out["modified"][0]["severity"] == "material"
    assert out["modified"][0]["materialFields"] == ["admission_fee"]


# --- Part 2: backfill no-op skip path ----------------------------------------

def test_kana_split_writes_partitions_by_change():
    import backfill_name_kana as bk
    writable = [
        (1, "kA", "博多湯", "はかたゆ"),   # live matches → current
        (2, "kB", "元湯", "もとゆ"),        # live differs → write
        (3, "kC", "X", None),               # target null, live null → current
        (4, "kD", "Y", "わ"),               # kid absent from live → write
    ]
    live = {
        "kA": {"nameKana": {"stringValue": "はかたゆ"}},
        "kB": {"nameKana": {"stringValue": "ふるいよみ"}},
        "kC": {"nameKana": {"nullValue": None}},
    }
    to_write, current = bk.split_writes(writable, live)
    assert {r[0] for r in to_write} == {2, 4}
    assert {r[0] for r in current} == {1, 3}
    # live unread (dry-run with no auth) → every writable row counts as a change.
    assert bk.split_writes(writable, None) == (writable, [])


def test_romaji_split_writes_partitions_by_change():
    import backfill_name_romaji as br
    writable = [(1, "kA", "X", "Hakata Yu"), (2, "kB", "Y", "Moto Yu")]
    live = {
        "kA": {"nameRomaji": {"stringValue": "Hakata Yu"}},   # current
        "kB": {"nameRomaji": {"stringValue": "Old Romaji"}},  # write
    }
    to_write, current = br.split_writes(writable, live)
    assert {r[0] for r in to_write} == {2}
    assert {r[0] for r in current} == {1}


def test_fees_split_writes_partitions_by_change():
    import backfill_fees as bf
    writable = [
        (1, "kA", "X", 350, "adult"),   # live 350 → current
        (2, "kB", "Y", 600, "adult"),   # live 500 → write
        (3, "kC", "Z", None, "none"),   # target null, live null → current
    ]
    live = {
        "kA": {"adultFee": {"integerValue": "350"}},
        "kB": {"adultFee": {"integerValue": "500"}},
        "kC": {"adultFee": {"nullValue": None}},
    }
    to_write, current = bf.split_writes(writable, live)
    assert {r[0] for r in to_write} == {2}
    assert {r[0] for r in current} == {1, 3}


def test_schedule_split_writes_partitions_by_change():
    import backfill_schedule as bs
    sched_a = {d: {"opens": "10:00", "closes": "22:00"} for d in bs.DAYS_FULL}
    sched_b = dict(sched_a)
    sched_b["tuesday"] = None                                  # closed Tuesdays

    def live_doc(sched):
        return {"businessHours": {"mapValue": {"fields": {"schedule": bs.sched_val(sched)}}}}

    writable = [
        (1, "kA", "X", sched_a, "ok"),   # live == target → current
        (2, "kB", "Y", sched_b, "ok"),   # live has sched_a, target sched_b → write
        (3, "kC", "Z", sched_a, "ok"),   # kid absent from live → write
    ]
    live = {"kA": live_doc(sched_a), "kB": live_doc(sched_a)}
    to_write, current = bs.split_writes(writable, live)
    assert {r[0] for r in to_write} == {2, 3}
    assert {r[0] for r in current} == {1}


# --- Part 2: the no-op skip → no version bump contract (main(), REST mocked) --

def _run_kana_commit(monkeypatch, plan, live):
    """Run backfill_name_kana.main() --commit with build_plan/live_onsens/patch/
    bump_catalog_version all stubbed. Returns (patched_paths, bump_calls)."""
    import backfill_name_kana as bk
    patched, bumped = [], []
    monkeypatch.setattr(bk, "build_plan", lambda: plan)
    monkeypatch.setattr(bk, "live_onsens", lambda commit: ("TOK", live))
    monkeypatch.setattr(bk, "patch", lambda path, fields, mask, tok: patched.append(path))
    monkeypatch.setattr(bk, "bump_catalog_version", lambda now, tok: bumped.append(now))
    monkeypatch.setattr(sys, "argv", ["backfill_name_kana.py", "--commit"])
    bk.main()
    return patched, bumped


def test_backfill_commit_noop_writes_nothing_and_skips_bump(monkeypatch):
    plan = [(1, "kA", "博多湯", "はかたゆ"), (2, "kB", "元湯", "もとゆ")]
    live = {"kA": {"nameKana": {"stringValue": "はかたゆ"}},
            "kB": {"nameKana": {"stringValue": "もとゆ"}}}   # both already current
    patched, bumped = _run_kana_commit(monkeypatch, plan, live)
    assert patched == []       # nothing written…
    assert bumped == []        # …so the catalog version is NOT bumped


def test_backfill_commit_writes_only_changed_and_bumps_once(monkeypatch):
    plan = [(1, "kA", "博多湯", "はかたゆ"), (2, "kB", "元湯", "もとゆ")]
    live = {"kA": {"nameKana": {"stringValue": "はかたゆ"}},        # current
            "kB": {"nameKana": {"stringValue": "ちがうよみ"}}}      # changed
    patched, bumped = _run_kana_commit(monkeypatch, plan, live)
    assert patched == ["onsens/kB"]   # only the doc that actually changed
    assert len(bumped) == 1           # exactly one version bump, because a write happened
