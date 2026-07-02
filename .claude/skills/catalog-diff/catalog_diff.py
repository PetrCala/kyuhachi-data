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

# Make the repo root (for `onsen_scraper`) and the publisher dir (for the shared
# Firestore REST helpers) importable regardless of CWD. This file lives at
# <repo>/.claude/skills/catalog-diff/catalog_diff.py.
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "publisher"))

from onsen_scraper import FetchError, fetch_detail_page, fetch_url, parse_detail_page  # noqa: E402

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

# Published-catalog projection: snake_case parser field → live-doc field path.
# Only the source-authored fields the catalog actually publishes — every one of
# them MATERIAL. The muted descriptive fields (covid/efficacy/recommendation/…)
# are not published, and `imageUrl` is a *rehosted* Storage URL, not the source
# `image_url`, so neither is diffable against a scrape. The catalog baseline
# therefore compares published truth on these fields alone (see `load_catalog`).
CATALOG_FIELD_PATH = {
    "prefecture": "prefecture",
    "address": "address",
    "phone": "phone",
    "business_hours": "businessHours.raw",
    "admission_fee": "admissionFee",
    "spring_quality": "springQuality",
    "website_url": "websiteUrl",
}
CATALOG_FIELDS = list(CATALOG_FIELD_PATH)

DATA = REPO_ROOT / "data"
SNAPSHOT_DB = DATA / "snapshot.db"
ID_MAP = DATA / "onsen-id-map.json"

# Source listing index — the authoritative set of currently-listed onsens.
# Paginated 10/page: /spot/index/mode/paging/page/{n}/t//category/
INDEX_URL = "https://www.88onsen.com/spot/index/mode/paging/page/{n}/t//category/"
_HID_RE = re.compile(r"/spot/detail/hid/(\d+)")
_PAGE_RE = re.compile(r"/spot/index/mode/paging/page/(\d+)/")

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
    """Published Firestore /onsens projected onto CATALOG_FIELDS, keyed by hid.

    Read-only: an authed, paginated REST list of the /onsens collection (via the
    shared publisher/firestore_rest helpers), decoding each doc's typed values at
    the mapped camelCase paths back into the parser's snake_case field names, and
    inverting onsen-id-map.json (kyuhachiId → hid) so the result keys line up with
    load_snapshot(). Live docs whose kyuhachiId isn't in the id map are skipped —
    they can't be tied back to a scrapeable hid. Writes nothing (locked contract).

    Auth: gcloud Application Default Credentials (same token the publisher mints).
    """
    from firestore_rest import fetch_collection, field_at, token  # local: needs auth + network

    idmap = json.loads(ID_MAP.read_text(encoding="utf-8"))
    kid_to_hid = {kid: int(hid) for hid, kid in idmap.items()}
    out: dict[int, dict] = {}
    for kid, fields in fetch_collection("onsens", token()).items():
        hid = kid_to_hid.get(kid)
        if hid is None:
            continue
        out[hid] = {f: field_at(fields, path) for f, path in CATALOG_FIELD_PATH.items()}
    return out


def is_soft_removed(parsed: dict) -> bool:
    """True for a delisted ("soft-removed") page: fetched HTTP-200 fine but carries
    no detail at all.

    A delisted onsen (real example: hid 248, 神の湯 / 紫尾温泉) still returns 200
    with the normal site chrome, so the fetcher passes it through, but its
    `#spot_detail dl.tableview` table is gone — `parse_detail_page` then yields
    all-None. Without this check that page reads as a wholesale "every populated
    field → None" *material modification* instead of a *removal*.

    Conservative on purpose: a genuine onsen always carries at least one MATERIAL
    detail (address / business_hours / admission_fee / spring_quality / …). We
    treat a page as gone only when EVERY material field is None/empty, so a merely
    sparse-but-live page is never mistaken for a delisting.
    """
    return all(norm(f, parsed.get(f)) == "" for f in MATERIAL)


def scrape_live(ids: list[int]) -> dict[int, dict | None]:
    """In-memory scrape. Never writes the canonical DB. Per id, returns one of:
      None  — fetch failed (network / non-200 after retries); retry or inspect.
      {}    — page served (HTTP 200) but carries no onsen detail. The source
              soft-removes by serving generic chrome, not a 404, so an all-empty
              MATERIAL parse means delisted, not a content change (see
              `is_soft_removed`) → a removal candidate.
      {..}  — the parsed FIELDS.
    """
    out: dict[int, dict | None] = {}
    for hid in ids:
        try:
            html = fetch_detail_page(hid)
        except FetchError:
            out[hid] = None
            continue
        parsed = parse_detail_page(html, hid)
        fields = {f: parsed.get(f) for f in FIELDS}
        out[hid] = {} if is_soft_removed(fields) else fields
    return out


def crawl_index(hard_cap: int = 60) -> set[int]:
    """Return the set of hids currently listed on the source index — the
    authoritative membership set. Follows pagination (polite, via fetch_url).
    Network: needs egress to www.88onsen.com."""
    ids: set[int] = set()
    last_hint, n = 1, 1
    while n <= hard_cap:
        html = fetch_url(INDEX_URL.format(n=n))
        if n == 1:
            last_hint = max((int(m) for m in _PAGE_RE.findall(html)), default=1)
        page_ids = {int(x) for x in _HID_RE.findall(html)}
        if not page_ids:                       # empty listing page → past the end
            break
        new = page_ids - ids
        ids |= page_ids
        if n >= last_hint and not new:         # past hinted end, nothing new → stop
            break
        n += 1
    return ids


def diff(baseline: dict, live: dict, idmap: dict, index_ids: set[int] | None = None,
         fields: list[str] = FIELDS) -> dict:
    """Diff a baseline against a live scrape over `fields`. `fields` narrows the
    comparison for the catalog baseline (CATALOG_FIELDS — only the published
    fields), so muted descriptive fields the catalog never stores don't fire as
    spurious volatile changes; it defaults to the full FIELDS for the snapshot."""
    modified, removed, fetch_failed = [], [], []
    suppressed = 0  # onsens whose ONLY change was an as-of date-stamp refresh
    for hid, base in baseline.items():
        cur = live.get(hid)
        ref = {"hid": hid, "kyuhachiId": idmap.get(str(hid))}
        if index_ids is not None and hid not in index_ids:  # authoritative delist
            removed.append({**ref, "reason": "not on source index"})
            continue
        if cur is None:          # couldn't fetch — not a clean removal signal
            fetch_failed.append(ref)
            continue
        if not cur:              # {} → served (HTTP 200) but no detail → delisted
            removed.append({**ref, "reason": "empty detail page"})
            continue
        changed = {
            f: {"old": base.get(f), "new": cur.get(f)}
            for f in fields
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
            for f in fields
        ):
            suppressed += 1
    # `added` = ids on the source (live) but not in baseline, with real content.
    # New onsens have no kyuhachiId yet — surface prefecture/address to identify them.
    added = [{"hid": h, "kyuhachiId": idmap.get(str(h)),
              "prefecture": live[h].get("prefecture"), "address": live[h].get("address")}
             for h in live if h not in baseline and live[h]]
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

    if changelog.get("added"):
        lines += ["", f"## Added — NEW onsens ({len(changelog['added'])})",
                  "Listed on the source but not in baseline. Assign a kyuhachiId, "
                  "then add to the relevant challenge_types pool:"]
        lines += [f"- hid {a['hid']}  {a.get('prefecture') or '?'}  {a.get('address') or ''}".rstrip()
                  for a in changelog["added"]]

    if changelog["removed"]:
        lines += ["", "## Removed (404 / HTTP-200 empty / off the source index — "
                  "mark isActive:false, do not delete)"]
        lines += [f"- hid {r['hid']} ({r['kyuhachiId']})  — {r.get('reason', 'removed')}"
                  for r in changelog["removed"]]

    if changelog.get("fetchFailed"):
        lines += ["", f"## Fetch failed ({len(changelog['fetchFailed'])}) — re-run before deciding",
                  "- " + ", ".join(f"hid {r['hid']}" for r in changelog["fetchFailed"])]

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
    ap.add_argument("--discover", action="store_true",
                    help="crawl the source index first: detect ADDED onsens and use index "
                         "membership as the authoritative REMOVED signal")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "reports")
    args = ap.parse_args()

    idmap = json.loads(ID_MAP.read_text(encoding="utf-8"))
    if args.baseline == "catalog":
        baseline, compare_fields = load_catalog(), CATALOG_FIELDS
    else:
        baseline, compare_fields = load_snapshot(), FIELDS
    ids = sorted(baseline)

    if args.sample:  # preflight: are the selectors (and the egress allowlist) still good?
        sample = scrape_live(ids[:args.sample])
        ok = sum(1 for v in sample.values() if v and any(val for val in v.values()))
        verdict = "OK — selectors hold" if ok == args.sample \
            else "STOP — fix selectors / allowlist www.88onsen.com before a full run"
        print(f"sample {ok}/{args.sample} parsed ≥1 field — {verdict}")
        return

    index_ids = None
    if args.discover:
        index_ids = crawl_index()
        # Scrape the union: index ids (for field diffs + ADDED content) plus any
        # baseline ids still listed. Baseline ids absent from the index are flagged
        # REMOVED by membership without needing a fetch.
        ids = sorted(index_ids | set(baseline))
        print(f"index: {len(index_ids)} listed; baseline {len(baseline)}; "
              f"+{len(index_ids - set(baseline))} new / -{len(set(baseline) - index_ids)} delisted")

    if args.limit:
        ids = ids[:args.limit]
    changelog = diff(baseline, scrape_live(ids), idmap, index_ids=index_ids, fields=compare_fields)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    counts = write_report(changelog, args.baseline, args.out / stamp)
    print(f"report → {args.out / stamp}\n{counts}")


if __name__ == "__main__":
    main()
