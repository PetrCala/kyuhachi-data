#!/usr/bin/env python3
"""
backfill-schedule — one-time backfill of structured `businessHours.schedule`.

Parses each onsen's free-text `business_hours` in the snapshot DB (offline — no
scraping) into the app's WeeklySchedule shape via the shared hours parser, then
MERGE-PATCHes it onto `/onsens/{kyuhachiId}` as `businessHours.schedule`
(preserving `businessHours.raw`), and bumps `/catalog_meta/current.version` so the
app refetches. Additive and idempotent — same contract as `apply.py` /
`backfill_fees.py`: never overwrites other fields, never deletes.

Only onsens with a confidently-structured schedule are written (single window +
無休/explicit weekday closure, plus the no-hours→24/7 policy); irregular /
multi-window / partial hours are left as `raw` only. The ongoing path (recompute
`schedule` whenever `business_hours` changes) lives in `publisher/apply.py`; this
script is the initial fill across the existing catalog.

Auth: gcloud Application Default Credentials. Run `gcloud auth
application-default login` if 401. Dry-run needs no auth — the plan is computed
entirely from the local snapshot.

Usage:
  python publisher/backfill_schedule.py            # dry-run (default): plan only, no writes
  python publisher/backfill_schedule.py --show     # also list every onsen + its parse reason
  python publisher/backfill_schedule.py --commit   # execute the merge writes + version bump
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
from onsen_scraper.hours import parse_hours, parsed_hours_doc  # noqa: E402

PROJECT = "kyuhachi-fddcc"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
SNAPSHOT_DB = REPO / "data" / "snapshot.db"
IDMAP = json.loads((REPO / "data/onsen-id-map.json").read_text())
CURATED = REPO / "data" / "hours_curated.json"

DAYS_FULL = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_ABBR = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def expand_curated(entry: dict):
    """Expand a curated entry into an app WeeklySchedule, or None if not published.
    Each day = the base window, unless listed in `closed` (→ null) or overridden."""
    if not entry.get("publish"):
        return None
    o, c = entry["window"]
    sched = {}
    for abbr, day in zip(_ABBR, DAYS_FULL):
        if abbr in entry["closed"]:
            sched[day] = None
        elif abbr in entry["overrides"]:
            ov = entry["overrides"][abbr]
            sched[day] = None if ov is None else {"opens": ov[0], "closes": ov[1]}
        else:
            sched[day] = {"opens": o, "closes": c}
    return sched


# --- Firestore REST (mirrors apply.py / backfill_fees.py; DRY into
#     publisher/firestore_rest.py later — see roadmap item D) -------------------

def token() -> str:
    return subprocess.check_output(
        ["gcloud", "auth", "application-default", "print-access-token"], text=True
    ).strip()


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


def sched_val(schedule):
    """Encode a WeeklySchedule (or None) as a Firestore typed value (null day = closed;
    whole-null when unstructured)."""
    if schedule is None:
        return {"nullValue": None}
    days = {}
    for day, slot in schedule.items():
        days[day] = ({"nullValue": None} if slot is None else
                     {"mapValue": {"fields": {"opens": {"stringValue": slot["opens"]},
                                              "closes": {"stringValue": slot["closes"]}}}})
    return {"mapValue": {"fields": days}}


def live_schedule(bhf: dict):
    """Decode a live businessHours.schedule typed-value into {day: {opens,closes}|None}|None."""
    s = bhf.get("schedule")
    if not s or "nullValue" in s:
        return None
    f = s.get("mapValue", {}).get("fields", {})
    out = {}
    for day in DAYS_FULL:
        v = f.get(day, {})
        if "nullValue" in v or not v:
            out[day] = None
        else:
            sf = v["mapValue"]["fields"]
            out[day] = {"opens": sf["opens"]["stringValue"], "closes": sf["closes"]["stringValue"]}
    return out


# --- backfill -----------------------------------------------------------------

def build_plan():
    """[(id, kid, name, schedule|None, reason)] for every onsen, kyuhachiId resolved."""
    con = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select id, facility_name, business_hours from onsens order by id"
        ).fetchall()
    finally:
        con.close()
    plan = []
    for oid, name, raw in rows:
        schedule = parsed_hours_doc(raw)["schedule"]
        plan.append((oid, IDMAP.get(str(oid)), name, schedule, parse_hours(raw).reason))
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


def _names() -> dict:
    con = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    try:
        return {str(r[0]): r[1] for r in con.execute("select id, facility_name from onsens")}
    finally:
        con.close()


def _closed_str(s) -> str:
    if s is None:
        return "raw"
    cl = [d[:3] for d, v in s.items() if v is None]
    return "closed:" + ",".join(cl) if cl else "open-all"


def run_curated(commit: bool, show: bool) -> None:
    """Backfill from the hand-curated data/hours_curated.json: read each live doc,
    diff its schedule against the curated target, and write only the changes
    (new/corrected structured schedules, or clear ones now deemed unstructured)."""
    cur = json.loads(CURATED.read_text(encoding="utf-8"))["onsens"]
    names = _names()
    tok = token()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"curated schedule backfill — {'COMMIT' if commit else 'DRY-RUN'}   "
          f"project={PROJECT}   onsens={len(cur)}\nreading live schedules…")

    writes, clears, unchanged, deferred, skipped = [], [], 0, [], []
    for hid, entry in cur.items():
        if entry["status"] == "deferred-annual":
            deferred.append(hid)
        kid = IDMAP.get(hid)
        fields = get_fields(f"onsens/{kid}", tok) if kid else None
        if not kid or fields is None:
            skipped.append(hid)
            continue
        bhf = fields.get("businessHours", {}).get("mapValue", {}).get("fields", {})
        live, target = live_schedule(bhf), expand_curated(entry)
        if target == live:
            unchanged += 1
        elif target is not None:
            writes.append((hid, kid, entry, live, target))
        else:
            clears.append((hid, kid, entry, live))

    print(f"\n  writes  (new/corrected structured): {len(writes)}")
    print(f"  clears  (live had a schedule, now raw): {len(clears)}")
    print(f"  unchanged: {unchanged}   deferred-annual (left raw): {len(deferred)}   "
          f"skipped (no kid/doc): {len(skipped)}")
    if show or not commit:
        for hid, _kid, entry, live, target in writes:
            print(f"  WRITE id={hid:<4} {_closed_str(live):>14} → {_closed_str(target):<14} "
                  f"[{entry['confidence']}] {names.get(hid,'')[:20]}  ({entry['note']})")
        for hid, _kid, entry, live in clears:
            print(f"  CLEAR id={hid:<4} {_closed_str(live):>14} → raw            "
                  f"{names.get(hid,'')[:20]}  ({entry['status']})")
    if deferred:
        print(f"  deferred-annual (open-all-week candidates, left raw pending policy): "
              f"{','.join(deferred)}")

    if not commit:
        print(f"\nDry-run only — nothing written. Would write {len(writes)} and clear "
              f"{len(clears)} schedules, then bump catalog_meta/current.version. Re-run with --commit.")
        return

    print(f"\n-- writing {len(writes)} + clearing {len(clears)} businessHours.schedule --")
    for hid, kid, _e, _live, target in writes:
        patch(f"onsens/{kid}",
              {"businessHours": {"mapValue": {"fields": {"schedule": sched_val(target)}}},
               "updatedAt": {"timestampValue": now}},
              ["businessHours.schedule", "updatedAt"], tok)
    for hid, kid, _e, _live in clears:
        patch(f"onsens/{kid}",
              {"businessHours": {"mapValue": {"fields": {"schedule": sched_val(None)}}},
               "updatedAt": {"timestampValue": now}},
              ["businessHours.schedule", "updatedAt"], tok)
    print(f"    wrote {len(writes)}, cleared {len(clears)}.")
    bump_catalog_version(now, tok)


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill structured businessHours.schedule onto the catalog.")
    ap.add_argument("--from-curated", action="store_true",
                    help="backfill from the hand-curated data/hours_curated.json (LLM parse) "
                         "instead of the regex parser; diffs vs live and writes only changes")
    ap.add_argument("--show", action="store_true", help="list every onsen and its parse reason")
    ap.add_argument("--commit", action="store_true", help="execute the merge writes")
    args = ap.parse_args()

    if args.from_curated:
        run_curated(args.commit, args.show)
        return

    plan = build_plan()
    counts = Counter(reason for *_, reason in plan)
    # Writable = a structured schedule AND a known kyuhachiId.
    writable = [p for p in plan if p[3] is not None and p[1] is not None]
    missing = [oid for oid, kid, _n, sched, _r in plan if sched is not None and kid is None]

    print(f"schedule backfill — {'COMMIT' if args.commit else 'DRY-RUN'}   "
          f"project={PROJECT}   onsens={len(plan)}")
    print(f"  structured (writable): {len(writable)}   raw-only (skipped): {len(plan) - len(writable)}")
    print(f"  by reason: {dict(counts)}")
    if missing:
        print(f"!! {len(missing)} structured onsens have no kyuhachiId in onsen-id-map.json: {missing}")

    if args.show:
        for oid, kid, name, sched, reason in plan:
            mark = "write" if (sched is not None and kid is not None) else "skip "
            closed = ",".join(d[:2] for d, s in sched.items() if s is None) if sched else "-"
            print(f"  [{mark}] id={oid:<4} {reason:<17} closed={closed:<11} {name}")

    if not args.commit:
        print(f"\nDry-run only — nothing written. Would PATCH businessHours.schedule on "
              f"{len(writable)} onsens and bump catalog_meta/current.version. Re-run with --commit.")
        return

    tok = token()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"\n-- writing businessHours.schedule on {len(writable)} onsens --")
    for oid, kid, _name, sched, _reason in writable:
        patch(f"onsens/{kid}",
              {"businessHours": {"mapValue": {"fields": {"schedule": sched_val(sched)}}},
               "updatedAt": {"timestampValue": now}},
              ["businessHours.schedule", "updatedAt"], tok)
    print(f"    wrote {len(writable)}.")
    bump_catalog_version(now, tok)


if __name__ == "__main__":
    main()
