"""Read-only coverage report for the business-hours parser.

How many onsens in the snapshot parse to a structured weekly schedule vs. fall
back to raw, broken down by reason. Opens the snapshot DB read-only and writes
nothing (no DB, no Firestore) — a sanity check on the parse before any publish,
the same posture as the cost-analysis skill.

    python -m onsen_scraper.hours_report               # summary by reason
    python -m onsen_scraper.hours_report --show        # one line per onsen
    python -m onsen_scraper.hours_report --examples 3  # N sample strings/reason
"""
import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path

from onsen_scraper.hours import parse_hours

SNAPSHOT_DB = Path(__file__).resolve().parents[1] / "data" / "snapshot.db"

# Most-useful-first: structured buckets, then the raw-fallback reasons.
_ORDER = ["ok-open-all", "ok-weekday-closed", "no-closure-info",
          "irregular-closure", "multiple-windows", "partial-closure",
          "no-window", "empty"]


def _rows(db: Path):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(
            "select id, facility_name, business_hours from onsens order by id"
        ).fetchall()
    finally:
        con.close()


def report(show: bool = False, examples: int = 0, db: Path = SNAPSHOT_DB) -> None:
    rows = _rows(db)
    buckets: dict[str, list] = defaultdict(list)
    structured = 0
    for oid, name, bh in rows:
        p = parse_hours(bh)
        buckets[p.reason].append((oid, name, p))
        structured += p.schedule is not None
        if show:
            win = f"{p.window[0]}-{p.window[1]}" if p.window else "-"
            days = ",".join(d[:2] for d in p.closed_days) or "-"
            print(f"{oid:>4}  {p.reason:<17} win={win:<11} closed={days:<11} {name}")

    if show:
        print()
    total = len(rows)
    print(f"snapshot: {total} onsens — {structured} structured "
          f"({100 * structured / total:.0f}%), {total - structured} raw fallback\n")
    for reason in sorted(buckets, key=lambda r: _ORDER.index(r) if r in _ORDER else 99):
        items = buckets[reason]
        tag = "  (structured)" if reason.startswith("ok-") else ""
        print(f"  {reason:<18} {len(items):>3}{tag}")
        for oid, name, p in items[:examples]:
            first_line = (p.raw or "").splitlines()[0] if p.raw else ""
            print(f"        #{oid} {name}: {first_line[:50]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--show", action="store_true", help="print one line per onsen")
    ap.add_argument("--examples", type=int, default=0, metavar="N",
                    help="show N example source strings per reason bucket")
    args = ap.parse_args()
    report(show=args.show, examples=args.examples)


if __name__ == "__main__":
    main()
