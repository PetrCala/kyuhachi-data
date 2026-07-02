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
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from onsen_scraper.hours import parse_hours, parsed_hours_doc  # noqa: E402
from firestore_rest import (  # noqa: E402
    PROJECT, bump_catalog_version, get_fields, live_onsens, patch, token,
)

SNAPSHOT_DB = REPO / "data" / "snapshot.db"
IDMAP = json.loads((REPO / "data/onsen-id-map.json").read_text())
CURATED = REPO / "data" / "hours_curated.json"

DAYS_FULL = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_ABBR = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def norm_windows(v):
    """Normalize a curated window value — ["HH:MM","HH:MM"] or [[o,c], [o,c], …]
    (chronological) — to a list of [opens, closes] pairs; None stays None."""
    if v is None:
        return None
    return [list(v)] if isinstance(v[0], str) else [list(w) for w in v]


def _day_slot(windows):
    """DaySchedule from normalized windows. `opens`/`closes` mirror the FIRST
    window — the one true window legacy readers display (false-closed direction
    only, never false-open); the full list ships in `windows` only when ≥2."""
    slot = {"opens": windows[0][0], "closes": windows[0][1]}
    if len(windows) > 1:
        slot["windows"] = [{"opens": o, "closes": c} for o, c in windows]
    return slot


def expand_curated(entry: dict):
    """Expand a curated entry into an app WeeklySchedule, or None if not published.
    Each day = the base window(s), unless listed in `closed` (→ null) or overridden."""
    if not entry.get("publish"):
        return None
    base = norm_windows(entry["window"])
    sched = {}
    for abbr, day in zip(_ABBR, DAYS_FULL):
        if abbr in entry["closed"]:
            sched[day] = None
        elif abbr in entry["overrides"]:
            ov = norm_windows(entry["overrides"][abbr])
            sched[day] = None if ov is None else _day_slot(ov)
        else:
            sched[day] = _day_slot(base)
    return sched


def published_confidence(entry: dict) -> str:
    """The published businessHours.confidence for a curated entry. The curated
    `confidence` records PARSE confidence; irregular closure (不定休) is a
    schedule-reliability problem on top of a confident parse, so an irregular
    entry that publishes a grid caps it at "low" — which drives the app's
    call-ahead hint (docs/hours-schema.md). Unpublished entries pass through:
    with no grid claimed, the caption already carries the caveat."""
    if entry["status"] == "irregular" and entry.get("publish"):
        return "low"
    return entry["confidence"]


def _win_val(w: dict) -> dict:
    return {"mapValue": {"fields": {"opens": {"stringValue": w["opens"]},
                                    "closes": {"stringValue": w["closes"]}}}}


def _slot_val(slot: dict) -> dict:
    fields = {"opens": {"stringValue": slot["opens"]},
              "closes": {"stringValue": slot["closes"]}}
    if "windows" in slot:
        fields["windows"] = {"arrayValue": {"values": [_win_val(w) for w in slot["windows"]]}}
    return {"mapValue": {"fields": fields}}


def sched_val(schedule):
    """Encode a WeeklySchedule (or None) as a Firestore typed value (null day = closed;
    whole-null when unstructured; multi-window days carry a `windows` array)."""
    if schedule is None:
        return {"nullValue": None}
    days = {}
    for day, slot in schedule.items():
        days[day] = {"nullValue": None} if slot is None else _slot_val(slot)
    return {"mapValue": {"fields": days}}


def live_schedule(bhf: dict):
    """Decode a live businessHours.schedule typed-value into
    {day: {opens, closes, windows?} | None} | None."""
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
            slot = {"opens": sf["opens"]["stringValue"], "closes": sf["closes"]["stringValue"]}
            wins = sf.get("windows", {}).get("arrayValue", {}).get("values", [])
            if wins:
                slot["windows"] = [
                    {"opens": w["mapValue"]["fields"]["opens"]["stringValue"],
                     "closes": w["mapValue"]["fields"]["closes"]["stringValue"]}
                    for w in wins]
            out[day] = slot
    return out


def _rule_val(rule: dict) -> dict:
    """Encode a structured closure rule: strings as-is, int lists (weeks / days /
    exceptMonths / onlyMonths) as integer arrays."""
    fields = {}
    for k, v in rule.items():
        if isinstance(v, str):
            fields[k] = {"stringValue": v}
        else:
            fields[k] = {"arrayValue": {"values": [{"integerValue": str(i)} for i in v]}}
    return {"mapValue": {"fields": fields}}


def exc_val(exceptions: list) -> dict:
    """Encode exceptions [{en, ja, rule?}] as a Firestore arrayValue. `rule` is
    the optional machine-readable twin of the caption (docs/hours-schema.md)."""
    values = []
    for e in exceptions:
        fields = {"en": {"stringValue": e["en"]}, "ja": {"stringValue": e["ja"]}}
        if e.get("rule"):
            fields["rule"] = _rule_val(e["rule"])
        values.append({"mapValue": {"fields": fields}})
    return {"arrayValue": {"values": values}}


def conf_val(confidence: str) -> dict:
    return {"stringValue": confidence}


def le_val(last_entry) -> dict:
    """Encode businessHours.lastEntry ("HH:MM" or None)."""
    return {"stringValue": last_entry} if last_entry else {"nullValue": None}


def live_exceptions(bhf: dict) -> list:
    vals = bhf.get("exceptions", {}).get("arrayValue", {}).get("values", [])
    out = []
    for v in vals:
        f = v.get("mapValue", {}).get("fields", {})
        x = {"en": f.get("en", {}).get("stringValue", ""),
             "ja": f.get("ja", {}).get("stringValue", "")}
        rf = f.get("rule", {}).get("mapValue", {}).get("fields")
        if rf:
            x["rule"] = {k: (rv["stringValue"] if "stringValue" in rv else
                             [int(i["integerValue"]) for i in rv.get("arrayValue", {}).get("values", [])])
                         for k, rv in rf.items()}
        out.append(x)
    return out


def live_confidence(bhf: dict):
    return bhf.get("confidence", {}).get("stringValue")


def live_last_entry(bhf: dict):
    return bhf.get("lastEntry", {}).get("stringValue")


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


def split_writes(writable, live):
    """Partition writable rows into (to_write, current) by whether the structured
    businessHours.schedule would actually change the live doc. `live` is {kid:
    fields} from firestore_rest; None (live unread) → treat every row as a write."""
    if live is None:
        return list(writable), []
    to_write, current = [], []
    for row in writable:
        bhf = live.get(row[1], {}).get("businessHours", {}).get("mapValue", {}).get("fields", {})
        (current if live_schedule(bhf) == row[3] else to_write).append(row)
    return to_write, current


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
    """Backfill from data/hours_curated.json: read each live doc, diff the four
    structured sub-fields (schedule, exceptions, confidence, lastEntry) against
    the curated target, and PATCH only the fields that changed."""
    cur = json.loads(CURATED.read_text(encoding="utf-8"))["onsens"]
    names = _names()
    tok = token()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"curated hours backfill — {'COMMIT' if commit else 'DRY-RUN'}   "
          f"project={PROJECT}   onsens={len(cur)}\nreading live docs…")

    changed = []          # (hid, bh_fields, mask, summary)
    n = {"schedule": 0, "clear": 0, "exceptions": 0, "confidence": 0, "lastEntry": 0}
    deferred, skipped = [], []
    for hid, entry in cur.items():
        if entry["status"] == "deferred-annual":
            deferred.append(hid)
        kid = IDMAP.get(hid)
        fields = get_fields(f"onsens/{kid}", tok) if kid else None
        if not kid or fields is None:
            skipped.append(hid)
            continue
        bhf = fields.get("businessHours", {}).get("mapValue", {}).get("fields", {})
        bh, mask, summary = {}, [], []

        t_sched, l_sched = expand_curated(entry), live_schedule(bhf)
        if t_sched != l_sched:
            bh["schedule"] = sched_val(t_sched)
            mask.append("businessHours.schedule")
            if t_sched is None:
                n["clear"] += 1
                summary.append(f"sched {_closed_str(l_sched)}→raw")
            else:
                n["schedule"] += 1
                summary.append(f"sched {_closed_str(l_sched)}→{_closed_str(t_sched)}")

        t_exc, l_exc = entry.get("exceptions", []), live_exceptions(bhf)
        if t_exc != l_exc:
            bh["exceptions"] = exc_val(t_exc)
            mask.append("businessHours.exceptions")
            n["exceptions"] += 1
            summary.append(f"exc {len(l_exc)}→{len(t_exc)}")

        t_conf, l_conf = published_confidence(entry), live_confidence(bhf)
        if t_conf != l_conf:
            bh["confidence"] = conf_val(t_conf)
            mask.append("businessHours.confidence")
            n["confidence"] += 1
            summary.append(f"conf {l_conf}→{t_conf}")

        t_le, l_le = entry.get("lastEntry"), live_last_entry(bhf)
        if t_le != l_le:
            bh["lastEntry"] = le_val(t_le)
            mask.append("businessHours.lastEntry")
            n["lastEntry"] += 1
            summary.append(f"lastEntry {l_le}→{t_le}")

        if mask:
            changed.append((hid, kid, {"businessHours": {"mapValue": {"fields": bh}}}, mask, summary))

    print(f"\n  docs to PATCH: {len(changed)}   (schedule {n['schedule']}, clears {n['clear']}, "
          f"exceptions {n['exceptions']}, confidence {n['confidence']}, lastEntry {n['lastEntry']})")
    print(f"  deferred-annual (left raw): {len(deferred)}   skipped (no kid/doc): {len(skipped)}")
    # schedule changes are the interesting ones — always list those; field-only writes are uniform.
    if show or not commit:
        for hid, _kid, _f, _mask, summary in changed:
            if any(s.startswith("sched") for s in summary) or show:
                print(f"  id={hid:<4} {names.get(hid,'')[:22]:<22} {'; '.join(summary)}")
    if deferred:
        print(f"  deferred-annual: {','.join(deferred)}")

    if not commit:
        print("\nDry-run only — nothing written. Re-run with --commit.")
        return

    if not changed:
        print("\nAll docs already current — nothing written, version not bumped.")
        return
    print(f"\n-- patching {len(changed)} docs --")
    for _hid, kid, fields, mask, _s in changed:
        fields["updatedAt"] = {"timestampValue": now}
        patch(f"onsens/{kid}", fields, mask + ["updatedAt"], tok)
    print(f"    patched {len(changed)}.")
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

    # Read current businessHours.schedule once and skip docs already carrying it.
    tok, live = live_onsens(args.commit)
    to_write, current = split_writes(writable, live)
    unknown = " (live unread — counted as changes)" if live is None else ""
    print(f"\nwould change: {len(to_write)}   already current: {len(current)}{unknown}")

    if not args.commit:
        print(f"\nDry-run only — nothing written. Would PATCH businessHours.schedule on "
              f"{len(to_write)} onsens" + (" and bump catalog_meta/current.version" if to_write
              else " (none — version would NOT be bumped)") + ". Re-run with --commit.")
        return

    if not to_write:
        print("\nAll docs already current — nothing written, version not bumped.")
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"\n-- writing businessHours.schedule on {len(to_write)} changed onsens --")
    for oid, kid, _name, sched, _reason in to_write:
        patch(f"onsens/{kid}",
              {"businessHours": {"mapValue": {"fields": {"schedule": sched_val(sched)}}},
               "updatedAt": {"timestampValue": now}},
              ["businessHours.schedule", "updatedAt"], tok)
    print(f"    wrote {len(to_write)}.")
    bump_catalog_version(now, tok)


if __name__ == "__main__":
    main()
