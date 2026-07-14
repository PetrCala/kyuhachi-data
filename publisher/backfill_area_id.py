#!/usr/bin/env python3
"""
backfill-area-id: publish the region join field `areaId` onto every onsen doc.

Resolves each onsen's coarse tourism region from its `onsen_area_name` +
`prefecture` in the snapshot DB (offline, no scraping) via the shared region model
(`onsen_scraper.regions.region_for` and the `data/area-id-map.json` ledger) and
MERGE-PATCHes the region's stable `areaId` onto `/onsens/{kyuhachiId}` as `areaId`,
then bumps `/catalog_meta/current.version` so the app refetches. Additive and
idempotent: writes one named field via updateMask, never overwrites other fields,
never deletes, never touches `/users`. Same contract as `apply.py` /
`backfill_fees.py`.

`areaId` is the join from an onsen to its published `/area_guides/{areaId}` doc
(the app's "area guides" feature). It is a stable id this repo owns and assigns,
exactly like `kyuhachiId`; upstream 88onsen ids are never exposed. An onsen whose
(area, prefecture) the region model cannot place yet gets `areaId: null` (the app
shows no guide for it) and is surfaced here for the maintainer to assign in
`onsen_scraper.regions.AREA_REGION`.

Why a dedicated backfill (not only the surgical `apply.py` update path): region
membership derives from `areaName`, which comes from the /map seed rather than the
detail page, so `apply.py`'s detail-diff never sees it change. This script is both
the initial fill AND the ongoing path: it is idempotent, so re-running it after a
new onsen lands (or after a region reassignment in the taxonomy) republishes only
what changed. The `apply.py` `add` action calls the same `region_for()` when it
mints a new doc, so a brand-new onsen already carries its `areaId`.

No-op aware: before writing, the current `areaId` of every doc is read once (a
paginated /onsens list), so docs already carrying the target id are skipped and
`catalog_meta/current.version` is bumped only when at least one doc is written.

Auth: gcloud Application Default Credentials (same as `publisher/apply.py`).
Run `gcloud auth application-default login` if 401. A dry-run reads live to report
how many docs would change vs. are already current; with no auth it degrades to the
offline plan (every writable doc counted as a change) instead of erroring.

Usage:
  python publisher/backfill_area_id.py            # dry-run (default): print plan, write nothing
  python publisher/backfill_area_id.py --show      # also list every onsen and its region
  python publisher/backfill_area_id.py --commit    # execute the merge writes + version bump
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from onsen_scraper.regions import REGIONS, load_area_id_map, region_for  # noqa: E402
from firestore_rest import (  # noqa: E402
    PROJECT, bump_catalog_version, field_at, live_onsens, patch, sval,
)

SNAPSHOT_DB = REPO / "data" / "snapshot.db"
IDMAP = json.loads((REPO / "data/onsen-id-map.json").read_text())


# --- backfill -----------------------------------------------------------------

def build_plan():
    """[(id, kid, area, pref, region_key, area_id)] for every onsen.

    `region_key` is None when the region model cannot place the onsen; `area_id`
    is None when the key is unplaced OR the key has no id in the ledger (which
    should not happen once `regions.py --build` has minted every REGIONS key).
    """
    area_ids = load_area_id_map()
    con = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select id, onsen_area_name, prefecture from onsens order by id"
        ).fetchall()
    finally:
        con.close()
    plan = []
    for oid, area, pref in rows:
        key = region_for(area, pref)
        plan.append((oid, IDMAP.get(str(oid)), area, pref, key,
                     area_ids.get(key) if key else None))
    return plan


def split_writes(writable, live):
    """Partition writable rows into (to_write, current) by whether `areaId` would
    actually change the live doc. `live` is {kid: fields}; None (live unread) means
    treat every row as a write. Both target and decoded live value are str|None, so
    a direct compare mirrors sval's falsy->null encoding (a null areaId already
    published reads as 'current', not a spurious rewrite)."""
    if live is None:
        return list(writable), []
    to_write, current = [], []
    for row in writable:
        target = row[5] or None
        cur = field_at(live.get(row[1], {}), "areaId")
        (current if cur == target else to_write).append(row)
    return to_write, current


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill the region join field areaId onto the catalog.")
    ap.add_argument("--show", action="store_true", help="list every onsen and its resolved region")
    ap.add_argument("--commit", action="store_true", help="execute the merge writes")
    args = ap.parse_args()

    plan = build_plan()
    unplaced = [p for p in plan if p[4] is None]
    no_id = [p for p in plan if p[4] is not None and p[5] is None]
    missing = [oid for oid, kid, *_ in plan if kid is None]
    writable = [p for p in plan if p[1] is not None]
    by_region = Counter(p[4] for p in plan if p[4] is not None)

    print(f"areaId backfill: {'COMMIT' if args.commit else 'DRY-RUN'}   "
          f"project={PROJECT}   onsens={len(plan)}   regions={len(REGIONS)}")
    print(f"placed: {len(plan) - len(unplaced)}   unplaced (areaId:null): {len(unplaced)}")
    if missing:
        print(f"!! {len(missing)} onsens have no kyuhachiId in onsen-id-map.json: {missing}")
    if no_id:
        print(f"!! {len(no_id)} onsens map to a region with no areaId in area-id-map.json "
              f"(run `python -m onsen_scraper.regions --build`): "
              f"{sorted({p[4] for p in no_id})}")
    if unplaced:
        print(f"!! unplaced onsens (add their area name to regions.AREA_REGION): "
              f"{[(oid, pref, area) for oid, _kid, area, pref, *_ in unplaced]}")

    print("\n-- onsens per region --")
    for key in REGIONS:
        print(f"  {key:<26} {by_region.get(key, 0):>2}  ({REGIONS[key]['label']})")

    if args.show:
        print(f"\n-- all {len(plan)} onsens --")
        for oid, _kid, area, _pref, key, aid in plan:
            print(f"  id={oid:<4} {(area or ''):<22} -> {key or '(unplaced)'}  {aid or ''}")

    # Read current areaId once and skip docs already carrying the target id.
    tok, live = live_onsens(args.commit)
    to_write, current = split_writes(writable, live)
    unknown = " (live unread, counted as changes)" if live is None else ""
    print(f"\nwould change: {len(to_write)}   already current: {len(current)}{unknown}")

    if not args.commit:
        print(f"\nDry-run only, nothing written. Would PATCH areaId on {len(to_write)} "
              f"onsens" + (" and bump catalog_meta/current.version" if to_write else
              " (none, version would NOT be bumped)") + ". Re-run with --commit.")
        return

    if not to_write:
        print("\nAll docs already current, nothing written, version not bumped.")
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"\n-- writing areaId on {len(to_write)} changed onsens --")
    for oid, kid, _area, _pref, _key, aid in to_write:
        patch(f"onsens/{kid}",
              {"areaId": sval(aid), "updatedAt": {"timestampValue": now}},
              ["areaId", "updatedAt"], tok)
    print(f"    wrote {len(to_write)}.")
    bump_catalog_version(now, tok)


if __name__ == "__main__":
    main()
