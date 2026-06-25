#!/usr/bin/env python3
"""
Surgical catalog publisher — apply *human-adjudicated* changes to Firestore as
MERGE writes. The additive opposite of the app repo's clean-slate reseed: it
PATCHes only named fields (updateMask), never overwrites a whole doc, never
deletes an onsen, and never touches /users/**.

It is driven by a reviewed *decisions* file (one adjudicated change per onsen):
  - {"hid": N, "action": "update"} → fetch the live page and merge the changed
    MATERIAL fields (+ updatedAt) into /onsens/{kyuhachiId}.
  - {"hid": N, "action": "retire"} → set isActive:false (+ updatedAt). Onsen
    docs are never deleted; existing visits + frozen challenge snapshots keep
    counting.
  - {"hid": N, "action": "skip"}   → no-op (explicitly reviewed, no change).

The decisions file is normally scaffolded from a catalog-diff changelog.json
(--from-changelog), then hand-reviewed before applying.

Auth: gcloud Application Default Credentials (same as the app repo's
reseed-catalog.py). Run `gcloud auth application-default login` if 401.

Usage:
  # 1. scaffold a decisions skeleton from a diff changelog (no writes, no auth):
  python publisher/apply.py --from-changelog reports/<ts>/changelog.json --out decisions.json
  # 2. review/edit decisions.json, then dry-run (re-fetches the live pages):
  python publisher/apply.py --decisions decisions.json
  # 3. apply:
  python publisher/apply.py --decisions decisions.json --commit
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
from onsen_scraper import fee_for, fetch_detail_page, parse_detail_page  # noqa: E402
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

ACTIONS = ("update", "retire", "skip")  # `add` (new onsen) needs a kyuhachiId first — not here yet


def token() -> str:
    return subprocess.check_output(
        ["gcloud", "auth", "application-default", "print-access-token"], text=True
    ).strip()


def sval(v):
    return {"stringValue": v} if v else {"nullValue": None}


def ival(n):
    return {"nullValue": None} if n is None else {"integerValue": str(n)}


def _open(req, timeout=30, retries=3):
    """urlopen with a timeout, retrying transient network errors / 429 / 5xx.
    A single hung connection must not stall a 100+ doc publish loop forever."""
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


def patch(kid: str, fields: dict, mask: list[str], tok: str) -> int:
    qs = "&".join(f"updateMask.fieldPaths={m}" for m in mask)
    req = urllib.request.Request(
        f"{BASE}/onsens/{kid}?{qs}", data=json.dumps({"fields": fields}).encode(),
        method="PATCH",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    try:
        with _open(req) as r:
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
    # Keep numeric adultFee in sync whenever the fee text changes, so the app's
    # cost stats never go stale — derived via the shared fees parser (one source
    # of truth, same as the cost-analysis skill + backfill).
    if "admissionFee" in mask:
        fields["adultFee"] = ival(fee_for(hid, live.get("admission_fee"))[0])
        mask.append("adultFee")
    return fields, mask, summary


def load_decisions(path: Path) -> list[dict]:
    """Read a reviewed decisions file. Accepts a top-level list or {"decisions": [...]}.
    Each item: {hid, action: update|retire|skip, note?}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["decisions"] if isinstance(data, dict) else data
    bad = sorted({d.get("action") for d in items if d.get("action") not in ACTIONS})
    if bad:
        raise SystemExit(f"unknown action(s) in {path}: {bad}; allowed {ACTIONS}")
    return items


def scaffold_from_changelog(path: Path) -> list[dict]:
    """Turn a catalog-diff changelog.json into a decisions skeleton for human review.
    Defaults: material→update, low-signal→skip, removed→retire, added/fetchFailed→skip.
    The human edits the actions before applying."""
    cl = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for m in cl.get("modified", []):
        if m.get("severity") == "material":
            out.append({"hid": m["hid"], "action": "update",
                        "note": "material: " + ", ".join(m.get("materialFields", []))})
        else:
            out.append({"hid": m["hid"], "action": "skip",
                        "note": "low-signal only: " + ", ".join(m.get("mutedFields", []))})
    for r in cl.get("removed", []):
        out.append({"hid": r["hid"], "action": "retire", "note": "removed/delisted at source"})
    for a in cl.get("added", []):
        out.append({"hid": a["hid"], "action": "skip",
                    "note": "NEW onsen — assign a kyuhachiId first (not auto-handled)"})
    for f in cl.get("fetchFailed", []):
        out.append({"hid": f["hid"], "action": "skip", "note": "fetch failed — re-run before deciding"})
    return out


def apply_decision(d: dict, now: str, tok: str | None, commit: bool) -> None:
    hid = d["hid"]
    note = d.get("note", "")
    if d["action"] == "skip":
        print(f"hid {hid} → SKIP   # {note}\n")
        return
    if str(hid) not in IDMAP:
        print(f"hid {hid} → no kyuhachiId in id map; skipping\n")
        return
    kid = IDMAP[str(hid)]
    if d["action"] == "retire":
        fields = {"isActive": {"booleanValue": False}, "updatedAt": {"timestampValue": now}}
        mask = ["isActive", "updatedAt"]
        print(f"hid {hid} → /onsens/{kid}  RETIRE isActive:false   # {note}")
    else:  # update
        fields, mask, summary = build_update(hid)
        if not summary:
            print(f"hid {hid} → UPDATE: no material changes vs source; nothing to write\n")
            return
        fields["updatedAt"] = {"timestampValue": now}
        mask.append("updatedAt")
        print(f"hid {hid} → /onsens/{kid}  UPDATE   # {note}")
        for pf, old, new in summary:
            print(f"    {pf}:  {old!r}\n           → {new!r}")
    print(f"    mask: {mask}")
    if commit:
        patch(kid, fields, mask, tok)
        print("    committed.")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--decisions", type=Path, help="reviewed decisions JSON to apply")
    ap.add_argument("--from-changelog", type=Path,
                    help="scaffold a decisions skeleton from a catalog-diff changelog.json (no apply)")
    ap.add_argument("--out", type=Path, help="write the scaffold here (default: stdout)")
    ap.add_argument("--commit", action="store_true", help="execute the merge writes (with --decisions)")
    args = ap.parse_args()

    if args.from_changelog:
        skeleton = scaffold_from_changelog(args.from_changelog)
        text = json.dumps({"decisions": skeleton}, ensure_ascii=False, indent=2)
        if args.out:
            args.out.write_text(text + "\n", encoding="utf-8")
            print(f"wrote {len(skeleton)}-item decisions skeleton → {args.out}  "
                  "(review/edit the actions, then re-run with --decisions to apply)")
        else:
            print(text)
        return

    if not args.decisions:
        raise SystemExit("provide --decisions FILE to apply, or --from-changelog FILE to scaffold one")

    decisions = load_decisions(args.decisions)
    tok = token() if args.commit else None
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"Surgical catalog publish — {'COMMIT' if args.commit else 'DRY-RUN'}   "
          f"project={PROJECT}   decisions={args.decisions.name} ({len(decisions)})\n")
    for d in decisions:
        apply_decision(d, now, tok, args.commit)
    if not args.commit:
        print("Dry-run only — nothing written. Re-run with --commit to apply.")


if __name__ == "__main__":
    main()
