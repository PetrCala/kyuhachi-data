"""Tests for the shared Firestore REST helpers (publisher/firestore_rest.py) and
that every publisher script that used to copy-paste them (apply.py,
backfill_fees.py, backfill_name_kana.py, backfill_name_romaji.py,
backfill_schedule.py — roadmap item C) still imports cleanly and builds its
offline plan against the shared module. Fully offline — no network, no auth, no
writes."""
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
    import backfill_fees  # noqa: E402
    import backfill_name_kana  # noqa: E402
    import backfill_name_romaji  # noqa: E402
    import backfill_schedule  # noqa: E402

    backfills = (backfill_fees, backfill_name_kana, backfill_name_romaji, backfill_schedule)
    # patch is shared by every writer.
    for mod in (apply, *backfills):
        assert mod.patch is fr.patch
    # the four backfills share the version bump + the no-op live read.
    for mod in backfills:
        assert mod.bump_catalog_version is fr.bump_catalog_version
        assert mod.live_onsens is fr.live_onsens
    # the scalar-field backfills read live values through the shared decoder.
    for mod in (backfill_fees, backfill_name_kana, backfill_name_romaji):
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
    import backfill_fees  # noqa: E402
    import backfill_name_kana  # noqa: E402
    import backfill_name_romaji  # noqa: E402
    import backfill_schedule  # noqa: E402

    con = sqlite3.connect(f"file:{REPO / 'data' / 'snapshot.db'}?mode=ro", uri=True)
    snap_ids = {r[0] for r in con.execute("select id from onsens")}
    con.close()

    for mod in (backfill_fees, backfill_name_kana, backfill_name_romaji, backfill_schedule):
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
