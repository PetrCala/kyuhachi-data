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


def test_base_url_derived_from_project():
    assert fr.PROJECT == "kyuhachi-fddcc"
    assert fr.BASE == (
        "https://firestore.googleapis.com/v1/projects/kyuhachi-fddcc/"
        "databases/(default)/documents"
    )


def test_every_publisher_script_shares_firestore_rest():
    """Importing must not re-define a local copy — each script's token/patch/
    (bump_catalog_version, where applicable) must literally be firestore_rest's."""
    import apply  # noqa: E402
    import backfill_fees  # noqa: E402
    import backfill_name_kana  # noqa: E402
    import backfill_name_romaji  # noqa: E402
    import backfill_schedule  # noqa: E402

    scripts = (apply, backfill_fees, backfill_name_kana, backfill_name_romaji, backfill_schedule)
    for mod in scripts:
        assert mod.token is fr.token
        assert mod.patch is fr.patch
    for mod in (backfill_fees, backfill_name_kana, backfill_name_romaji, backfill_schedule):
        assert mod.bump_catalog_version is fr.bump_catalog_version
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
