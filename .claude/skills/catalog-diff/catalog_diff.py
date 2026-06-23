#!/usr/bin/env python3
"""
catalog-diff — read-only re-scrape + changelog for the 88onsen catalog.

Fetches the live detail pages, parses them, and diffs the result against a
baseline (the last good scrape snapshot by default). Writes changelog.json +
summary.md. Writes NOTHING to the canonical snapshot DB or to Firestore — the
output is a report a human acts on deliberately.

Usage:
  python catalog_diff.py --sample 10        # spot-check selectors, then stop
  python catalog_diff.py                     # full diff vs the snapshot baseline
  python catalog_diff.py --baseline catalog  # diff vs the published Firestore catalog
"""
import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# Make the repo root importable so `onsen_scraper` resolves regardless of CWD.
# This file lives at <repo>/.claude/skills/catalog-diff/catalog_diff.py.
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from onsen_scraper import FetchError, fetch_detail_page, parse_detail_page  # noqa: E402

# Detail-page fields the parser produces. name/areaName/lat/lng come from the
# map seed (not the detail page) — out of scope for this diff.
FIELDS = [
    "prefecture", "address", "phone", "business_hours", "admission_fee",
    "spring_quality", "website_url", "image_url", "access_info",
    "recommendation", "efficacy", "senjin_benefits", "covid_measures",
]
# Changes to these are surfaced loudly; everything else is "volatile" / low-signal.
MATERIAL = {
    "prefecture", "address", "phone", "business_hours",
    "admission_fee", "spring_quality", "website_url",
}
URL_FIELDS = {"website_url", "image_url"}
# Low-signal fields: real but rarely actionable (stale covid notes, rotating
# image filenames, committee blurbs). Tracked, but never drive "material"
# severity; shown collapsed in the report.
MUTED = {
    "image_url", "covid_measures", "efficacy",
    "recommendation", "senjin_benefits", "access_info",
}

DATA = REPO_ROOT / "data"
SNAPSHOT_DB = DATA / "snapshot.db"
ID_MAP = DATA / "onsen-id-map.json"

_WS = re.compile(r"[ \t]+")
_BLANK = re.compile(r"\n\s*\n+")
# Site-wide "as-of" date footers the source refreshes en masse — e.g.
# （2025.3現在） → 【2026年 4月現在】, (…時点), 【…以降】. These flip on ~every
# page without any substantive change, so strip them before comparing.
_ASOF = re.compile(r"[（(【\[][^（()）【】\[\]]*(?:現在|時点|以降)[^（()）【】\[\]]*[)）】\]]")


def norm(field: str, value, *, strip_dates: bool = True) -> str:
    """Normalize so cosmetic diffs (full-width chars, <br>, spacing, as-of date
    stamps) don't fire. strip_dates=False yields the raw (pre-destamp) form."""
    if value is None:
        return ""
    v = unicodedata.normalize("NFKC", str(value))  # 全角 → 半角 (１０：００ → 10:00)
    v = v.replace("\r\n", "\n").replace("<br>", "\n").replace("<br/>", "\n")
    if strip_dates:
        v = _ASOF.sub("", v)
    v = _BLANK.sub("\n", _WS.sub(" ", v)).strip()
    return v.rstrip("/").lower() if field in URL_FIELDS else v


def load_snapshot() -> dict[int, dict]:
    """{hid: {field: raw}} from the last good scrape — opened read-only."""
    db = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("SELECT * FROM onsens").fetchall()
    finally:
        db.close()
    cols = set(rows[0].keys()) if rows else set()
    return {r["id"]: {f: r[f] for f in FIELDS if f in cols} for r in rows}


def load_catalog() -> dict[int, dict]:
    """Published Firestore /onsens projected onto FIELDS, keyed by hid.

    TODO: authed REST read (mirror scripts/reseed-catalog.py in the app repo),
    then map kyuhachiId back to hid via onsen-id-map.json.
    """
    raise NotImplementedError("catalog baseline adapter not implemented yet")


def scrape_live(ids: list[int]) -> dict[int, dict | None]:
    """In-memory scrape. Never writes the canonical DB. None = fetch failed/gone."""
    out: dict[int, dict | None] = {}
    for hid in ids:
        try:
            parsed = parse_detail_page(fetch_detail_page(hid), hid)
            out[hid] = {f: parsed.get(f) for f in FIELDS}
        except FetchError:
            out[hid] = None
    return out


def diff(baseline: dict, live: dict, idmap: dict) -> dict:
    modified, removed, fetch_failed = [], [], []
    suppressed = 0  # onsens whose ONLY change was an as-of date-stamp refresh
    for hid, base in baseline.items():
        cur = live.get(hid)
        if cur is None:
            target = removed if hid in live else fetch_failed
            target.append({"hid": hid, "kyuhachiId": idmap.get(str(hid))})
            continue
        changed = {
            f: {"old": base.get(f), "new": cur.get(f)}
            for f in FIELDS
            if norm(f, base.get(f)) != norm(f, cur.get(f))
        }
        if changed:
            material = sorted(MATERIAL & changed.keys())
            modified.append({
                "hid": hid,
                "kyuhachiId": idmap.get(str(hid)),
                "severity": "material" if material else "volatile",
                "materialFields": material,
                "mutedFields": sorted(MUTED & changed.keys()),
                "fields": changed,
            })
        elif any(
            norm(f, base.get(f), strip_dates=False) != norm(f, cur.get(f), strip_dates=False)
            for f in FIELDS
        ):
            suppressed += 1
    # `added` is only meaningful once an index/listing crawl feeds in new ids.
    added = [{"hid": h} for h in live if h not in baseline]
    return {"modified": modified, "removed": removed, "fetchFailed": fetch_failed,
            "added": added, "suppressedDateStampOnly": suppressed}


def write_report(changelog: dict, label: str, outdir: Path) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    counts = {k: len(v) for k, v in changelog.items() if isinstance(v, list)}
    counts["suppressedDateStampOnly"] = changelog.get("suppressedDateStampOnly", 0)
    (outdir / "changelog.json").write_text(json.dumps({
        "scrapedAt": datetime.now(timezone.utc).isoformat(),
        "baseline": label,
        "counts": counts,
        **changelog,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    material = [m for m in changelog["modified"] if m["severity"] == "material"]
    volatile = [m for m in changelog["modified"] if m["severity"] == "volatile"]

    lines = [f"# Catalog diff vs {label}", "", "| change | n |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in counts.items()]
    lines += [f"| material movers | {len(material)} |",
              f"| low-signal only | {len(volatile)} |"]

    lines += ["", f"## Material changes ({len(material)})"]
    for m in material:
        lines.append(f"\n**hid {m['hid']}** ({m['kyuhachiId']})")
        lines += [f"- `{f}`: {m['fields'][f]['old']!r} → {m['fields'][f]['new']!r}"
                  for f in m["materialFields"]]
        if m["mutedFields"]:
            lines.append(f"- _(+{len(m['mutedFields'])} low-signal: {', '.join(m['mutedFields'])})_")

    if changelog["removed"]:
        lines += ["", "## Removed (live page 404s — mark isActive:false, do not delete)"]
        lines += [f"- hid {r['hid']} ({r['kyuhachiId']})" for r in changelog["removed"]]

    if volatile:
        lines += ["", f"## Low-signal only ({len(volatile)})",
                  "Only muted fields changed (image / covid / efficacy / "
                  "recommendation / benefits / access):",
                  "- " + ", ".join(f"hid {m['hid']}" for m in volatile)]

    (outdir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", choices=["snapshot", "catalog"], default="snapshot")
    ap.add_argument("--sample", type=int, help="spot-check N pages, then stop")
    ap.add_argument("--limit", type=int, help="diff only the first N ids")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "reports")
    args = ap.parse_args()

    idmap = json.loads(ID_MAP.read_text(encoding="utf-8"))
    baseline = load_snapshot() if args.baseline == "snapshot" else load_catalog()
    ids = sorted(baseline)

    if args.sample:  # preflight: are the selectors (and the egress allowlist) still good?
        sample = scrape_live(ids[:args.sample])
        ok = sum(1 for v in sample.values() if v and any(val for val in v.values()))
        verdict = "OK — selectors hold" if ok == args.sample \
            else "STOP — fix selectors / allowlist www.88onsen.com before a full run"
        print(f"sample {ok}/{args.sample} parsed ≥1 field — {verdict}")
        return

    if args.limit:
        ids = ids[:args.limit]
    changelog = diff(baseline, scrape_live(ids), idmap)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    counts = write_report(changelog, args.baseline, args.out / stamp)
    print(f"report → {args.out / stamp}\n{counts}")


if __name__ == "__main__":
    main()
