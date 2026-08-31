#!/usr/bin/env python3
"""
backfill-detail-page-url: publish each onsen's 88onsen.com source page as
`detailPageUrl` onto every onsen doc.

Derives `https://www.88onsen.com/spot/detail/hid/{hid}` from the upstream hid via
the shared `onsen_scraper.get_detail_url` template (offline: no scraping, no
network) and MERGE-PATCHes it onto `/onsens/{kyuhachiId}` as `detailPageUrl`,
then bumps `/catalog_meta/current.version` so the app refetches. Additive and
idempotent, same contract as `apply.py` and the other one-field backfills: writes
one named field via updateMask, never overwrites other fields, never deletes.

## Why the app needs this

On 2026-08-31 一般社団法人 九州観光機構 granted permission to display the catalog
photos in the app (see the app repo's `docs/storage-image-exposure.md` and
PetrCala/kyuhachi#229). The request that was granted offered per-photo credit
plus a link back to the source, so the app credits every photo to its own
88onsen.com page. The hid is a locked-away upstream id that never leaves this
repo, so the app cannot build that URL itself: it has to be published.

This is a photo-credit field, not a general "more info" link. `websiteUrl` is the
facility's own site and stays what it was.

## Why a dedicated backfill (not the `apply.py` update path)

`detailPageUrl` is not a detail-page field. It is the template URL the scrape was
fetched *from*, so it never appears in a diff of scraped content and `apply.py`
never sees a change to react to. `apply.py`'s `add` action calls the same
`get_detail_url()` when it mints a new doc; this script is the initial fill for
the docs that already exist.

It is also, in practice, a one-shot: the URL is a pure function of a hid that by
this repo's locked decisions never changes. Re-running it is harmless (idempotent)
but should find nothing to do. If it ever reports writes on a doc that already had
the field, that means a hid moved, which is a bug worth chasing rather than
publishing over.

"Republishes only what changed": the current `detailPageUrl` of every doc is read
once (a paginated /onsens list) before writing, so docs already carrying the target
URL are skipped and `catalog_meta/current.version` is bumped only when at least one
doc is actually written.

Auth: gcloud Application Default Credentials (same as `publisher/apply.py`).
Run `gcloud auth application-default login` if 401. A dry-run reads live to report
how many docs would change vs. are already current; with no auth it degrades to the
offline plan (every writable doc counted as a change) instead of erroring.

Usage:
  python publisher/backfill_detail_page_url.py            # dry-run (default): print plan, write nothing
  python publisher/backfill_detail_page_url.py --show     # also list every onsen + its URL
  python publisher/backfill_detail_page_url.py --commit   # execute the merge writes + version bump
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from onsen_scraper import get_detail_url  # noqa: E402
from firestore_rest import (  # noqa: E402
    PROJECT, bump_catalog_version, field_at, live_onsens, patch, sval,
)

SNAPSHOT_DB = REPO / "data" / "snapshot.db"
IDMAP = json.loads((REPO / "data/onsen-id-map.json").read_text())


# --- backfill -----------------------------------------------------------------

def build_plan():
    """[(id, kid, name, detail_page_url)] for every onsen, kyuhachiId resolved.

    The URL comes from the hid template rather than the snapshot's stored
    `detail_page_url` column, so a row scraped before the template settled still
    publishes the canonical form."""
    con = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select id, facility_name from onsens order by id"
        ).fetchall()
    finally:
        con.close()
    return [(oid, IDMAP.get(str(oid)), name, get_detail_url(oid)) for oid, name in rows]


def split_writes(writable, live):
    """Partition writable rows into (to_write, current) by whether `detailPageUrl`
    would actually change the live doc. `live` is {kid: fields}; None (live unread)
    → treat every row as a write. Mirrors sval's falsy→null encoding so a null
    already published reads as 'current', not a spurious rewrite."""
    if live is None:
        return list(writable), []
    to_write, current = [], []
    for row in writable:
        target = row[3] or None
        cur = field_at(live.get(row[1], {}), "detailPageUrl")
        (current if cur == target else to_write).append(row)
    return to_write, current


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Backfill the 88onsen source page URL onto the catalog.")
    ap.add_argument("--show", action="store_true", help="list every onsen and its URL")
    ap.add_argument("--commit", action="store_true", help="execute the merge writes")
    args = ap.parse_args()

    plan = build_plan()
    missing = [oid for oid, kid, *_ in plan if kid is None]
    writable = [p for p in plan if p[1] is not None]

    print(f"detailPageUrl backfill [{'COMMIT' if args.commit else 'DRY-RUN'}]   "
          f"project={PROJECT}   onsens={len(plan)}")
    if missing:
        print(f"!! {len(missing)} onsens have no kyuhachiId in onsen-id-map.json: {missing}")

    # A few samples so a reviewer can eyeball the URL shape without auth or --show.
    print("\n-- sample URLs (first 5) --")
    for oid, _kid, name, url in plan[:5]:
        print(f"  id={oid:<4} {(name or ''):<28} → {url}")

    if args.show:
        print(f"\n-- all {len(plan)} URLs --")
        for oid, _kid, name, url in plan:
            print(f"  id={oid:<4} {(name or ''):<32} → {url}")

    # Read current detailPageUrl once and skip docs already carrying the target URL.
    tok, live = live_onsens(args.commit)
    to_write, current = split_writes(writable, live)
    unknown = " (live unread, counted as changes)" if live is None else ""
    print(f"\nwould change: {len(to_write)}   already current: {len(current)}{unknown}")

    if not args.commit:
        print(f"\nDry-run only, nothing written. Would PATCH detailPageUrl on "
              f"{len(to_write)} onsens" + (" and bump catalog_meta/current.version"
              if to_write else " (none, so version would NOT be bumped)") +
              ". Re-run with --commit.")
        return

    if not to_write:
        print("\nAll docs already current. Nothing written, version not bumped.")
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"\n-- writing detailPageUrl on {len(to_write)} changed onsens --")
    for oid, kid, _name, url in to_write:
        patch(f"onsens/{kid}",
              {"detailPageUrl": sval(url), "updatedAt": {"timestampValue": now}},
              ["detailPageUrl", "updatedAt"], tok)
    print(f"    wrote {len(to_write)}.")
    bump_catalog_version(now, tok)


if __name__ == "__main__":
    main()
