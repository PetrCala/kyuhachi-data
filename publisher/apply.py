#!/usr/bin/env python3
"""
Surgical catalog publisher — apply *human-adjudicated* changes to Firestore as
MERGE writes. The additive opposite of the app repo's clean-slate reseed: it
PATCHes only named fields (updateMask), never overwrites a whole doc, never
deletes an onsen, and never touches /users/**.

This is the genesis of the versioned publisher. For now it takes an explicit,
hand-reviewed DECISIONS list (one adjudicated change per onsen):
  - {"hid": N, "action": "update"} → fetch the live page and merge the changed
    MATERIAL fields (+ updatedAt) into /onsens/{kyuhachiId}.
  - {"hid": N, "action": "retire"} → set isActive:false (+ updatedAt). Onsen
    docs are never deleted; existing visits + frozen challenge snapshots keep
    counting.

Auth: gcloud Application Default Credentials (same as the app repo's
reseed-catalog.py). Run `gcloud auth application-default login` if 401.

Usage:
  python publisher/apply.py            # dry-run (default): print the plan, write nothing
  python publisher/apply.py --commit   # execute the merge writes
"""
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / ".claude/skills/catalog-diff"))
from onsen_scraper import fetch_detail_page, parse_detail_page  # noqa: E402
import catalog_diff as cd  # noqa: E402

PROJECT = "kyuhachi-fddcc"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
IDMAP = json.loads((REPO / "data/onsen-id-map.json").read_text())

# parser field -> Firestore field path (MATERIAL fields only).
FIELD_PATH = {
    "prefecture": "prefecture", "address": "address", "phone": "phone",
    "admission_fee": "admissionFee", "spring_quality": "springQuality",
    "website_url": "websiteUrl", "business_hours": "businessHours.raw",
}

# Human-reviewed decisions from the catalog-diff run on 2026-06-23.
DECISIONS = [
    {"hid": 57, "action": "update", "note": "same onsen 源泉屋; official site → Instagram, address formalized"},
    {"hid": 248, "action": "retire", "note": "神の湯 (紫尾温泉) removed from source — detail page delisted"},
]


def token() -> str:
    return subprocess.check_output(
        ["gcloud", "auth", "application-default", "print-access-token"], text=True
    ).strip()


def sval(v):
    return {"stringValue": v} if v else {"nullValue": None}


def patch(kid: str, fields: dict, mask: list[str], tok: str) -> int:
    qs = "&".join(f"updateMask.fieldPaths={m}" for m in mask)
    req = urllib.request.Request(
        f"{BASE}/onsens/{kid}?{qs}", data=json.dumps({"fields": fields}).encode(),
        method="PATCH",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {e.read().decode()[:300]}")
        raise


def build_update(hid: int):
    """Fetch live, diff vs baseline, return (fields, mask, summary) for changed material fields."""
    base = cd.load_snapshot()[hid]
    live = parse_detail_page(fetch_detail_page(hid), hid)
    fields, mask, summary = {}, [], []
    for pf, path in FIELD_PATH.items():
        if cd.norm(pf, base.get(pf)) == cd.norm(pf, live.get(pf)):
            continue
        val = live.get(pf)
        summary.append((pf, base.get(pf), val))
        if "." in path:  # nested map field, e.g. businessHours.raw — preserves .schedule
            top, sub = path.split(".")
            fields.setdefault(top, {"mapValue": {"fields": {}}})["mapValue"]["fields"][sub] = sval(val)
        else:
            fields[path] = sval(val)
        mask.append(path)
    return fields, mask, summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", action="store_true", help="execute the merge writes")
    args = ap.parse_args()

    tok = token()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"Surgical catalog publish — {'COMMIT' if args.commit else 'DRY-RUN'}   project={PROJECT}\n")

    for d in DECISIONS:
        hid, kid = d["hid"], IDMAP[str(d["hid"])]
        if d["action"] == "retire":
            fields = {"isActive": {"booleanValue": False}, "updatedAt": {"timestampValue": now}}
            mask = ["isActive", "updatedAt"]
            print(f"hid {hid} → /onsens/{kid}  RETIRE isActive:false   # {d['note']}")
        else:
            fields, mask, summary = build_update(hid)
            if not summary:
                print(f"hid {hid} → no material changes vs source; skipping\n")
                continue
            fields["updatedAt"] = {"timestampValue": now}
            mask.append("updatedAt")
            print(f"hid {hid} → /onsens/{kid}  UPDATE   # {d['note']}")
            for pf, old, new in summary:
                print(f"    {pf}:  {old!r}\n           → {new!r}")
        print(f"    mask: {mask}")
        if args.commit:
            patch(kid, fields, mask, tok)
            print("    committed.")
        print()

    if not args.commit:
        print("Dry-run only — nothing written. Re-run with --commit to apply.")


if __name__ == "__main__":
    main()
