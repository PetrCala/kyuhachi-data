#!/usr/bin/env python3
"""
recurate-hours — maintenance helper for data/hours_curated.json.

`data/hours_curated.json` is the source of truth for the structured business-hours
parse — one entry per onsen (keyed by 88onsen hid), produced by a one-time LLM
parse of the free-text `business_hours` column in `data/snapshot.db`. When
88onsen updates an onsen's `business_hours`, that curated entry goes stale. This
helper supports the read-only/offline scaffolding of the re-curation flow:

  targets   — which onsens to re-parse (from a catalog-diff changelog).
  show      — dump each target's `business_hours` text + its current curated
              entry, so the SESSION MODEL (not a regex) can re-parse it per
              docs/hours-schema.md.
  set       — merge model-refreshed entries back into hours_curated.json,
              validating each entry's shape and preserving the file's exact
              formatting + numeric key ordering.
  validate  — re-check every curated entry against the schema invariants
              (a fast local pre-check before the pytest suite).

The LLM re-parse itself is NOT done here. `onsen_scraper/hours.py` is a regex
parser that is deliberately unreliable on Japanese phrasing (e.g. `翌日休` "closed
the next day" misread as 日曜/Sunday) — which is exactly why a refresh must be
done by the session model, reading docs/hours-schema.md, not by the regex. This
helper only moves source text IN (`show`) and structured entries OUT (`set`).

Read-only by default. `set` is the only writer, and it writes ONLY
data/hours_curated.json — never the snapshot DB, never Firestore. Publishing is a
separate, explicit step (`publisher/backfill_schedule.py --from-curated --commit`).

Usage:
  python recurate_hours.py targets --changelog reports/<ts>/changelog.json
  python recurate_hours.py show 5 99 --changelog reports/<ts>/changelog.json
  python recurate_hours.py show 5 99                 # source text from snapshot.db
  python recurate_hours.py set --file refreshed.json # merge {hid: entry, ...}
  python recurate_hours.py set --hid 99 --file one.json
  python recurate_hours.py validate
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

# This file lives at <repo>/.claude/skills/recurate-hours/recurate_hours.py.
REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_DB = REPO_ROOT / "data" / "snapshot.db"
CURATED = REPO_ROOT / "data" / "hours_curated.json"

# Detection-only helper for `validate`'s last-entry guard. It reads the source
# text to CHECK the curated captions; it never authors the schedule (the regex
# parser stays out of that — see onsen_scraper/hours.py). Add the repo root to
# sys.path so this skill script can import the package.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from onsen_scraper.hours import last_entry_caption, single_last_entry  # noqa: E402

# Weekday abbreviations used in `closed` / `overrides` (Mon-first), matching
# publisher/backfill_schedule.py._ABBR and the app's WeeklySchedule key order.
ABBR = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAYS_FULL = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
STATUSES = {"structured", "irregular", "monthly", "multi-window", "seasonal", "deferred-annual"}
CONFIDENCE = {"high", "medium", "low"}
# Canonical key order for a curated entry — `set` re-emits in this order so the
# file stays uniform regardless of how the model ordered its keys.
ENTRY_KEYS = ("publish", "status", "window", "closed", "overrides", "lastEntry",
              "confidence", "note", "exceptions")
_TIME = re.compile(r"^\d{1,2}:\d{2}$")  # HH:MM, 24+ allowed for past-midnight (e.g. 25:00)

# Structured closure rules — the machine-readable twin an exception caption may
# carry (docs/hours-schema.md). Keyed by rule kind → its allowed fields.
RULE_FIELDS = {
    "monthlyWeekday": {"kind", "weeks", "weekday", "holidayPolicy", "exceptMonths", "onlyMonths"},
    "monthlyDay": {"kind", "days"},
    "irregular": {"kind"},
}
HOLIDAY_POLICIES = {"nextDay", "nextWeekday", "skip", "varies"}


# --- snapshot + curated I/O ---------------------------------------------------

def load_curated() -> dict:
    return json.loads(CURATED.read_text(encoding="utf-8"))


def write_curated(doc: dict) -> None:
    """Write hours_curated.json with the repo's exact formatting (2-space indent,
    no ASCII-escaping, numeric key order, trailing newline) — a byte-stable
    round-trip when nothing changed."""
    doc["onsens"] = {k: doc["onsens"][k] for k in sorted(doc["onsens"], key=int)}
    CURATED.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snapshot_hours(hids=None) -> dict:
    """{hid(str): {"name", "business_hours"}} from the snapshot DB (read-only)."""
    con = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    try:
        rows = con.execute("select id, facility_name, business_hours from onsens").fetchall()
    finally:
        con.close()
    want = {str(h) for h in hids} if hids is not None else None
    return {str(i): {"name": n, "business_hours": bh}
            for i, n, bh in rows if want is None or str(i) in want}


def changelog_hours(path: Path) -> dict:
    """{hid(str): new_business_hours} for onsens whose `business_hours` changed,
    read out of a catalog-diff changelog.json. Empty for non-business_hours diffs."""
    cl = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for m in cl.get("modified", []):
        fields = m.get("fields", {})
        if "business_hours" in fields:
            out[str(m["hid"])] = fields["business_hours"].get("new")
    return out


# --- validation (mirrors tests/test_publish_schedule.py invariants) -----------

def _mins(t: str) -> int:
    h, m = str(t).split(":")
    return int(h) * 60 + int(m)


def _window_problems(hid: str, label: str, v) -> list:
    """Problems with one window value: ["HH:MM","HH:MM"] or [[o,c], [o,c], …]
    (each window opens before it closes; multi-windows chronological and
    non-overlapping). Null is NOT accepted here — callers handle it."""
    wins = [v] if (isinstance(v, list) and v and isinstance(v[0], str)) else v
    if not (isinstance(wins, list) and wins and all(
            isinstance(w, list) and len(w) == 2 and all(_TIME.match(str(t)) for t in w)
            for w in wins)):
        return [f"id {hid}: {label} must be [HH:MM, HH:MM] or a list of such windows, got {v!r}"]
    errs, prev_close = [], None
    for o, c in wins:
        if _mins(o) >= _mins(c):
            errs.append(f"id {hid}: {label} window {o}–{c} must open before it closes")
        if prev_close is not None and _mins(o) < prev_close:
            errs.append(f"id {hid}: {label} windows must be chronological and non-overlapping")
        prev_close = _mins(c)
    return errs


def _rule_problems(hid: str, i: int, r) -> list:
    """Problems with one exception's structured `rule` (docs/hours-schema.md)."""
    where = f"id {hid}: exceptions[{i}].rule"
    if not isinstance(r, dict) or r.get("kind") not in RULE_FIELDS:
        return [f"{where}: kind must be one of {sorted(RULE_FIELDS)}, got {r!r}"]
    errs, kind = [], r["kind"]
    unknown = set(r) - RULE_FIELDS[kind]
    if unknown:
        errs.append(f"{where}: unknown key(s) {sorted(unknown)} for kind {kind}")
    if kind == "monthlyWeekday":
        weeks = r.get("weeks")
        if not (isinstance(weeks, list) and weeks
                and all(isinstance(w, int) and 1 <= w <= 5 for w in weeks)):
            errs.append(f"{where}: weeks must be a non-empty list of 1..5, got {weeks!r}")
        if r.get("weekday") not in WEEKDAYS_FULL:
            errs.append(f"{where}: weekday must be one of {list(WEEKDAYS_FULL)}, got {r.get('weekday')!r}")
        if "holidayPolicy" in r and r["holidayPolicy"] not in HOLIDAY_POLICIES:
            errs.append(f"{where}: holidayPolicy must be one of {sorted(HOLIDAY_POLICIES)}")
        for k in ("exceptMonths", "onlyMonths"):
            if k in r and not (isinstance(r[k], list) and r[k]
                               and all(isinstance(m, int) and 1 <= m <= 12 for m in r[k])):
                errs.append(f"{where}: {k} must be a non-empty list of months 1..12")
        if "exceptMonths" in r and "onlyMonths" in r:
            errs.append(f"{where}: exceptMonths and onlyMonths are mutually exclusive")
    elif kind == "monthlyDay":
        days = r.get("days")
        if not (isinstance(days, list) and days
                and all(isinstance(d, int) and 1 <= d <= 31 for d in days)):
            errs.append(f"{where}: days must be a non-empty list of 1..31, got {days!r}")
    return errs


def validate_entry(hid: str, e) -> list:
    """Return a list of human-readable problems with one curated entry ([] = ok)."""
    errs = []
    if not isinstance(e, dict):
        return [f"id {hid}: entry must be an object, got {type(e).__name__}"]

    unknown = set(e) - set(ENTRY_KEYS)
    if unknown:
        errs.append(f"id {hid}: unknown key(s) {sorted(unknown)} (allowed: {list(ENTRY_KEYS)})")
    for k in ("publish", "status", "closed", "overrides", "confidence", "exceptions"):
        if k not in e:
            errs.append(f"id {hid}: missing required key '{k}'")

    if "publish" in e and not isinstance(e["publish"], bool):
        errs.append(f"id {hid}: publish must be a bool")
    if e.get("status") not in STATUSES:
        errs.append(f"id {hid}: status {e.get('status')!r} not in {sorted(STATUSES)}")
    if e.get("confidence") not in CONFIDENCE:
        errs.append(f"id {hid}: confidence {e.get('confidence')!r} not in {sorted(CONFIDENCE)}")

    closed = e.get("closed", [])
    if not isinstance(closed, list) or set(closed) - set(ABBR):
        errs.append(f"id {hid}: closed must be a list of {list(ABBR)}, got {closed!r}")

    window = e.get("window")
    if e.get("publish"):
        if window is None:
            errs.append(f"id {hid}: publish=true requires a window")
        else:
            errs += _window_problems(hid, "window", window)
    elif window is not None:
        errs += _window_problems(hid, "window", window)

    ov = e.get("overrides", {})
    if not isinstance(ov, dict):
        errs.append(f"id {hid}: overrides must be an object")
    else:
        for day, slot in ov.items():
            if day not in ABBR:
                errs.append(f"id {hid}: override day {day!r} not in {list(ABBR)}")
            if slot is not None:
                errs += _window_problems(hid, f"override {day}", slot)

    le = e.get("lastEntry")
    if le is not None and not (isinstance(le, str) and _TIME.match(le)):
        errs.append(f"id {hid}: lastEntry must be \"HH:MM\" or absent, got {le!r}")

    exc = e.get("exceptions", [])
    rule_kinds = []
    if not isinstance(exc, list):
        errs.append(f"id {hid}: exceptions must be a list")
    else:
        for i, x in enumerate(exc):
            if not (isinstance(x, dict) and set(x) - {"rule"} == {"en", "ja"}):
                errs.append(f"id {hid}: each exception must be {{en, ja}} (+ optional rule), got {x!r}")
                continue
            if not (str(x["en"]).strip() and str(x["ja"]).strip()):
                errs.append(f"id {hid}: exception en/ja must both be non-empty: {x!r}")
            if "rule" in x:
                errs += _rule_problems(hid, i, x["rule"])
                if isinstance(x["rule"], dict):
                    rule_kinds.append(x["rule"].get("kind"))

    # A published grid whose status implies a caveat must carry the matching
    # machine-readable rule — the caption alone is invisible to computing
    # consumers (the route planner), which would otherwise trust the grid.
    if e.get("publish"):
        if e.get("status") == "monthly" and not any(
                k in ("monthlyWeekday", "monthlyDay") for k in rule_kinds):
            errs.append(f"id {hid}: published monthly entry needs a monthlyWeekday/monthlyDay rule")
        if e.get("status") == "irregular" and "irregular" not in rule_kinds:
            errs.append(f"id {hid}: published irregular entry needs an {{\"kind\": \"irregular\"}} rule")
    return errs


def normalize_entry(hid: str, e: dict, old: dict | None) -> dict:
    """Return the entry with canonical key order, defaulting `note` from the old
    entry (or "") when the refreshed entry omits it. Assumes `e` already validated."""
    note = e.get("note", (old or {}).get("note", ""))
    merged = {**e, "note": note}
    return {k: merged[k] for k in ENTRY_KEYS if k in merged}


# --- subcommands --------------------------------------------------------------

def cmd_targets(args) -> int:
    cl = json.loads(Path(args.changelog).read_text(encoding="utf-8"))
    names = {h: v["name"] for h, v in snapshot_hours().items()}
    curated = load_curated()["onsens"]

    changed = [m for m in cl.get("modified", []) if "business_hours" in m.get("fields", {})]
    added = cl.get("added", [])
    removed = cl.get("removed", [])

    if args.json:
        json.dump({
            "changed": [{"hid": str(m["hid"]),
                         "old": m["fields"]["business_hours"]["old"],
                         "new": m["fields"]["business_hours"]["new"]} for m in changed],
            "added": [str(a["hid"]) for a in added],
            "removed": [str(r["hid"]) for r in removed],
        }, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"business_hours changed: {len(changed)} onsen(s)\n")
    for m in changed:
        hid = str(m["hid"])
        f = m["fields"]["business_hours"]
        flag = "" if hid in curated else "  [NO curated entry yet]"
        print(f"  hid {hid}  {names.get(hid, '')}{flag}")
        print(f"    old: {f['old']!r}")
        print(f"    new: {f['new']!r}")
    if added:
        print(f"\nadded (new onsens — scrape business_hours, then curate from scratch): "
              f"{', '.join(str(a['hid']) for a in added)}")
    if removed:
        print(f"removed (handle via isActive:false in the publisher; leave curated as-is): "
              f"{', '.join(str(r['hid']) for r in removed)}")
    print(f"\ntarget hids: {' '.join(str(m['hid']) for m in changed)}")
    return 0


def cmd_show(args) -> int:
    hids = [str(h) for h in args.hids]
    new_text = changelog_hours(args.changelog) if args.changelog else {}
    snap = snapshot_hours(hids)
    curated = load_curated()["onsens"]

    for hid in hids:
        s = snap.get(hid, {})
        # Prefer the freshly-scraped text from the changelog; fall back to snapshot.
        text = new_text.get(hid) if hid in new_text else s.get("business_hours")
        src = "changelog (new scrape)" if hid in new_text else "snapshot.db"
        print(f"================ hid {hid}  {s.get('name', '(unknown — not in snapshot)')} ================")
        print(f"business_hours [{src}]:")
        print(f"  {text!r}\n")
        if hid in curated:
            print("current curated entry:")
            print("  " + json.dumps(curated[hid], ensure_ascii=False, indent=2).replace("\n", "\n  "))
        else:
            print("current curated entry: (none — parse from scratch)")
        print()
    print("Re-parse each per docs/hours-schema.md (bilingual {en,ja} captions + rule twins; "
          "window/closed/overrides for the base week — window lists for split sessions; "
          "evidence-gated lastEntry; 第N曜→monthly, 不定休→irregular (grid + rule); "
          "never assert open from silence),")
    print("then merge with:  python recurate_hours.py set --file <refreshed.json>")
    return 0


def _read_payload(args) -> dict:
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.json:
        text = args.json
    else:
        text = sys.stdin.read()
    payload = json.loads(text)
    if args.hid is not None:
        return {str(args.hid): payload}     # a single bare entry → wrap by hid
    return {str(k): v for k, v in payload.items()}


def _entry_summary(hid: str, old, new) -> str:
    if old is None:
        return f"  + id {hid}: NEW  publish={new['publish']} status={new['status']}"
    bits = []
    for k in ("publish", "status", "window", "closed", "lastEntry", "confidence"):
        if old.get(k) != new.get(k):
            bits.append(f"{k} {old.get(k)!r}→{new.get(k)!r}")
    if old.get("exceptions") != new.get("exceptions"):
        bits.append(f"exceptions {len(old.get('exceptions', []))}→{len(new.get('exceptions', []))}")
    if old.get("overrides") != new.get("overrides"):
        bits.append("overrides changed")
    return f"  ~ id {hid}: {'; '.join(bits)}" if bits else f"  = id {hid}: unchanged"


def cmd_set(args) -> int:
    payload = _read_payload(args)
    errs = [msg for hid, e in payload.items() for msg in validate_entry(hid, e)]
    if errs:
        print("REFUSED — invalid entries, nothing written:", file=sys.stderr)
        print("\n".join(errs), file=sys.stderr)
        return 1

    doc = load_curated()
    onsens = doc["onsens"]
    lines = []
    for hid, e in payload.items():
        old = onsens.get(hid)
        new = normalize_entry(hid, e, old)
        lines.append(_entry_summary(hid, old, new))
        onsens[hid] = new

    print(f"merging {len(payload)} entr{'y' if len(payload) == 1 else 'ies'} into "
          f"{CURATED.relative_to(REPO_ROOT)}:")
    print("\n".join(sorted(lines)))
    if args.dry_run:
        print("\nDry-run — nothing written. Drop --dry-run to apply.")
        return 0
    write_curated(doc)
    print(f"\nwrote {CURATED.relative_to(REPO_ROOT)}. Next: run the test suite, then "
          f"dry-run the publisher (publisher/backfill_schedule.py --from-curated).")
    return 0


def cmd_validate(args) -> int:
    doc = load_curated()
    onsens = doc["onsens"]
    errs = [msg for hid, e in onsens.items() for msg in validate_entry(hid, e)]
    if errs:
        print(f"INVALID — {len(errs)} problem(s):")
        print("\n".join(errs))
        return 1
    print(f"OK — {len(onsens)} curated entries well-formed.")

    # Last-entry guard: any onsen whose source states a clean single 最終受付 cutoff
    # must surface it as a caption (docs/hours-schema.md), so a re-curation can't
    # silently re-bury a trip-critical fact. Per-bath/per-day cutoffs return None
    # from last_entry_caption and are curated by hand — not policed here.
    snap = snapshot_hours()
    le_missing = [
        hid for hid, e in onsens.items()
        if (cap := last_entry_caption(snap.get(hid, {}).get("business_hours"))) is not None
        and cap not in e.get("exceptions", [])
    ]
    if le_missing:
        print(f"MISSING last-entry caption — {len(le_missing)} onsen(s) state a "
              f"最終受付 the curated exceptions don't surface: {sorted(le_missing, key=int)}")
        print("  add it via recurate-hours `set` (en 'Last entry by HH:MM', ja '最終受付 HH:MM').")
        return 1
    print("  last-entry: every stated 最終受付 cutoff is surfaced as a caption.")

    # Structured-lastEntry evidence gate: businessHours.lastEntry may only state
    # what the source text states — never inferred (docs/hours-schema.md). An
    # entry's `lastEntry` must equal the mechanically-detected single 最終受付
    # cutoff. (Once the lastEntry backfill lands, this tightens to REQUIRE the
    # field wherever the cutoff is detectable.)
    le_bad = [
        hid for hid, e in onsens.items()
        if e.get("lastEntry") is not None
        and single_last_entry(snap.get(hid, {}).get("business_hours")) != e["lastEntry"]
    ]
    if le_bad:
        print(f"UNSUPPORTED lastEntry — {len(le_bad)} onsen(s) carry a structured "
              f"lastEntry the source text doesn't state: {sorted(le_bad, key=int)}")
        print("  lastEntry is evidence-based only; drop it or fix the time to match the source.")
        return 1

    # Coverage vs the snapshot is informational here (the pytest suite enforces an
    # exact match); a freshly-added onsen is expected to be missing until curated.
    snap_ids = set(snapshot_hours())
    missing = sorted(snap_ids - set(onsens), key=int)
    extra = sorted(set(onsens) - snap_ids, key=int)
    if missing:
        print(f"  note: {len(missing)} snapshot onsen(s) have no curated entry: {missing}")
    if extra:
        print(f"  note: {len(extra)} curated entr(ies) not in the snapshot: {extra}")
    if not missing and not extra:
        print(f"  coverage: exact match with the {len(snap_ids)} snapshot onsens.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("targets", help="list onsens whose business_hours changed (from a catalog-diff changelog)")
    p.add_argument("--changelog", required=True, type=Path, help="path to catalog-diff changelog.json")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_targets)

    p = sub.add_parser("show", help="dump source business_hours + current curated entry for given hids")
    p.add_argument("hids", nargs="+", help="onsen hids to show")
    p.add_argument("--changelog", type=Path, help="pull the NEW business_hours from this changelog (else snapshot.db)")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("set", help="merge refreshed curated entries into hours_curated.json (the write step)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--file", type=Path, help="JSON file: {hid: entry, ...} (or a bare entry with --hid)")
    src.add_argument("--json", help="inline JSON string")
    p.add_argument("--hid", help="treat the payload as ONE entry for this hid")
    p.add_argument("--dry-run", action="store_true", help="show the merge summary without writing")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("validate", help="re-check every curated entry against the schema invariants")
    p.set_defaults(func=cmd_validate)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
