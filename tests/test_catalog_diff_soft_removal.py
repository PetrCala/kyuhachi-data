"""Tests for catalog-diff soft-removal (delisting) detection.

A delisted onsen (real example: hid 248, 神の湯 / 紫尾温泉) returns HTTP 200 with
the normal site chrome but NO detail table, so the parser yields all-None. That
must classify as REMOVED (same as a 404), not as a "every field → None" material
modification. These tests are fully offline — no network, no snapshot writes.

`catalog_diff` lives in the skill dir, so we add it to sys.path. Reading the
snapshot DB is read-only (mode=ro) and optional (a synthetic populated parse is
the primary fixture; the real page is a bonus realism check)."""
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "catalog-diff"
sys.path.insert(0, str(SKILL_DIR))

import catalog_diff as cd  # noqa: E402
from onsen_scraper import parse_detail_page  # noqa: E402

SNAPSHOT_DB = REPO_ROOT / "data" / "snapshot.db"

# A delisted page: full site chrome, but no #spot_detail table at all.
DELISTED_HTML = """\
<!DOCTYPE html>
<html><head><title>88onsen</title></head>
<body>
  <div id="header">温泉</div>
  <div id="contents_title"><ul><li><a href="/">Home</a></li></ul></div>
  <div id="footer">（2026年 4月現在）</div>
</body></html>
"""


# --- the emptiness predicate -------------------------------------------------

def test_predicate_true_for_all_none_material():
    parsed = {f: None for f in cd.FIELDS}
    assert cd.is_soft_removed(parsed) is True


def test_predicate_true_for_empty_and_whitespace_material():
    # &nbsp; / blank strings normalize to "" — still soft-removed.
    parsed = {f: None for f in cd.FIELDS}
    parsed["address"] = "\xa0"
    parsed["business_hours"] = "   "
    assert cd.is_soft_removed(parsed) is True


def test_predicate_true_for_chrome_only_when_no_material_field():
    # Muted-only content (e.g. a rotating image) does NOT keep a page alive:
    # material is what makes an onsen real.
    parsed = {f: None for f in cd.FIELDS}
    parsed["image_url"] = "https://example.com/photo.jpg"
    assert cd.is_soft_removed(parsed) is True


def test_predicate_false_for_one_material_field():
    # Conservative: a single material detail keeps the page "live".
    parsed = {f: None for f in cd.FIELDS}
    parsed["address"] = "鹿児島県薩摩郡さつま町"
    assert cd.is_soft_removed(parsed) is False


def test_predicate_false_for_normal_populated_parse():
    parsed = {f: None for f in cd.FIELDS}
    parsed.update({
        "prefecture": "鹿児島県",
        "address": "鹿児島県薩摩郡さつま町",
        "business_hours": "9:00〜21:00",
        "admission_fee": "大人 500円",
        "spring_quality": "単純硫黄泉",
    })
    assert cd.is_soft_removed(parsed) is False


def test_predicate_true_for_parsed_delisted_chrome():
    # Run the real parser over a chrome-only page → all material None → soft-removed.
    parsed = parse_detail_page(DELISTED_HTML, 99999)
    fields = {f: parsed.get(f) for f in cd.FIELDS}
    assert cd.is_soft_removed(fields) is True


@pytest.mark.skipif(not SNAPSHOT_DB.exists(), reason="snapshot.db not present")
def test_predicate_false_on_real_snapshot_page():
    # Realism check: a genuine page from the snapshot parses to ≥1 material field,
    # so the predicate must NOT flag it as removed.
    db = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute(
            "SELECT id, raw_html FROM onsens WHERE raw_html IS NOT NULL LIMIT 1"
        ).fetchone()
    finally:
        db.close()
    assert row is not None, "expected at least one snapshot row with raw_html"
    parsed = parse_detail_page(row["raw_html"], row["id"])
    fields = {f: parsed.get(f) for f in cd.FIELDS}
    assert cd.is_soft_removed(fields) is False


# --- diff() routing ----------------------------------------------------------

def _populated(**over):
    base = {f: None for f in cd.FIELDS}
    base.update({
        "prefecture": "鹿児島県",
        "address": "鹿児島県薩摩郡さつま町",
        "business_hours": "9:00〜21:00",
        "admission_fee": "大人 500円",
        "spring_quality": "単純硫黄泉",
    })
    base.update(over)
    return base


def test_diff_routes_empty_live_to_removed_not_modified():
    hid = 248
    baseline = {hid: _populated()}
    # scrape_live returns {} for a delisted page (HTTP 200, no detail); {} → removed.
    # (A genuine fetch error is None and routes to fetchFailed instead.)
    live = {hid: {}}
    idmap = {str(hid): "uuid-248"}

    out = cd.diff(baseline, live, idmap)

    removed_hids = [r["hid"] for r in out["removed"]]
    modified_hids = [m["hid"] for m in out["modified"]]
    failed_hids = [r["hid"] for r in out["fetchFailed"]]
    assert removed_hids == [hid]
    assert hid not in modified_hids
    assert hid not in failed_hids
    assert out["removed"][0]["kyuhachiId"] == "uuid-248"
    assert out["removed"][0]["reason"] == "empty detail page"


def test_diff_fetch_error_is_fetch_failed_not_removed():
    # None (a genuine FetchError after retries) is NOT a clean removal signal.
    hid = 248
    baseline = {hid: _populated()}
    live = {hid: None}
    idmap = {str(hid): "uuid-248"}

    out = cd.diff(baseline, live, idmap)

    assert [r["hid"] for r in out["fetchFailed"]] == [hid]
    assert hid not in [r["hid"] for r in out["removed"]]


def test_diff_index_absence_routes_to_removed():
    # With --discover, a baseline hid absent from the source index is an
    # authoritative delisting — removed without even needing a fetch.
    hid = 248
    baseline = {hid: _populated()}
    idmap = {str(hid): "uuid-248"}

    out = cd.diff(baseline, {}, idmap, index_ids={1, 2, 3})

    assert [r["hid"] for r in out["removed"]] == [hid]
    assert out["removed"][0]["reason"] == "not on source index"
    assert hid not in [r["hid"] for r in out["fetchFailed"]]


def test_diff_added_detected_for_new_listed_onsen():
    # An hid in live (scraped from the index) but absent from baseline, with real
    # content, is a NEW onsen → added, surfaced with prefecture/address.
    new = 300
    baseline = {10: _populated()}
    live = {10: _populated(), new: _populated(prefecture="大分県", address="別府市")}
    idmap = {"10": "uuid-10"}

    out = cd.diff(baseline, live, idmap, index_ids={10, new})

    assert [a["hid"] for a in out["added"]] == [new]
    assert out["added"][0]["prefecture"] == "大分県"
    assert new not in [r["hid"] for r in out["removed"]]


def test_diff_genuine_modification_still_lands_in_modified():
    hid = 10
    baseline = {hid: _populated(admission_fee="大人 500円")}
    live = {hid: _populated(admission_fee="大人 700円")}
    idmap = {str(hid): "uuid-10"}

    out = cd.diff(baseline, live, idmap)

    modified_hids = [m["hid"] for m in out["modified"]]
    removed_hids = [r["hid"] for r in out["removed"]]
    assert modified_hids == [hid]
    assert hid not in removed_hids
    assert out["modified"][0]["severity"] == "material"
    assert "admission_fee" in out["modified"][0]["materialFields"]


def test_diff_unchanged_onsen_in_neither_bucket():
    hid = 20
    same = _populated()
    baseline = {hid: dict(same)}
    live = {hid: dict(same)}
    idmap = {str(hid): "uuid-20"}

    out = cd.diff(baseline, live, idmap)

    assert out["modified"] == []
    assert out["removed"] == []
    assert out["fetchFailed"] == []


def test_diff_missing_live_hid_is_fetch_failed_not_removed():
    # hid never reached this run (absent from `live`) → transient fetchFailed,
    # NOT removed. Guards the existing removed-vs-fetchFailed contract.
    hid = 30
    baseline = {hid: _populated()}
    live = {}  # nothing scraped for this hid
    idmap = {str(hid): "uuid-30"}

    out = cd.diff(baseline, live, idmap)

    failed_hids = [r["hid"] for r in out["fetchFailed"]]
    removed_hids = [r["hid"] for r in out["removed"]]
    assert failed_hids == [hid]
    assert hid not in removed_hids
