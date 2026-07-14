"""Tests for the area-guides publisher (publisher/publish_area_guides.py).

Covers section canonicalization, the Firestore typed-value encoders + the doc-key
contract, the not-publishable skips, and the decode round-trip that drives no-op
detection. Also checks the shipped curated content parses and defaults to an
unreviewed state (so --commit is blocked until a human review). Fully offline: no
network, no auth, no writes (main()/read_live are never invoked)."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "publisher"))

import publish_area_guides as P  # noqa: E402

MODEL = {r["key"]: r
         for r in json.loads((REPO / "data/area-regions.json").read_text())["regions"]}
CURATED_DOC = json.loads((REPO / "data/area_guides_curated.json").read_text())
CURATED = CURATED_DOC["regions"]


# --- section canonicalization -------------------------------------------------

def test_canonical_sections_orders_by_kind_and_drops_empty_highlights():
    raw = [
        {"kind": "culture", "body": {"en": "c", "ja": "文"}},
        {"kind": "specialties", "body": {"en": "s", "ja": "食"}, "highlights": []},
        {"kind": "history", "body": {"en": "h", "ja": "史"},
         "highlights": [{"en": "x", "ja": "エックス"}]},
    ]
    out = P.canonical_sections(raw)
    assert [s["kind"] for s in out] == ["specialties", "history", "culture"]
    assert "highlights" not in out[0]                 # empty list dropped
    assert out[1]["highlights"] == [{"en": "x", "ja": "エックス"}]


# --- encoders + doc contract --------------------------------------------------

def test_guide_fields_matches_the_doc_key_contract():
    (_aid, content), reason = P.region_content("oita-beppu", CURATED["oita-beppu"], MODEL)
    assert reason is None
    fields = P.guide_fields(content, version=3, now="t")
    assert set(fields) == P.GUIDE_DOC_KEYS
    assert fields["version"] == {"integerValue": "3"}
    assert fields["center"]["mapValue"]["fields"]["lat"]["doubleValue"] == \
        content["center"]["lat"]


def test_absent_tagline_encodes_as_null():
    content = {"name": {"en": "N", "ja": "名"}, "tagline": None,
               "center": {"lat": 1.0, "lng": 2.0},
               "sections": [{"kind": "history", "body": {"en": "h", "ja": "史"}}]}
    fields = P.guide_fields(content, version=1, now="t")
    assert fields["tagline"] == {"nullValue": None}


# --- not-publishable skips ----------------------------------------------------

def test_region_content_skips_when_no_area_id():
    bad_model = {"ghost": {"areaId": None, "center": {"lat": 1, "lng": 2}}}
    result, reason = P.region_content("ghost", CURATED["oita-beppu"], bad_model)
    assert result is None and "areaId" in reason


def test_region_content_skips_when_no_sections():
    key = "oita-beppu"
    empty = dict(CURATED[key], sections=[])
    result, reason = P.region_content(key, empty, MODEL)
    assert result is None and "section" in reason


# --- no-op detection round-trip -----------------------------------------------

def test_encoded_doc_round_trips_for_noop_detection():
    # What we would write, decoded back, must equal the desired content so a
    # re-publish of unchanged content is correctly detected as current.
    for key in ("oita-beppu", "kagoshima", "kumamoto-aso"):
        (_aid, content), _ = P.region_content(key, CURATED[key], MODEL)
        fields = P.guide_fields(content, version=1, now="t")
        assert P.live_content(fields) == content


# --- shipped content invariants ----------------------------------------------

def test_every_model_region_has_reviewable_curated_content():
    assert set(CURATED) == set(MODEL)
    valid = set(P.SECTION_ORDER)
    for key, c in CURATED.items():
        assert set(c["name"]) == {"en", "ja"}
        kinds = [s["kind"] for s in c["sections"]]
        assert kinds and all(k in valid for k in kinds)
        assert len(kinds) == len(set(kinds))          # no duplicate kinds


def test_reviewed_status_is_backed_by_a_substantive_review_note():
    # The gate: publish refuses --commit unless this is 'reviewed'. That must never
    # be a bare flip: if it says 'reviewed', reviewNote has to actually describe
    # what review happened (so an accidental/unjustified flip is still caught).
    meta = CURATED_DOC["_meta"]
    if meta["reviewStatus"] == "reviewed":
        assert len(meta.get("reviewNote", "")) > 80
    else:
        assert meta["reviewStatus"] == "draft-unreviewed"
