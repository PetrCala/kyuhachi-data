"""Tests for the apply.py `add` action — building a new onsen's create-doc from
the /map seed + detail scrape + curated hours + generated reading.

Fully offline: the network sources (map seed, detail fetch) and the reading
resolvers are monkeypatched, and the dry-run path (tok=None) performs no Firestore
or Storage write — so nothing here scrapes, authenticates, or writes."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "publisher"))
sys.path.insert(0, str(REPO / ".claude/skills/catalog-diff"))

import apply  # noqa: E402  (publisher/apply.py — the surgical publisher)


FAKE_SEED = {999: {"name": "テスト湯", "areaName": "テスト温泉",
                   "address": "X県Z市", "lat": 33.5, "lng": 130.5}}
FAKE_DETAIL = {
    "prefecture": "X県", "address": "X県Y市1-2-3", "phone": "0120-000-000",
    "admission_fee": "大人 500円", "spring_quality": "単純温泉",
    "website_url": "https://example.com/", "business_hours": "10:00～22:00\n無休",
    "image_url": "https://www.88onsen.com/upload/x.jpg",
}
_OPEN_ALL = {"status": "ok", "publish": True, "window": ["10:00", "22:00"],
             "closed": [], "overrides": {}, "exceptions": [], "confidence": "high"}


@pytest.fixture
def patched(monkeypatch):
    """Stub every network/auth source so build_add runs offline against fixtures."""
    monkeypatch.setattr(apply, "map_seed", lambda: FAKE_SEED)
    monkeypatch.setattr(apply, "curated_hours", lambda: {"999": dict(_OPEN_ALL)})
    monkeypatch.setattr(apply, "fetch_detail_page", lambda hid: "<html/>")
    monkeypatch.setattr(apply, "parse_detail_page", lambda html, hid: dict(FAKE_DETAIL))
    monkeypatch.setattr(apply, "kana_for", lambda hid, name: "てすとゆ")
    monkeypatch.setattr(apply, "romaji_for", lambda hid, name: "Tesuto Yu")
    monkeypatch.setitem(apply.IDMAP, "999", "kid-999")


def test_build_add_matches_onsen_doc_contract(patched):
    fields, _summary = apply.build_add(999, tok=None)   # dry-run: no upload / version read
    fields["createdAt"] = {"timestampValue": "t"}        # added by apply_decision
    fields["updatedAt"] = {"timestampValue": "t"}
    assert set(fields) == apply.ONSEN_DOC_KEYS           # exact OnsenDocument shape

    assert fields["name"] == {"stringValue": "テスト湯"}
    assert fields["nameKana"] == {"stringValue": "てすとゆ"}
    assert fields["areaName"] == {"stringValue": "テスト温泉"}
    assert fields["prefecture"] == {"stringValue": "X県"}
    assert fields["address"] == {"stringValue": "X県Y市1-2-3"}   # detail wins over seed
    assert fields["lat"] == {"doubleValue": 33.5}               # numbers, not GeoPoint
    assert fields["lng"] == {"doubleValue": 130.5}
    assert fields["isActive"] == {"booleanValue": True}
    assert fields["adultFee"] == {"integerValue": "500"}        # derived from fee text
    # a dry-run leaves the photo + catalog version unresolved (filled on --commit)
    assert fields["imageUrl"] == {"nullValue": None}
    assert fields["blurhash"] == {"nullValue": None}
    assert fields["catalogVersion"] == {"nullValue": None}


def test_build_add_business_hours_from_curated(patched):
    fields, _ = apply.build_add(999, tok=None)
    bh = fields["businessHours"]["mapValue"]["fields"]
    assert bh["raw"] == {"stringValue": "10:00～22:00\n無休"}
    sched = bh["schedule"]["mapValue"]["fields"]
    assert set(sched) == set(apply.bsf.DAYS_FULL)              # full 7-day grid
    assert sched["monday"]["mapValue"]["fields"] == {
        "opens": {"stringValue": "10:00"}, "closes": {"stringValue": "22:00"}}


def test_publish_false_new_onsen_keeps_raw_but_null_schedule(monkeypatch, patched):
    closed_entry = dict(_OPEN_ALL, publish=False)
    monkeypatch.setattr(apply, "curated_hours", lambda: {"999": closed_entry})
    fields, _ = apply.build_add(999, tok=None)
    bh = fields["businessHours"]["mapValue"]["fields"]
    assert bh["schedule"] == {"nullValue": None}              # publish:false → no grid
    assert bh["raw"]["stringValue"]                           # raw fallback preserved


def test_validate_add_schema_guards_the_contract():
    good = {k: {"nullValue": None} for k in apply.ONSEN_DOC_KEYS}
    apply.validate_add_schema(good, tok=None)                 # exact match → ok
    with pytest.raises(SystemExit):
        apply.validate_add_schema({k: v for k, v in good.items() if k != "lat"}, tok=None)
    with pytest.raises(SystemExit):
        apply.validate_add_schema(dict(good, mysteryField={"nullValue": None}), tok=None)


def test_add_decision_dry_run_previews_without_writing(patched, capsys):
    # tok=None, commit=False → preview only; create() is never reached (would need net).
    apply.apply_decision({"hid": 999, "action": "add", "note": "new onsen"},
                         now="t", tok=None, commit=False)
    out = capsys.readouterr().out
    assert "ADD (new onsen)" in out
    assert "would create" in out
    assert "created." not in out
