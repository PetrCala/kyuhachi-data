"""Tests for the shared Firestore REST helpers (publisher/firestore_rest.py) and
that every publisher script that used to copy-paste them (apply.py,
backfill_fees.py, backfill_name_kana.py, backfill_name_romaji.py,
backfill_schedule.py, backfill_data_verified_at.py — roadmap item C) still
imports cleanly and builds its offline plan against the shared module. Fully
offline — no network, no auth, no writes."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "publisher"))

import firestore_rest as fr  # noqa: E402


def test_typed_value_encoders():
    assert fr.sval("x") == {"stringValue": "x"}
    assert fr.sval("") == {"nullValue": None}
    assert fr.sval(None) == {"nullValue": None}
    assert fr.ival(5) == {"integerValue": "5"}
    assert fr.ival(None) == {"nullValue": None}
    assert fr.dval(1.5) == {"doubleValue": 1.5}
    assert fr.dval(None) == {"nullValue": None}
    assert fr.bval(True) == {"booleanValue": True}
    assert fr.bval(False) == {"booleanValue": False}


def test_decode_value_round_trips_encoders():
    # decode_value is the inverse of the sval/ival/dval/bval encoders.
    assert fr.decode_value(fr.sval("x")) == "x"
    assert fr.decode_value(fr.sval("")) is None          # falsy string → null → None
    assert fr.decode_value(fr.ival(5)) == 5              # integerValue is a *string* on the wire
    assert fr.decode_value(fr.ival(0)) == 0
    assert fr.decode_value(fr.dval(1.5)) == 1.5
    assert fr.decode_value(fr.bval(True)) is True
    assert fr.decode_value(fr.bval(False)) is False
    assert fr.decode_value({"nullValue": None}) is None
    assert fr.decode_value(None) is None
    assert fr.decode_value({}) is None


def test_decode_value_nested_map_and_array():
    v = {"mapValue": {"fields": {
        "opens": {"stringValue": "10:00"},
        "n": {"integerValue": "3"},
        "days": {"arrayValue": {"values": [{"stringValue": "mon"}, {"nullValue": None}]}},
    }}}
    assert fr.decode_value(v) == {"opens": "10:00", "n": 3, "days": ["mon", None]}
    assert fr.decode_value({"arrayValue": {}}) == []     # empty/absent values → []


def test_field_at_flat_and_nested():
    fields = {
        "prefecture": {"stringValue": "福岡県"},
        "businessHours": {"mapValue": {"fields": {"raw": {"stringValue": "10:00~22:00"}}}},
    }
    assert fr.field_at(fields, "prefecture") == "福岡県"
    assert fr.field_at(fields, "businessHours.raw") == "10:00~22:00"      # walks the nested map
    assert fr.field_at(fields, "businessHours.schedule") is None          # missing leaf → None
    assert fr.field_at(fields, "nope") is None                            # missing top → None
    assert fr.field_at({}, "businessHours.raw") is None                   # empty doc → None


# --- paginated collection reads (REST layer mocked) --------------------------

class _Resp:
    """Minimal urlopen stand-in: a context manager whose read() yields JSON bytes."""
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _mock_open(monkeypatch, pages):
    """Patch fr._open to hand back `pages` in order, recording each requested URL."""
    seen = []
    it = iter(pages)

    def fake(req, timeout=30, retries=3):
        seen.append(req.full_url)
        return _Resp(next(it))

    monkeypatch.setattr(fr, "_open", fake)
    return seen


def test_list_documents_follows_pagination(monkeypatch):
    pages = [
        {"documents": [{"name": "projects/p/.../onsens/a", "fields": {}},
                       {"name": "projects/p/.../onsens/b", "fields": {}}],
         "nextPageToken": "PAGE2//tok"},
        {"documents": [{"name": "projects/p/.../onsens/c", "fields": {}}]},  # no token → last page
    ]
    seen = _mock_open(monkeypatch, pages)
    docs = list(fr.list_documents("onsens", "TOK", page_size=2))

    assert [d["name"].rsplit("/", 1)[-1] for d in docs] == ["a", "b", "c"]
    assert len(seen) == 2                                   # exactly two page requests
    assert "pageSize=2" in seen[0] and "pageToken" not in seen[0]
    assert "pageToken=PAGE2%2F%2Ftok" in seen[1]           # token URL-encoded and forwarded


def test_fetch_collection_keys_by_doc_id(monkeypatch):
    pages = [{"documents": [
        {"name": "projects/p/databases/(default)/documents/onsens/kid-A",
         "fields": {"nameKana": {"stringValue": "はかたゆ"}}},
        {"name": "projects/p/databases/(default)/documents/onsens/kid-B",
         "fields": {"adultFee": {"integerValue": "350"}}},
    ]}]
    _mock_open(monkeypatch, pages)
    got = fr.fetch_collection("onsens", "TOK")

    assert set(got) == {"kid-A", "kid-B"}                   # keyed by the doc id (kyuhachiId)
    assert fr.field_at(got["kid-A"], "nameKana") == "はかたゆ"
    assert fr.field_at(got["kid-B"], "adultFee") == 350


def _onsen_page(*docs):
    """One list-documents page: (docId, isActive) pairs → the wire shape."""
    return {"documents": [
        {"name": f"projects/p/databases/(default)/documents/onsens/{kid}",
         "fields": {"isActive": fr.bval(active)}}
        for kid, active in docs
    ]}


def test_onsen_counts_separates_total_from_active(monkeypatch):
    # A retired onsen is still a document: it counts toward total, not active.
    _mock_open(monkeypatch, [_onsen_page(("a", True), ("b", True), ("retired", False))])
    assert fr.onsen_counts("TOK") == (3, 2)


def _onsen_fields(name, romaji, area, pref, lat, lng, active=True):
    """One /onsens document's `fields`, as the REST API returns it."""
    return {
        "name": fr.sval(name), "nameRomaji": fr.sval(romaji),
        "areaName": fr.sval(area), "prefecture": fr.sval(pref),
        "lat": fr.dval(lat), "lng": fr.dval(lng), "isActive": fr.bval(active),
    }


def _capture_patches(monkeypatch):
    """Record every patch() call as {path: (fields, mask)} instead of writing."""
    wrote = {}

    def fake_patch(path, fields, mask, tok):
        wrote[path] = (fields, mask)
        return 200

    monkeypatch.setattr(fr, "patch", fake_patch)
    return wrote


def test_bump_catalog_version_refreshes_both_counts(monkeypatch):
    # get_fields (the current doc) and the collection read are separate calls;
    # patch both so the test stays offline, and capture what would be written.
    monkeypatch.setattr(fr, "get_fields", lambda path, tok: {"version": {"integerValue": "22"}})
    monkeypatch.setattr(fr, "fetch_collection", lambda coll, tok: {
        "a": _onsen_fields("竹瓦温泉", "Takegawara Onsen", "別府温泉", "大分県", 33.2, 131.4),
        "retired": _onsen_fields("旧温泉", None, "別府温泉", "大分県", 33.3, 131.5, active=False),
    })
    wrote = _capture_patches(monkeypatch)
    fr.bump_catalog_version("2026-08-31T00:00:00.000000Z", "TOK")

    fields, mask = wrote["catalog_meta/current"]
    # Every field written is also masked, or the PATCH silently drops it.
    assert set(mask) == {"version", "publishedAt", "totalCount", "activeCount"}
    assert set(fields) == set(mask)
    assert fields["version"] == {"integerValue": "23"}
    assert fields["totalCount"] == fr.ival(2)
    assert fields["activeCount"] == fr.ival(1)


def test_bump_catalog_version_republishes_the_index_at_the_same_version(monkeypatch):
    # The index is derived from the same read and stamped with the same version,
    # so the website can never serve an index older than the published catalog.
    monkeypatch.setattr(fr, "get_fields", lambda path, tok: {"version": {"integerValue": "22"}})
    monkeypatch.setattr(fr, "fetch_collection", lambda coll, tok: {
        "a": _onsen_fields("竹瓦温泉", "Takegawara Onsen", "別府温泉", "大分県", 33.2, 131.4),
    })
    wrote = _capture_patches(monkeypatch)
    fr.bump_catalog_version("2026-08-31T00:00:00.000000Z", "TOK")

    assert set(wrote) == {"catalog_meta/current", "catalog_index/current"}
    index, mask = wrote["catalog_index/current"]
    assert set(index) == set(mask)          # a masked-out field is silently dropped
    assert index["version"] == fr.ival(23)  # the NEW catalog version, not 22
    assert index["version"] == wrote["catalog_meta/current"][0]["version"]


def test_bump_catalog_version_writes_nothing_when_the_doc_is_absent(monkeypatch):
    monkeypatch.setattr(fr, "get_fields", lambda path, tok: None)

    def unreachable(*a, **k):
        raise AssertionError("must not count or write when catalog_meta is absent")

    monkeypatch.setattr(fr, "fetch_collection", unreachable)
    monkeypatch.setattr(fr, "patch", unreachable)
    fr.bump_catalog_version("2026-08-31T00:00:00.000000Z", "TOK")


# --- /catalog_index/current -------------------------------------------------


def test_index_entries_are_positional_sorted_and_include_retired_onsens():
    live = {
        "b-kid": _onsen_fields("湯乃屋", "Yunoya", "由布院", "大分県", 33.26, 131.36),
        "a-kid": _onsen_fields("竹瓦温泉", "Takegawara Onsen", "別府温泉", "大分県",
                               33.2, 131.4),
        "z-retired": _onsen_fields("旧温泉", None, "別府温泉", "大分県", 33.3, 131.5,
                                   active=False),
    }
    rows = fr.index_entries(live)

    # Ordered by kyuhachiId, so an unchanged catalog republishes byte-identically.
    assert [r[0] for r in rows] == ["a-kid", "b-kid", "z-retired"]
    # The tuple order IS the contract the website reads by position.
    assert rows[0] == ["a-kid", "竹瓦温泉", "Takegawara Onsen", "別府温泉", "大分県",
                       33.2, 131.4]
    # A retired onsen is still indexed: the site has to place a visit to one.
    assert rows[2][0] == "z-retired"
    # An onsen without a romaji reading carries null, not a fallback to the kanji.
    assert rows[2][2] is None


def test_index_entries_round_coordinates_to_five_places():
    live = {"k": _onsen_fields("温泉", "Onsen", "別府温泉", "大分県",
                               33.2841234567, 131.4919876543)}
    assert fr.index_entries(live)[0][5:] == [33.28412, 131.49199]


def test_catalog_index_fields_pack_entries_as_one_utf8_json_string():
    live = {"k": _onsen_fields("竹瓦温泉", "Takegawara Onsen", "別府温泉", "大分県",
                               33.2, 131.4)}
    fields = fr.catalog_index_fields(7, "2026-08-31T00:00:00.000000Z", live)

    assert fields["schemaVersion"] == fr.ival(fr.CATALOG_INDEX_SCHEMA_VERSION)
    assert fields["version"] == fr.ival(7)
    assert fields["count"] == fr.ival(1)
    packed = fields["entries"]["stringValue"]
    # A string, not an arrayValue: the array shape is what this document exists
    # to avoid, and it would silently more than double the payload.
    assert set(fields["entries"]) == {"stringValue"}
    assert json.loads(packed) == fr.index_entries(live)
    # Raw UTF-8, not \uXXXX escapes, and no whitespace between values: both
    # would inflate the one field the whole document exists to keep small.
    assert "竹瓦温泉" in packed
    assert "\\u" not in packed
    assert ", " not in packed


def test_publish_catalog_index_masks_every_field_it_writes(monkeypatch):
    wrote = _capture_patches(monkeypatch)
    live = {"k": _onsen_fields("竹瓦温泉", "Takegawara Onsen", "別府温泉", "大分県",
                               33.2, 131.4)}
    fr.publish_catalog_index(7, "2026-08-31T00:00:00.000000Z", live, "TOK")

    fields, mask = wrote["catalog_index/current"]
    assert set(mask) == set(fields)
    assert set(mask) == {"schemaVersion", "version", "publishedAt", "count", "entries"}


def test_live_onsens_degrades_on_dry_run_but_raises_on_commit(monkeypatch, capsys):
    def boom():
        raise RuntimeError("no gcloud ADC")

    monkeypatch.setattr(fr, "token", boom)
    # dry-run: a read failure is non-fatal — (None, None) + a printed note.
    tok, live = fr.live_onsens(commit=False)
    assert tok is None and live is None
    assert "could not read live catalog" in capsys.readouterr().out
    # commit: writes need auth, so the failure propagates.
    with pytest.raises(RuntimeError):
        fr.live_onsens(commit=True)


def test_base_url_derived_from_project():
    assert fr.PROJECT == "kyuhachi-fddcc"
    assert fr.BASE == (
        "https://firestore.googleapis.com/v1/projects/kyuhachi-fddcc/"
        "databases/(default)/documents"
    )


def test_every_publisher_script_shares_firestore_rest():
    """Importing must not re-define a local copy — each script's shared helpers must
    literally be firestore_rest's (not a copy-pasted redefinition)."""
    import apply  # noqa: E402
    import backfill_data_verified_at  # noqa: E402
    import backfill_fees  # noqa: E402
    import backfill_name_kana  # noqa: E402
    import backfill_name_romaji  # noqa: E402
    import backfill_schedule  # noqa: E402

    backfills = (backfill_data_verified_at, backfill_fees, backfill_name_kana,
                 backfill_name_romaji, backfill_schedule)
    # patch is shared by every writer.
    for mod in (apply, *backfills):
        assert mod.patch is fr.patch
    # the five backfills share the version bump + the no-op live read.
    for mod in backfills:
        assert mod.bump_catalog_version is fr.bump_catalog_version
        assert mod.live_onsens is fr.live_onsens
    # the scalar-field backfills read live values through the shared decoder.
    for mod in (backfill_data_verified_at, backfill_fees, backfill_name_kana, backfill_name_romaji):
        assert mod.field_at is fr.field_at
    # apply + the curated-schedule read still mint tokens directly.
    assert apply.token is fr.token and backfill_schedule.token is fr.token
    assert backfill_schedule.get_fields is fr.get_fields
    assert apply.create is fr.create
    assert apply.sval is fr.sval and apply.ival is fr.ival
    assert apply.dval is fr.dval and apply.bval is fr.bval


def test_backfill_scripts_build_their_plan_offline():
    """Each backfill's build_plan() reads only the local snapshot DB — no
    network, no auth — and covers every onsen in it."""
    pytest.importorskip("pykakasi")
    import backfill_data_verified_at  # noqa: E402
    import backfill_fees  # noqa: E402
    import backfill_name_kana  # noqa: E402
    import backfill_name_romaji  # noqa: E402
    import backfill_schedule  # noqa: E402

    con = sqlite3.connect(f"file:{REPO / 'data' / 'snapshot.db'}?mode=ro", uri=True)
    snap_ids = {r[0] for r in con.execute("select id from onsens")}
    con.close()

    for mod in (backfill_data_verified_at, backfill_fees, backfill_name_kana,
                backfill_name_romaji, backfill_schedule):
        plan = mod.build_plan()
        assert {p[0] for p in plan} == snap_ids


def test_apply_scaffold_builds_its_plan_offline(tmp_path):
    """apply.py has no build_plan(), but --from-changelog is its offline plan-
    building path (no writes, no auth) — exercise it the same way."""
    import apply  # noqa: E402

    changelog = {
        "modified": [{"hid": 1, "severity": "material", "materialFields": ["phone"]}],
        "removed": [{"hid": 2}],
        "added": [{"hid": 3}],
        "fetchFailed": [{"hid": 4}],
    }
    cl_path = tmp_path / "changelog.json"
    cl_path.write_text(json.dumps(changelog), encoding="utf-8")
    skeleton = apply.scaffold_from_changelog(cl_path)
    assert {d["hid"]: d["action"] for d in skeleton} == {1: "update", 2: "retire", 3: "add", 4: "skip"}
