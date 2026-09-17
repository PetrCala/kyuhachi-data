#!/usr/bin/env python3
"""
backfill-asof-stamp: republish source text whose ONLY drift is the "as-of" date
stamp, e.g. `（2025.3現在）` → `【2026年 4月現在】`.

## Why this exists at all

The catalog's diff normalizer (`catalog_diff.norm`) deliberately strips as-of date
stamps before comparing. That suppression is load-bearing: 88onsen.com periodically
refreshes the stamp site-wide without touching a single fee, and without it every
such refresh reports ~150 phantom "modified" onsens (it did exactly that on the
first live run, 2026-06-23). The cost of the suppression is that a stamp refresh
can NEVER propagate through the normal detect → apply.py loop, because apply.py
diffs on the same normalized form and concludes "no material changes".

So the stamps drift, silently and permanently. As of 2026-09-17, 101 `admissionFee`
texts and 1 `businessHours.raw` carried a stamp ~18 months older than the source.
The fees themselves were correct to the yen; only the parenthetical caption was
stale. The app renders that caption verbatim (`OnsenFee` on the onsen detail screen
and in the preview sheet), so users read a 2025 date on a fee the source now stamps
2026.

This script is the deliberate, occasional counterpart to that suppression: the one
place that publishes a stamp-only change, run by hand when the captions have drifted
far enough to be worth a no-op-in-substance write.

## What it will and will not write

Source of truth is `data/snapshot.db`, not a fresh scrape. The baseline is advanced
by `catalog-sync promote` only after a successful publish, so it is a verified copy
of the source text, and running `catalog-sync detect` immediately before this script
confirms it (`suppressedDateStampOnly: 0` vs the snapshot baseline means baseline and
source agree on the stamps too).

For each field it compares the baseline against the live doc twice:

  - normalized WITH date-stripping differs  → MATERIAL change. Refused, not written,
    and reported. That belongs to `apply.py` via the changelog, which adjudicates
    identity and re-derives `adultFee`. This script must never be the thing that
    quietly publishes a real fee change.
  - normalized WITHOUT date-stripping differs → stamp-only. Written.
  - otherwise → already current. Skipped.

`businessHours.raw` is written as a nested map field under the `businessHours.raw`
updateMask, so the curated `schedule` / `exceptions` / `confidence` that
`backfill_schedule.py` owns are preserved untouched.

`adultFee` is NOT re-derived: a stamp-only change cannot move the parsed fee by
construction, and `backfill_fees.py` remains the owner of that field.

`dataVerifiedAt` is NOT touched either, though a full detect arguably re-verifies
every doc. That is a broader decision about all 160 onsens, not these 102 fields;
`backfill_data_verified_at.py` owns it.

Idempotent and additive, same contract as the other one-field backfills: named
fields via updateMask, never a whole-doc overwrite, never a delete. Bumps
`/catalog_meta/current.version` only if something was actually written.

Auth: gcloud Application Default Credentials. A dry-run degrades to an offline plan
if the live read fails; `--commit` propagates the error.

Usage:
  python publisher/backfill_asof_stamp.py            # dry-run: print plan, write nothing
  python publisher/backfill_asof_stamp.py --show     # also print every before/after pair
  python publisher/backfill_asof_stamp.py --commit   # execute the merge writes + version bump
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / ".claude" / "skills" / "catalog-diff"))
import catalog_diff as cd  # noqa: E402
from firestore_rest import (  # noqa: E402
    PROJECT, bump_catalog_version, field_at, live_onsens, patch, sval,
)

IDMAP = json.loads((REPO / "data/onsen-id-map.json").read_text())

# parser field -> published path. Only the two source-authored free-text fields
# that carry an as-of stamp; the rest of CATALOG_FIELDS never has one.
STAMPED = {
    "admission_fee": "admissionFee",
    "business_hours": "businessHours.raw",
}


def classify(base_val, live_val, field: str) -> str:
    """'material' | 'stamp' | 'current' for one field's baseline-vs-live pair."""
    if cd.norm(field, base_val) != cd.norm(field, live_val):
        return "material"
    if cd.norm(field, base_val, strip_dates=False) != cd.norm(field, live_val, strip_dates=False):
        return "stamp"
    return "current"


def build_plan(live):
    """(writes, material, current) over every baseline onsen x STAMPED field.

    `live` is {kid: fields}; None (live unread on a dry-run) means we cannot
    classify, so nothing is planned as a write — an offline run reports only what
    it can honestly know rather than guessing every row is a change."""
    writes, material, current = [], [], []
    if live is None:
        return writes, material, current
    for hid, base in sorted(cd.load_snapshot().items()):
        kid = IDMAP.get(str(hid))
        if kid is None or kid not in live:
            continue
        for field, path in STAMPED.items():
            base_val, live_val = base.get(field), field_at(live[kid], path)
            row = (hid, kid, field, path, live_val, base_val)
            {"material": material, "stamp": writes, "current": current}[
                classify(base_val, live_val, field)].append(row)
    return writes, material, current


def encode(path: str, value):
    """(fields, mask) for one published path — nested paths become a mapValue so
    sibling keys under the same map (businessHours.schedule et al) survive."""
    if "." not in path:
        return {path: sval(value)}, [path]
    top, sub = path.split(".")
    return {top: {"mapValue": {"fields": {sub: sval(value)}}}}, [path]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Republish source text whose only drift is the as-of date stamp.")
    ap.add_argument("--show", action="store_true", help="print every before/after pair")
    ap.add_argument("--commit", action="store_true", help="execute the merge writes")
    args = ap.parse_args()

    print(f"as-of stamp backfill [{'COMMIT' if args.commit else 'DRY-RUN'}]   "
          f"project={PROJECT}")
    tok, live = live_onsens(args.commit)
    if live is None:
        print("\nlive catalog unread — cannot classify stamp vs material drift. "
              "Authenticate (gcloud auth application-default login) and re-run.")
        return

    writes, material, current = build_plan(live)
    print(f"reading baseline + live…  live docs={len(live)}")

    if material:
        print(f"\n!! {len(material)} MATERIAL differences — NOT written by this script.")
        print("   These are real content changes; run the catalog-sync detect → apply.py")
        print("   loop so they are adjudicated and adultFee is re-derived.")
        for hid, _kid, field, *_ in material[:20]:
            print(f"     hid {hid:<5} {field}")
        if len(material) > 20:
            print(f"     … and {len(material) - 20} more")

    by_field = {}
    for _hid, _kid, field, *_ in writes:
        by_field[field] = by_field.get(field, 0) + 1
    print(f"\nwould change: {len(writes)}   already current: {len(current)}   "
          f"refused (material): {len(material)}")
    if by_field:
        print("  by field: " + ", ".join(f"{f} {n}" for f, n in sorted(by_field.items())))

    sample = writes if args.show else writes[:3]
    if sample:
        print(f"\n-- {'all' if args.show else 'sample'} before/after ({len(sample)}) --")
        for hid, _kid, field, _path, live_val, base_val in sample:
            print(f"  hid {hid} {field}")
            print(f"    live → {live_val!r}")
            print(f"    new  → {base_val!r}")

    if not args.commit:
        print(f"\nDry-run only, nothing written. Would PATCH {len(writes)} fields"
              + (" and bump catalog_meta/current.version" if writes
                 else " (none, so version would NOT be bumped)")
              + ". Re-run with --commit.")
        return

    if not writes:
        print("\nAll docs already current. Nothing written, version not bumped.")
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"\n-- writing {len(writes)} stamp-only fields --")
    for hid, kid, _field, path, _live_val, base_val in writes:
        fields, mask = encode(path, base_val)
        fields["updatedAt"] = {"timestampValue": now}
        patch(f"onsens/{kid}", fields, mask + ["updatedAt"], tok)
    print(f"    wrote {len(writes)}.")
    bump_catalog_version(now, tok)


if __name__ == "__main__":
    main()
