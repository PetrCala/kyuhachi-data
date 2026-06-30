#!/usr/bin/env python3
"""
backfill-name-romaji — publish the generated Hepburn romaji `nameRomaji` onto every
onsen doc.

Generates the romaji reading of each onsen's `name` from the kanji
`facility_name` in the snapshot DB (offline — no scraping) via the shared
analyzer (`onsen_scraper.readings.name_romaji`, pykakasi Hepburn capitalised as a
proper noun) and MERGE-PATCHes it onto `/onsens/{kyuhachiId}` as `nameRomaji`,
then bumps `/catalog_meta/current.version` so the app refetches. Additive and
idempotent — same contract as `apply.py` / `backfill_name_kana.py`: writes one
named field via updateMask, never overwrites other fields, never deletes.

`nameRomaji` is a Latin-script pronunciation aid the app shows beneath the kanji
name for non-Japanese users so they can read and search an onsen — never a
translation, and (unlike `nameKana`) display-only, not a sort key. It is a
*generated* field; readings do not exist upstream (see app PR
PetrCala/kyuhachi#183). Mirrors `backfill_name_kana.py` exactly — the kana and
romaji readings come from the same pykakasi conversion but are published by
separate one-field backfills, matching this repo's one-script-per-field
convention. Run both after a name lands or is corrected.

Why a dedicated backfill (not the surgical `apply.py` update path): `name` is not
a detail-page field — it comes from the map seed, not the scrape — so `apply.py`
never sees a name change to react to. This script is therefore both the initial
fill AND the ongoing path: it is idempotent, so re-running it after a new onsen's
name lands (or any name correction) republishes only what changed. A future
`apply.py` `add` action should call `name_romaji()` when it mints the new doc.

Auth: gcloud Application Default Credentials (same as `publisher/apply.py`).
Run `gcloud auth application-default login` if 401. Dry-run needs no auth — the
plan is computed entirely from the local snapshot.

Usage:
  python publisher/backfill_name_romaji.py            # dry-run (default): print plan, write nothing
  python publisher/backfill_name_romaji.py --show     # also list every onsen + its romaji
  python publisher/backfill_name_romaji.py --commit   # execute the merge writes + version bump
"""
import argparse
import json
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from onsen_scraper.readings import name_romaji  # noqa: E402

PROJECT = "kyuhachi-fddcc"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
SNAPSHOT_DB = REPO / "data" / "snapshot.db"
IDMAP = json.loads((REPO / "data/onsen-id-map.json").read_text())


# --- Firestore REST (mirrors apply.py / backfill_name_kana.py; DRY into
#     publisher/firestore_rest.py later — see roadmap item D) -------------------

def token() -> str:
    return subprocess.check_output(
        ["gcloud", "auth", "application-default", "print-access-token"], text=True
    ).strip()


def sval(v):
    return {"stringValue": v} if v else {"nullValue": None}


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
    """[(id, kid, name, romaji|None)] for every onsen, kyuhachiId + reading resolved."""
    con = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select id, facility_name from onsens order by id"
        ).fetchall()
    finally:
        con.close()
    return [(oid, IDMAP.get(str(oid)), name, name_romaji(name)) for oid, name in rows]


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
    ap = argparse.ArgumentParser(description="Backfill generated nameRomaji onto the catalog.")
    ap.add_argument("--show", action="store_true", help="list every onsen and its generated romaji")
    ap.add_argument("--commit", action="store_true", help="execute the merge writes")
    args = ap.parse_args()

    plan = build_plan()
    no_romaji = [p for p in plan if p[3] is None]
    missing = [oid for oid, kid, *_ in plan if kid is None]
    writable = [p for p in plan if p[1] is not None]

    print(f"nameRomaji backfill — {'COMMIT' if args.commit else 'DRY-RUN'}   "
          f"project={PROJECT}   onsens={len(plan)}")
    print(f"readings generated: {len(plan) - len(no_romaji)}   null (no reading): {len(no_romaji)}")
    if missing:
        print(f"!! {len(missing)} onsens have no kyuhachiId in onsen-id-map.json: {missing}")
    if no_romaji:
        print(f"!! null readings (will publish nameRomaji:null → app shows kanji alone): "
              f"{[oid for oid, *_ in no_romaji]}")

    # A handful of sample readings so a reviewer can spot-check quality without
    # auth or a full --show dump.
    print("\n-- sample readings (first 12) --")
    for oid, _kid, name, romaji in plan[:12]:
        print(f"  id={oid:<4} {(name or ''):<28} → {romaji}")

    if args.show:
        print(f"\n-- all {len(plan)} readings --")
        for oid, _kid, name, romaji in plan:
            print(f"  id={oid:<4} {(name or ''):<32} → {romaji}")

    if not args.commit:
        print(f"\nDry-run only — nothing written. Would PATCH nameRomaji on {len(writable)} "
              f"onsens and bump catalog_meta/current.version. Re-run with --commit.")
        return

    tok = token()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"\n-- writing nameRomaji on {len(writable)} onsens --")
    for oid, kid, _name, romaji in writable:
        patch(f"onsens/{kid}",
              {"nameRomaji": sval(romaji), "updatedAt": {"timestampValue": now}},
              ["nameRomaji", "updatedAt"], tok)
    print(f"    wrote {len(writable)}.")
    bump_catalog_version(now, tok)


if __name__ == "__main__":
    main()
