#!/usr/bin/env python3
"""
publish-catalog-index: (re)build `/catalog_index/current` from the live catalog.

The index is a slim, derived projection of `/onsens` for the app repo's public
journey website, which renders seven values per onsen (`kyuhachiId`, `name`,
`nameRomaji`, `areaName`, `prefecture`, `lat`, `lng`) and used to read all 161
documents, 386 KB, to get them. Packed into one document it is 24 KB and a single
document read. Nothing about `/onsens` changes: the app reads it and uses nearly
every field. See `docs/onsen-schema.md`, and ADR-012 in the app repo for the
shape and the measurements behind it.

## Why a script as well as the automatic republish

`bump_catalog_version` republishes the index after every committed publish, from
the same live read and stamped with the same catalog version, so in the normal
loop this script is not needed and never runs.

It exists for the two cases that loop cannot cover:

  - **The first publish.** The document does not exist yet and no catalog change
    is pending, so nothing would call `bump_catalog_version`. Publishing an index
    is not a catalog change, so this script deliberately does NOT bump
    `catalog_meta/current.version`: bumping it would make every device on the app
    redownload an unchanged catalog for a document the app never reads.
  - **Rebuilding.** The index is derived and disposable. If it is ever deleted,
    corrupted, or found to disagree with the catalog, this rebuilds it from the
    live collection without touching a single onsen document.

Auth: gcloud Application Default Credentials (same as `publisher/apply.py`).
Run `gcloud auth application-default login` if 401. A dry-run reads live to
report the exact document it would write, and writes nothing.

Usage:
  python publisher/publish_catalog_index.py            # dry-run (reads only)
  python publisher/publish_catalog_index.py --commit    # write the document
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "publisher"))

from firestore_rest import (  # noqa: E402
    CATALOG_INDEX_SCHEMA_VERSION,
    PROJECT,
    catalog_index_fields,
    fetch_collection,
    field_at,
    get_fields,
    patch,
    token,
)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Rebuild /catalog_index/current from the live onsen catalog.")
    ap.add_argument("--show", action="store_true",
                    help="print the first few packed entries")
    ap.add_argument("--commit", action="store_true", help="execute the write")
    args = ap.parse_args()

    tok = token()
    meta = get_fields("catalog_meta/current", tok)
    if meta is None:
        print("catalog_meta/current does not exist; there is no catalog version to "
              "mirror. Publish the catalog first.")
        raise SystemExit(1)
    version = int(meta.get("version", {}).get("integerValue", 0))

    live = fetch_collection("onsens", tok)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    fields = catalog_index_fields(version, now, live)
    packed = fields["entries"]["stringValue"]
    entries = json.loads(packed)
    active = sum(1 for f in live.values() if field_at(f, "isActive") is True)

    existing = get_fields("catalog_index/current", tok)
    state = "absent" if existing is None else \
        f"schemaVersion={field_at(existing, 'schemaVersion')} " \
        f"version={field_at(existing, 'version')} count={field_at(existing, 'count')}"

    print(f"catalog index [{'COMMIT' if args.commit else 'DRY-RUN'}]   "
          f"project={PROJECT}")
    print(f"  live catalog     : {len(live)} onsens ({active} active, "
          f"{len(live) - active} retired - all of them are indexed)")
    print(f"  catalog version  : {version} (mirrored, not bumped)")
    print(f"  schemaVersion    : {CATALOG_INDEX_SCHEMA_VERSION}")
    print(f"  entries          : {len(entries)}")
    print(f"  packed size      : {len(packed.encode())} bytes")
    print(f"  currently live   : {state}")

    # A reviewer should be able to see what the website will actually render
    # without decoding a 24 KB string by hand.
    for row in entries[:5] if not args.show else entries:
        print(f"    {row[0]}  {row[1]}  ({row[3]}, {row[4]})  {row[5]},{row[6]}")

    if not args.commit:
        print("\nDry-run only, nothing written. Re-run with --commit to publish.")
        return

    patch("catalog_index/current", fields, list(fields), tok)
    print(f"\nWrote catalog_index/current: {len(entries)} entries, "
          f"{len(packed.encode()) // 1024} KB packed. "
          f"catalog_meta/current.version left at {version}.")


if __name__ == "__main__":
    main()
