#!/usr/bin/env python3
"""
backfill-fees — one-time backfill of numeric `adultFee` onto every onsen doc.

Computes the adult walk-in fee (yen) from each onsen's free-text `admission_fee`
in the snapshot DB (offline — no scraping) and MERGE-PATCHes it onto
`/onsens/{kyuhachiId}` as `adultFee`, then bumps `/catalog_meta/current.version`
so the app refetches. Additive and idempotent: re-running writes the same values,
never overwrites other fields, never deletes — same contract as `apply.py`.

The ongoing path (recompute `adultFee` whenever `admission_fee` changes) belongs
in the surgical publisher (`publisher/apply.py`); this script is the initial fill.

No-op aware: before writing, the current `adultFee` of every doc is read once (a
paginated /onsens list), so docs already carrying the target fee are skipped and
`catalog_meta/current.version` is bumped only when at least one doc is written.

Auth: gcloud Application Default Credentials (same as `publisher/apply.py`).
Run `gcloud auth application-default login` if 401. A dry-run reads live to report
how many docs would change vs. are already current; with no auth it degrades to the
offline plan (every writable doc counted as a change) instead of erroring.

Usage:
  python publisher/backfill_fees.py            # dry-run (default): print plan, write nothing
  python publisher/backfill_fees.py --commit   # execute the merge writes + version bump
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
from onsen_scraper.fees import fee_for  # noqa: E402
from firestore_rest import (  # noqa: E402
    PROJECT, bump_catalog_version, field_at, ival, live_onsens, patch,
)

SNAPSHOT_DB = REPO / "data" / "snapshot.db"
IDMAP = json.loads((REPO / "data/onsen-id-map.json").read_text())

# Anything other than a clean 大人 match gets surfaced for human review before commit.
REVIEW_METHODS = {"jhs+", "free", "fallback", "corrected", "none"}


# --- backfill -----------------------------------------------------------------

def build_plan():
    """[(id, kid, name, fee_yen|None, method)] for every onsen, kyuhachiId resolved."""
    con = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select id, facility_name, admission_fee from onsens order by id"
        ).fetchall()
    finally:
        con.close()
    plan = []
    for oid, name, raw in rows:
        fee, method = fee_for(oid, raw)
        plan.append((oid, IDMAP.get(str(oid)), name, fee, method))
    return plan


def split_writes(writable, live):
    """Partition writable rows into (to_write, current) by whether the numeric
    `adultFee` would actually change the live doc. `live` is {kid: fields}; None
    (live unread) → treat every row as a write. Both target and decoded live value
    are int|None, so a direct compare mirrors ival's None→null encoding."""
    if live is None:
        return list(writable), []
    to_write, current = [], []
    for row in writable:
        target = row[3]  # fee_yen int|None
        cur = field_at(live.get(row[1], {}), "adultFee")
        (current if cur == target else to_write).append(row)
    return to_write, current


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill numeric adultFee onto the catalog.")
    ap.add_argument("--commit", action="store_true", help="execute the merge writes")
    args = ap.parse_args()

    plan = build_plan()
    counts = Counter(p[4] for p in plan)
    missing = [oid for oid, kid, *_ in plan if kid is None]

    print(f"adultFee backfill — {'COMMIT' if args.commit else 'DRY-RUN'}   "
          f"project={PROJECT}   onsens={len(plan)}")
    print(f"methods: {dict(counts)}")
    if missing:
        print(f"!! {len(missing)} onsens have no kyuhachiId in onsen-id-map.json: {missing}")

    review = sorted((p for p in plan if p[4] in REVIEW_METHODS), key=lambda p: p[4])
    print(f"\n-- {len(review)} non-'adult' extractions to eyeball before commit --")
    for oid, _kid, name, fee, method in review:
        fee_s = "null" if fee is None else f"¥{fee}"
        print(f"  [{method:9}] id={oid:<4} {fee_s:>7}  {name}")

    writable = [p for p in plan if p[1] is not None]

    # Read current adultFee once and skip docs already carrying the target value.
    tok, live = live_onsens(args.commit)
    to_write, current = split_writes(writable, live)
    unknown = " (live unread — counted as changes)" if live is None else ""
    print(f"\nwould change: {len(to_write)}   already current: {len(current)}{unknown}")

    if not args.commit:
        print(f"\nDry-run only — nothing written. Would PATCH adultFee on {len(to_write)} "
              f"onsens" + (" and bump catalog_meta/current.version" if to_write else
              " (none — version would NOT be bumped)") + ". Re-run with --commit.")
        return

    if not to_write:
        print("\nAll docs already current — nothing written, version not bumped.")
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"\n-- writing adultFee on {len(to_write)} changed onsens --")
    for oid, kid, _name, fee, _method in to_write:
        patch(f"onsens/{kid}",
              {"adultFee": ival(fee), "updatedAt": {"timestampValue": now}},
              ["adultFee", "updatedAt"], tok)
    print(f"    wrote {len(to_write)}.")
    bump_catalog_version(now, tok)


if __name__ == "__main__":
    main()
