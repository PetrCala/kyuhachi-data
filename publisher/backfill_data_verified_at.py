#!/usr/bin/env python3
"""
backfill-data-verified-at — one-time seed of the per-onsen `dataVerifiedAt`
timestamp onto every onsen doc, so the app can show a freshness cue ("data last
verified 2026-06") and manage expectations as fees/hours drift between
catalog-sync runs.

Source of truth: `data/snapshot.db`'s per-row `scraped_at` (offline — no
scraping), the best per-onsen signal available without re-fetching all 161
detail pages just to stamp a date. The ONGOING path is `publisher/apply.py`'s
`update`/`add` actions, which re-fetch the live page before writing and reuse
that write's own `now` — a genuine live verification instant, not a proxy.

KNOWN LIMITATION: `scraped_at` is only refreshed by `catalog-sync promote` when
a row is INSERTed (a brand-new onsen); the UPDATE path does not currently touch
it (see `.claude/skills/catalog-sync/catalog_sync.py::promote_into_db`). So for
most pre-existing onsens, `scraped_at` reflects the *original* baseline scrape,
not the most recent re-verification — this backfill inherits that imprecision.
Two datetime formats coexist in `scraped_at` (the original scaffold import wrote
naive "YYYY-MM-DD HH:MM:SS.ffffff"; `catalog_sync.py`'s `_now()` writes proper
"YYYY-MM-DDTHH:MM:SS.ffffffZ") — both are UTC and normalized here.

Like the other backfills, this is no-op aware — but with a MONOTONIC guard
instead of plain equality: a doc is only written if the seed would move its live
`dataVerifiedAt` *forward*. Once `apply.py` stamps a fresher live-verified value
on a real update, re-running this backfill skips that doc rather than regressing
it to the (staler) snapshot timestamp — safe to re-run, and the version is
bumped only when at least one doc is actually written.

Auth: gcloud Application Default Credentials (same as `publisher/apply.py`).
Run `gcloud auth application-default login` if 401. A dry-run reads live to
report how many docs would change vs. are already current; with no auth it
degrades to the offline plan (every dated doc counted as a change).

Usage:
  python publisher/backfill_data_verified_at.py            # dry-run (default): print plan, write nothing
  python publisher/backfill_data_verified_at.py --show     # also list every onsen + its resolved timestamp
  python publisher/backfill_data_verified_at.py --commit   # execute the merge writes + version bump
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from firestore_rest import (  # noqa: E402
    PROJECT, bump_catalog_version, field_at, live_onsens, patch,
)

SNAPSHOT_DB = REPO / "data" / "snapshot.db"
IDMAP = json.loads((REPO / "data/onsen-id-map.json").read_text())


# --- backfill -----------------------------------------------------------------

def _to_rfc3339(scraped_at: str | None) -> str | None:
    """Normalize a snapshot.db `scraped_at` value to a Firestore-ready RFC3339
    UTC timestamp ("...ffffffZ"). Both coexisting formats (naive space-separated,
    and the proper T...Z form `catalog_sync._now()` writes) are UTC already."""
    if not scraped_at:
        return None
    s = scraped_at.replace(" ", "T")
    if not s.endswith("Z"):
        s += "Z"
    dt = datetime.fromisoformat(s).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _parse_ts(s: str | None) -> datetime | None:
    """RFC3339 → aware UTC datetime (None-safe). Firestore may echo a timestamp
    back with different fractional precision than we sent, so the monotonic
    guard compares parsed datetimes, never text."""
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def build_plan():
    """[(id, kid, name, dataVerifiedAt_rfc3339|None)] for every onsen, kyuhachiId resolved."""
    con = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select id, facility_name, scraped_at from onsens order by id"
        ).fetchall()
    finally:
        con.close()
    return [(oid, IDMAP.get(str(oid)), name, _to_rfc3339(scraped_at))
            for oid, name, scraped_at in rows]


def split_writes(writable, live):
    """Partition writable rows into (to_write, current) with a MONOTONIC guard:
    a row is written only if it would move the live doc's dataVerifiedAt
    *forward*. The live catalog may already carry a fresher verification instant
    (apply.py stamps one on every update/add) — a seed must never regress it.
    Rows without a scraped_at have nothing to seed and are never written.
    `live` is {kid: fields} from firestore_rest; None (live unread, degraded
    dry-run) → every dated row counted as a write."""
    to_write, current = [], []
    for row in writable:
        target = _parse_ts(row[3])
        if target is None:
            current.append(row)
            continue
        if live is not None:
            cur = _parse_ts(field_at(live.get(row[1], {}), "dataVerifiedAt"))
            if cur is not None and cur >= target:
                current.append(row)
                continue
        to_write.append(row)
    return to_write, current


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill dataVerifiedAt onto the catalog (one-time seed).")
    ap.add_argument("--show", action="store_true", help="list every onsen and its resolved timestamp")
    ap.add_argument("--commit", action="store_true", help="execute the merge writes")
    args = ap.parse_args()

    plan = build_plan()
    no_ts = [p for p in plan if p[3] is None]
    missing = [oid for oid, kid, *_ in plan if kid is None]
    writable = [p for p in plan if p[1] is not None]
    stamps = sorted(p[3] for p in plan if p[3])

    print(f"dataVerifiedAt backfill — {'COMMIT' if args.commit else 'DRY-RUN'}   "
          f"project={PROJECT}   onsens={len(plan)}")
    if stamps:
        print(f"scraped_at range: {stamps[0]}  →  {stamps[-1]}   "
              f"(oldest values are the original baseline scrape, not a recent "
              "re-verification — see the script docstring)")
    if missing:
        print(f"!! {len(missing)} onsens have no kyuhachiId in onsen-id-map.json: {missing}")
    if no_ts:
        print(f"!! {len(no_ts)} onsens have no scraped_at in snapshot.db (nothing to "
              f"seed — skipped): {[oid for oid, *_ in no_ts]}")

    print("\n-- sample timestamps (first 12) --")
    for oid, _kid, name, ts in plan[:12]:
        print(f"  id={oid:<4} {(name or ''):<28} → {ts}")

    if args.show:
        print(f"\n-- all {len(plan)} timestamps --")
        for oid, _kid, name, ts in plan:
            print(f"  id={oid:<4} {(name or ''):<32} → {ts}")

    # Read the current dataVerifiedAt once; skip docs the live catalog already
    # verifies at least as recently (the monotonic guard — never move backward).
    tok, live = live_onsens(args.commit)
    to_write, current = split_writes(writable, live)
    unknown = " (live unread — counted as changes)" if live is None else ""
    print(f"\nwould move forward: {len(to_write)}   already as fresh or fresher: "
          f"{len(current)}{unknown}")

    if not args.commit:
        print(f"\nDry-run only — nothing written. Would PATCH dataVerifiedAt on {len(to_write)} "
              f"onsens" + (" and bump catalog_meta/current.version" if to_write else
              " (none — version would NOT be bumped)") + ". Re-run with --commit.")
        return

    if not to_write:
        print("\nAll docs already current — nothing written, version not bumped.")
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"\n-- writing dataVerifiedAt on {len(to_write)} onsens --")
    for oid, kid, _name, ts in to_write:
        patch(f"onsens/{kid}",
              {"dataVerifiedAt": {"timestampValue": ts},
               "updatedAt": {"timestampValue": now}},
              ["dataVerifiedAt", "updatedAt"], tok)
    print(f"    wrote {len(to_write)}.")
    bump_catalog_version(now, tok)


if __name__ == "__main__":
    main()
