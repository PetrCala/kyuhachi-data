"""Tests for the catalog-sync driver (detect staging, baseline promotion, id mint).

Fully offline — no network, no auth, no writes to the real snapshot.db / id map.
`promote_into_db` is exercised against an in-memory SQLite mirror of the onsens
schema; `write_idmap` is redirected at a tmp path. The skill lives in a non-package
dir, so we add it to sys.path (same trick as test_publish_schedule)."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / ".claude/skills/catalog-sync"))

import catalog_sync as cs  # noqa: E402

# Minimal-but-faithful mirror of data/snapshot.db's onsens table.
_SCHEMA = (
    "create table onsens (id integer primary key, onsen_area_name varchar, "
    "facility_name varchar, latitude float, longitude float, "
    + ", ".join(f"{f} varchar" for f in cs.DETAIL_FIELDS)
    + ", detail_page_url varchar, raw_html varchar, scraped_at datetime)"
)


def _db(rows=()):
    con = sqlite3.connect(":memory:")
    con.execute(_SCHEMA)
    for oid, fields in rows:
        cols = ["id", *fields]
        con.execute(f"insert into onsens ({','.join(cols)}) values "
                    f"({','.join('?' * len(cols))})", [oid, *fields.values()])
    con.commit()
    return con


# --- build_staging ------------------------------------------------------------

def test_build_staging_routes_content_removed_and_failed():
    scrape = {
        1: {f: ("X" if f == "address" else None) for f in cs.DETAIL_FIELDS},  # content
        2: {},      # soft-removed (HTTP 200, no detail)
        3: None,    # fetch failed
    }
    st = cs.build_staging(scrape)
    assert set(st["onsens"]) == {"1"}
    assert st["onsens"]["1"]["address"] == "X"
    assert st["removed"] == [2]
    assert st["fetchFailed"] == [3]


def test_build_staging_index_absence_is_authoritative():
    scrape = {5: {"address": "a", **{f: None for f in cs.DETAIL_FIELDS if f != "address"}}}
    st = cs.build_staging(scrape, index_removed={9, 5})
    # Index membership wins over content: 5 is delisted even though its page still
    # renders, so it is removed and NOT promoted; 9 (absent, never scraped) too.
    assert "5" not in st["onsens"]
    assert st["removed"] == [5, 9]


# --- promote_into_db ----------------------------------------------------------

def _fields(**kw):
    return {f: kw.get(f) for f in cs.DETAIL_FIELDS}


def test_promote_updates_changed_inserts_new_and_is_idempotent():
    con = _db([(1, _fields(address="old", phone="111"))])
    staging = {"onsens": {
        "1": _fields(address="NEW", phone="111"),    # address changed
        "7": _fields(address="brand new"),           # new onsen
    }}
    stats = cs.promote_into_db(con, staging, now="2026-06-25T00:00:00Z")
    assert (stats["updated"], stats["inserted"], stats["unchanged"]) == (1, 1, 0)
    con.commit()

    row1 = con.execute("select address, phone from onsens where id=1").fetchone()
    assert row1 == ("NEW", "111")
    row7 = con.execute("select address, detail_page_url, scraped_at from onsens where id=7").fetchone()
    assert row7[0] == "brand new"
    assert row7[1] == "https://www.88onsen.com/spot/detail/hid/7"
    assert row7[2] == "2026-06-25T00:00:00Z"

    # Re-applying the same staging is a no-op.
    again = cs.promote_into_db(con, staging)
    assert (again["updated"], again["inserted"], again["unchanged"]) == (0, 0, 2)


def test_promote_prune_only_with_flag():
    con = _db([(1, _fields(address="a")), (2, _fields(address="b"))])
    staging = {"onsens": {"1": _fields(address="a")}, "removed": [2]}

    s = cs.promote_into_db(con, staging, prune=False)
    assert s["pruned"] == 0 and s["removedSeen"] == 1
    assert con.execute("select count(*) from onsens where id=2").fetchone()[0] == 1

    s = cs.promote_into_db(con, staging, prune=True)
    assert s["pruned"] == 1
    assert con.execute("select count(*) from onsens where id=2").fetchone()[0] == 0


# --- map seed (name + coordinates the detail page lacks) ----------------------

_MAP_HTML = (
    "<html><script>\nvar marker = [];\n"
    'var markerData = ['
    '{"id":"1","onsenti":"二日市温泉","shisetsu":"博多湯","address":"筑紫野市湯町1-14-5",'
    '"lat":33.4914372,"lng":130.5149407},'
    '{"id":"253","onsenti":"新温泉","shisetsu":"新しい湯","address":"どこか","lat":31.5,"lng":130.2}'
    '];\nfunction init(){}\n</script></html>'
)


def test_parse_map_seed():
    from onsen_scraper import parse_map_seed
    seed = parse_map_seed(_MAP_HTML)
    assert set(seed) == {1, 253}
    assert seed[1] == {"name": "博多湯", "areaName": "二日市温泉",
                       "address": "筑紫野市湯町1-14-5", "lat": 33.4914372, "lng": 130.5149407}
    assert seed[253]["name"] == "新しい湯" and seed[253]["lat"] == 31.5


def test_parse_map_seed_missing_array_raises():
    from onsen_scraper import parse_map_seed
    with pytest.raises(ValueError):
        parse_map_seed("<html>no markerData here</html>")


def test_promote_fills_seed_name_and_coords():
    con = _db([(1, _fields(address="a"))])               # existing row, seed cols NULL
    staging = {"onsens": {"1": _fields(address="a"), "253": _fields(address="new")},
               "seed": {"1": {"name": "博多湯", "areaName": "二日市温泉",
                              "address": "a", "lat": 33.49, "lng": 130.51},
                        "253": {"name": "新しい湯", "areaName": "新温泉",
                                "address": "x", "lat": 31.5, "lng": 130.2}}}
    stats = cs.promote_into_db(con, staging)
    con.commit()
    # existing onsen gains name/area/coords even though its detail didn't change
    assert con.execute("select facility_name, onsen_area_name, latitude, longitude "
                       "from onsens where id=1").fetchone() == ("博多湯", "二日市温泉", 33.49, 130.51)
    # a brand-new onsen lands COMPLETE (detail + seed), not detail-only
    assert con.execute("select facility_name, latitude, address from onsens where id=253"
                       ).fetchone() == ("新しい湯", 31.5, "new")
    assert (stats["updated"], stats["inserted"], stats["seeded"]) == (1, 1, 2)


def test_promote_syncs_coord_drift():
    con = _db([(1, {"address": "a", "latitude": 33.0, "longitude": 130.0})])
    staging = {"onsens": {"1": _fields(address="a")},   # detail unchanged
               "seed": {"1": {"name": None, "areaName": None,
                              "address": "a", "lat": 33.49, "lng": 130.51}}}
    stats = cs.promote_into_db(con, staging)
    con.commit()
    assert stats["updated"] == 1                          # coords drifted → update
    assert con.execute("select latitude, longitude from onsens where id=1"
                       ).fetchone() == (33.49, 130.51)


# --- mint_ids + write_idmap ---------------------------------------------------

def test_mint_ids_only_assigns_missing():
    idmap = {"1": "existing-uuid"}
    seq = iter(["uuid-a", "uuid-b"])
    minted = cs.mint_ids(idmap, [1, 7, 9], rng=lambda: next(seq))
    assert minted == {"7": "uuid-a", "9": "uuid-b"}  # 1 already mapped, skipped
    assert idmap == {"1": "existing-uuid"}           # pure — input untouched


def test_write_idmap_roundtrips_byte_stable(tmp_path, monkeypatch):
    target = tmp_path / "onsen-id-map.json"
    monkeypatch.setattr(cs, "IDMAP_PATH", target)
    cs.write_idmap({"7": "b", "1": "a"})             # unsorted input
    text = target.read_text(encoding="utf-8")
    assert text == '{\n  "1": "a",\n  "7": "b"\n}\n'  # numeric order, 2-space, trailing nl
    assert json.loads(text) == {"1": "a", "7": "b"}


# --- drift guard --------------------------------------------------------------

def test_detail_fields_match_catalog_diff():
    sys.path.insert(0, str(REPO / ".claude/skills/catalog-diff"))
    import catalog_diff as cd
    assert list(cs.DETAIL_FIELDS) == cd.FIELDS
