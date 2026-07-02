"""Tests for the dataVerifiedAt backfill's plan builder and monotonic write
guard (publisher/backfill_data_verified_at.py).

Fully offline: `build_plan()` is exercised against a synthetic sqlite fixture
(SNAPSHOT_DB/IDMAP monkeypatched) so it never touches the real
data/snapshot.db, and `split_writes` against literal {kid: fields} dicts — no
network/auth path is reached (dry-run only)."""
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "publisher"))

import backfill_data_verified_at as bdv  # noqa: E402


# --- _to_rfc3339 ----------------------------------------------------------

def test_to_rfc3339_normalizes_naive_space_separated_baseline_format():
    # The original scaffold import's format: no "T", no "Z".
    assert bdv._to_rfc3339("2026-02-10 10:03:31.038834") == "2026-02-10T10:03:31.038834Z"


def test_to_rfc3339_passes_through_proper_rfc3339():
    # catalog_sync.py's _now() format, written by `promote` on INSERT.
    assert bdv._to_rfc3339("2026-06-25T19:14:04.870892Z") == "2026-06-25T19:14:04.870892Z"


def test_to_rfc3339_none_stays_none():
    assert bdv._to_rfc3339(None) is None
    assert bdv._to_rfc3339("") is None


# --- build_plan -------------------------------------------------------------

@pytest.fixture
def fixture_db(tmp_path, monkeypatch):
    db_path = tmp_path / "snapshot.db"
    con = sqlite3.connect(db_path)
    con.execute("create table onsens (id integer primary key, facility_name varchar, "
                "scraped_at datetime)")
    con.executemany("insert into onsens (id, facility_name, scraped_at) values (?, ?, ?)", [
        (1, "博多湯", "2026-02-10 10:03:31.038834"),      # baseline-format, has a kyuhachiId
        (2, "テスト湯", "2026-06-25T19:14:04.870892Z"),    # promote-format, has a kyuhachiId
        (3, "無ID湯", "2026-02-10 10:03:33.809342"),       # no kyuhachiId in the id map
        (4, "無日時湯", None),                              # never scraped
    ])
    con.commit()
    con.close()
    monkeypatch.setattr(bdv, "SNAPSHOT_DB", db_path)
    monkeypatch.setattr(bdv, "IDMAP", {"1": "kid-1", "2": "kid-2"})
    return db_path


def test_build_plan_resolves_kyuhachi_id_and_normalizes_timestamp(fixture_db):
    plan = bdv.build_plan()
    assert plan == [
        (1, "kid-1", "博多湯", "2026-02-10T10:03:31.038834Z"),
        (2, "kid-2", "テスト湯", "2026-06-25T19:14:04.870892Z"),
        (3, None, "無ID湯", "2026-02-10T10:03:33.809342Z"),
        (4, None, "無日時湯", None),
    ]


def test_build_plan_orders_by_id_and_covers_every_row(fixture_db):
    plan = bdv.build_plan()
    assert [p[0] for p in plan] == [1, 2, 3, 4]


def test_build_plan_writable_excludes_rows_without_a_kyuhachi_id(fixture_db):
    plan = bdv.build_plan()
    writable = [p for p in plan if p[1] is not None]
    assert {p[0] for p in writable} == {1, 2}


# --- split_writes (the monotonic guard) --------------------------------------

def _row(oid, kid, ts):
    return (oid, kid, f"onsen-{oid}", ts)


def _live_doc(ts):
    return {"dataVerifiedAt": {"timestampValue": ts}} if ts else {}


def test_split_writes_only_moves_forward():
    rows = [
        _row(1, "kid-1", "2026-02-10T10:03:31.038834Z"),   # live is FRESHER → skip
        _row(2, "kid-2", "2026-06-25T19:14:04.870892Z"),   # live is STALER → write
        _row(3, "kid-3", "2026-02-10T10:03:33.809342Z"),   # live has none yet → write
    ]
    live = {
        "kid-1": _live_doc("2026-07-01T00:00:00Z"),        # apply.py already re-verified
        "kid-2": _live_doc("2026-02-10T10:03:31Z"),
        "kid-3": {},
    }
    to_write, current = bdv.split_writes(rows, live)
    assert [r[0] for r in to_write] == [2, 3]
    assert [r[0] for r in current] == [1]


def test_split_writes_equal_timestamp_is_current_across_precision():
    # Idempotence: an equal instant echoed back by Firestore with different
    # fractional precision must read as current, not a spurious rewrite.
    rows = [_row(1, "kid-1", "2026-06-25T19:14:04.000000Z")]
    live = {"kid-1": _live_doc("2026-06-25T19:14:04Z")}
    to_write, current = bdv.split_writes(rows, live)
    assert to_write == [] and [r[0] for r in current] == [1]


def test_split_writes_nothing_to_seed_is_never_written():
    rows = [_row(1, "kid-1", None)]                        # no scraped_at in the snapshot
    to_write, current = bdv.split_writes(rows, {"kid-1": {}})
    assert to_write == [] and [r[0] for r in current] == [1]


def test_split_writes_degrades_without_live_read():
    # live=None (unauthed dry-run): every dated row counts as a write, undated never.
    rows = [_row(1, "kid-1", "2026-02-10T10:03:31.038834Z"), _row(2, "kid-2", None)]
    to_write, current = bdv.split_writes(rows, None)
    assert [r[0] for r in to_write] == [1]
    assert [r[0] for r in current] == [2]
