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

Auth: gcloud Application Default Credentials (same as `publisher/apply.py`).
Run `gcloud auth application-default login` if 401. Dry-run needs no auth — the
plan is computed entirely from the local snapshot.

Usage:
  python publisher/backfill_fees.py            # dry-run (default): print plan, write nothing
  python publisher/backfill_fees.py --commit   # execute the merge writes + version bump
"""
import argparse
import json
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from onsen_scraper.fees import fee_for  # noqa: E402

PROJECT = "kyuhachi-fddcc"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
SNAPSHOT_DB = REPO / "data" / "snapshot.db"
IDMAP = json.loads((REPO / "data/onsen-id-map.json").read_text())

# Anything other than a clean 大人 match gets surfaced for human review before commit.
REVIEW_METHODS = {"jhs+", "free", "fallback", "corrected", "none"}


# --- Firestore REST (mirrors apply.py; DRY into publisher/firestore_rest.py later) ---

def token() -> str:
    return subprocess.check_output(
        ["gcloud", "auth", "application-default", "print-access-token"], text=True
    ).strip()


def ival(n):
    return {"nullValue": None} if n is None else {"integerValue": str(n)}


def _open(req, timeout=30, retries=3):
    """urlopen with a timeout, retrying transient network errors / 429 / 5xx.
    Without this a single hung connection stalls the 148-doc loop forever."""
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if attempt < retries and e.code in (429, 500, 502, 503):
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries:
                continue
            raise


def get_fields(path: str, tok: str):
    """Return the doc's `fields` dict, or None on 404."""
    req = urllib.request.Request(f"{BASE}/{path}", headers={"Authorization": f"Bearer {tok}"})
    try:
        with _open(req) as r:
            return json.load(r).get("fields", {})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def patch(path: str, fields: dict, mask: list, tok: str) -> int:
    qs = "&".join(f"updateMask.fieldPaths={m}" for m in mask)
    req = urllib.request.Request(
        f"{BASE}/{path}?{qs}", data=json.dumps({"fields": fields}).encode(), method="PATCH",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    try:
        with _open(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {e.read().decode()[:300]}")
        raise


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


def bump_catalog_version(now: str, tok: str):
    fields = get_fields("catalog_meta/current", tok)
    if fields is None:
        print("catalog_meta/current does not exist yet — skipping version bump "
              "(the first full publish will create it).")
        return
    cur = int(fields.get("version", {}).get("integerValue", 0))
    patch("catalog_meta/current",
          {"version": {"integerValue": str(cur + 1)}, "publishedAt": {"timestampValue": now}},
          ["version", "publishedAt"], tok)
    print(f"catalog_meta/current: version {cur} → {cur + 1}  (bumped)")


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
    if not args.commit:
        print(f"\nDry-run only — nothing written. Would PATCH adultFee on {len(writable)} "
              f"onsens and bump catalog_meta/current.version. Re-run with --commit.")
        return

    tok = token()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"\n-- writing adultFee on {len(writable)} onsens --")
    for oid, kid, _name, fee, _method in writable:
        patch(f"onsens/{kid}",
              {"adultFee": ival(fee), "updatedAt": {"timestampValue": now}},
              ["adultFee", "updatedAt"], tok)
    print(f"    wrote {len(writable)}.")
    bump_catalog_version(now, tok)


if __name__ == "__main__":
    main()
