#!/usr/bin/env python3
"""backfill-images — one-time rehost of every onsen photo to Firebase Storage.

Each onsen's `imageUrl` currently points at the raw source photo on
www.88onsen.com — a plain Apache origin with no CDN and no Cache-Control, so the
app waits 3-5s (up to ~12s) on the first load of every photo. This script
downloads each source photo, resizes + re-encodes it to WebP, uploads it to
Firebase Storage (Google edge, long Cache-Control, a stable tokenised download
URL), computes a BlurHash, and MERGE-PATCHes the new `imageUrl` + `blurhash` onto
`/onsens/{kyuhachiId}` — then bumps `/catalog_meta/current.version` so the app
refetches. Additive and idempotent: the download token is derived from the
kyuhachiId, so the published URL is stable and re-running is a no-op. Never
overwrites other fields, never deletes — same contract as `apply.py`.

The ongoing path (rehost whenever the source photo changes) lives in the surgical
publisher (`publisher/apply.py`); this script is the initial fill.

Auth: gcloud Application Default Credentials (same as `publisher/apply.py`). Run
`gcloud auth application-default login` if 401. The bearer token authorises both
the Storage upload (GCS) and the Firestore writes.

Usage:
  python publisher/backfill_images.py                 # dry-run: offline plan, nothing fetched/written
  python publisher/backfill_images.py --probe --limit 3   # download+resize+blurhash 3 (no upload/write) to verify the pipeline
  python publisher/backfill_images.py --commit        # rehost all: upload + merge-write + version bump
  python publisher/backfill_images.py --commit --limit 10 # cautious partial run (first 10)
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
sys.path.insert(0, str(REPO / "publisher"))
import image_processor as ip  # noqa: E402

PROJECT = "kyuhachi-fddcc"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
SNAPSHOT_DB = REPO / "data" / "snapshot.db"
IDMAP = json.loads((REPO / "data/onsen-id-map.json").read_text())
BUCKET = ip.DEFAULT_BUCKET


# --- Firestore REST (mirrors backfill_fees.py; DRY into publisher/firestore_rest.py later) ---

def token() -> str:
    return subprocess.check_output(
        ["gcloud", "auth", "application-default", "print-access-token"], text=True
    ).strip()


def sval(v):
    return {"stringValue": v} if v else {"nullValue": None}


def _open(req, timeout=30, retries=3):
    """urlopen with a timeout, retrying transient network errors / 429 / 5xx."""
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


# --- backfill -----------------------------------------------------------------

def build_plan():
    """[(id, kid, name, image_url|None)] for every onsen, kyuhachiId resolved."""
    con = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select id, facility_name, image_url from onsens order by id"
        ).fetchall()
    finally:
        con.close()
    return [(oid, IDMAP.get(str(oid)), name, (img or None)) for oid, name, img in rows]


def process_one(kid: str, image_url: str, tok: str | None):
    """download → webp → blurhash, uploading only when `tok` is set (commit).
    Returns (image_url_for_firestore, blurhash, raw_bytes, webp_bytes)."""
    raw = ip.download(image_url)
    webp = ip.to_webp(raw)
    bh = ip.blurhash_of(raw)
    if tok is None:  # dry-run/probe: the URL is fully determined without uploading
        new_url = ip.download_url(BUCKET, kid, ip.download_token(kid))
    else:
        new_url = ip.upload(webp, kid, BUCKET, tok)
    return new_url, bh, len(raw), len(webp)


def _kb(n: int) -> str:
    return f"{n / 1024:.0f}KB"


def main() -> None:
    ap = argparse.ArgumentParser(description="Rehost onsen photos to Firebase Storage.")
    ap.add_argument("--commit", action="store_true", help="upload + execute the merge writes")
    ap.add_argument("--limit", type=int, default=None, help="process at most N onsens")
    ap.add_argument("--probe", action="store_true",
                    help="dry-run: actually download+resize+blurhash (no upload, no write) to show real sizes")
    args = ap.parse_args()

    plan = build_plan()
    if args.limit is not None:
        plan = plan[: args.limit]
    missing_kid = [oid for oid, kid, *_ in plan if kid is None]
    missing_img = [oid for oid, kid, _n, img in plan if kid and not img]
    writable = [(oid, kid, name, img) for oid, kid, name, img in plan if kid and img]

    mode = "COMMIT" if args.commit else ("PROBE" if args.probe else "DRY-RUN")
    print(f"image rehost — {mode}   project={PROJECT}   bucket={BUCKET}")
    print(f"onsens={len(plan)}  with-photo={len(writable)}  "
          f"no-photo={len(missing_img)}  no-kyuhachiId={len(missing_kid)}")
    if missing_kid:
        print(f"!! no kyuhachiId in onsen-id-map.json: {missing_kid}")

    # Plain dry-run: offline plan only (no network), mirroring backfill_fees.
    if not args.commit and not args.probe:
        print(f"\nDry-run only — nothing fetched or written. Would rehost {len(writable)} photos to "
              f"onsen-images/<kyuhachiId>.webp and PATCH imageUrl+blurhash, then bump the catalog version.")
        print("Re-run with --probe [--limit N] to verify the pipeline, or --commit to apply.")
        return

    tok = token() if args.commit else None
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    raw_total = webp_total = 0
    done = failed = 0
    print(f"\n-- {'rehosting' if args.commit else 'probing'} {len(writable)} photos --")
    for oid, kid, name, img in writable:
        try:
            new_url, bh, raw_n, webp_n = process_one(kid, img, tok)
            raw_total += raw_n
            webp_total += webp_n
            done += 1
            print(f"  id={oid:<4} {_kb(raw_n):>6} → {_kb(webp_n):>6}  bh={bh}  {name}")
            if args.commit:
                patch(f"onsens/{kid}",
                      {"imageUrl": sval(new_url), "blurhash": sval(bh),
                       "updatedAt": {"timestampValue": now}},
                      ["imageUrl", "blurhash", "updatedAt"], tok)
        except Exception as e:  # one bad photo must not abort the run
            failed += 1
            print(f"  id={oid:<4} !! FAILED ({type(e).__name__}: {e}) — leaving imageUrl untouched  {name}")

    saved = raw_total - webp_total
    pct = (saved / raw_total * 100) if raw_total else 0
    print(f"\n{'wrote' if args.commit else 'processed'} {done}, failed {failed}.  "
          f"bytes {_kb(raw_total)} → {_kb(webp_total)}  (−{pct:.0f}%)")
    if args.commit and done:
        bump_catalog_version(now, tok)
    elif not args.commit:
        print("Probe only — nothing uploaded or written. Re-run with --commit to apply.")


if __name__ == "__main__":
    main()
