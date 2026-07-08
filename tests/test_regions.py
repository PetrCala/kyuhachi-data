"""Tests for the coarse tourism-region model (onsen_scraper/regions.py).

Covers the pure assignment rule (region_for), area-name normalization, the stable
areaId ledger, and the region-model builder over the real snapshot DB + id maps.
Fully offline: no network, no auth, no writes."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from onsen_scraper import regions as R  # noqa: E402


# --- normalization ------------------------------------------------------------

def test_normalize_strips_appended_date_notice():
    assert R.normalize_area_name(
        "くにさき六郷温泉　　2026年度設定急遽中止です。ご注意ください"
    ) == "くにさき六郷温泉"


def test_normalize_strips_keyword_notice():
    assert R.normalize_area_name(
        "雲仙・小地獄温泉　営業時間が通年9：30～19：00に改定"
    ) == "雲仙・小地獄温泉"


def test_normalize_preserves_genuine_multitoken_name():
    # A space with no trailing date/keyword is a real part of the name.
    assert R.normalize_area_name("大阿蘇　火の山温泉") == "大阿蘇　火の山温泉"


def test_normalize_none_passthrough():
    assert R.normalize_area_name(None) is None


# --- region_for ---------------------------------------------------------------

def test_single_region_prefecture_maps_any_area():
    # Kagoshima is a single-region prefecture: any area name lands in it.
    assert R.region_for("指宿温泉", "鹿児島県") == "kagoshima"
    assert R.region_for("まだ無い温泉", "鹿児島県") == "kagoshima"


def test_split_prefecture_maps_by_area_name():
    assert R.region_for("別府温泉", "大分県") == "oita-beppu"
    assert R.region_for("由布院温泉", "大分県") == "oita-yufuin"
    assert R.region_for("阿蘇内牧温泉", "熊本県") == "kumamoto-aso"
    assert R.region_for("人吉温泉", "熊本県") == "kumamoto-hitoyoshi"


def test_split_prefecture_assigns_via_normalized_name():
    # The notice-suffixed source name still assigns to its region.
    assert R.region_for(
        "くにさき六郷温泉　　2026年度…中止", "大分県") == "oita-kunisaki"


def test_unknown_area_in_split_prefecture_is_unplaced():
    # A novel area name in a split prefecture is left unplaced, not guessed.
    assert R.region_for("架空温泉", "大分県") is None


def test_unknown_prefecture_is_unplaced():
    assert R.region_for("別府温泉", "X県") is None


# --- id ledger ----------------------------------------------------------------

def test_area_id_map_covers_every_region_with_uuids():
    ledger = R.load_area_id_map()
    for key in R.REGIONS:
        assert key in ledger, f"{key} has no areaId in the ledger"
        assert len(ledger[key]) == 36 and ledger[key].count("-") == 4  # uuid shape


def test_mint_missing_is_idempotent_dry():
    # With every key already present, minting proposes no change.
    before = R.load_area_id_map()
    after = R.mint_missing_area_ids(commit=False)
    assert {k: after[k] for k in before} == before


# --- builder ------------------------------------------------------------------

def test_build_region_model_places_every_onsen():
    model = R.build_region_model()
    assert model["unassigned"] == []
    assert len(model["regions"]) == len(R.REGIONS)
    total = sum(r["memberCount"] for r in model["regions"])
    assert total == 161  # the whole catalog is placed


def test_every_region_has_id_center_and_consistent_members():
    for r in R.build_region_model()["regions"]:
        assert r["areaId"], f"{r['key']} missing areaId"
        assert r["center"] and "lat" in r["center"] and "lng" in r["center"]
        # every placed hid resolves to a kyuhachiId (the catalog is fully mapped)
        assert len(r["memberOnsenIds"]) == r["memberCount"] == len(r["memberHids"])


def test_centroid_lies_within_member_bounds():
    import json
    import sqlite3
    idmap = json.loads((REPO / "data/onsen-id-map.json").read_text())
    con = sqlite3.connect(f"file:{R.SNAPSHOT_DB}?mode=ro", uri=True)
    geo = {str(i): (la, lo) for i, la, lo in
           con.execute("select id, latitude, longitude from onsens")}
    con.close()
    hid_by_kid = {v: k for k, v in idmap.items()}
    for r in R.build_region_model()["regions"]:
        lats = [geo[hid_by_kid[k]][0] for k in r["memberOnsenIds"]]
        lngs = [geo[hid_by_kid[k]][1] for k in r["memberOnsenIds"]]
        assert min(lats) <= r["center"]["lat"] <= max(lats)
        assert min(lngs) <= r["center"]["lng"] <= max(lngs)
