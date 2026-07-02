#!/usr/bin/env python3
"""
catalog-sync — the deterministic backbone of the end-to-end onsen catalog update.

This is the driver the `catalog-sync` skill orchestrates. It owns the stages that
are pure mechanics; the judgement-heavy stages (LLM hours re-parse, identity
adjudication, approving live writes) stay with the operator/agent and the focused
sub-tools (`catalog-diff`, `recurate-hours`, `publisher/apply.py`,
`publisher/backfill_schedule.py`). One scrape feeds the whole run.

Stages:
  status   — offline snapshot of where things stand (baseline / id-map / curated
             coverage, pending staging). No network, no auth. Start here.
  sample   — preflight: scrape N detail pages, report parse health, stop. Catches
             a dead allowlist or DOM drift before a full run.
  detect   — ONE polite scrape of the source + the map seed, diffed against the
             snapshot baseline (reuses the catalog-diff engine). The seed (one
             fetch of /map) is the authoritative membership set → ADDED/REMOVED,
             and supplies the name/area/coords the detail page lacks. Writes the
             changelog report AND a staging scrape (data/snapshot.next.json,
             incl. the seed) for `promote`.
  mint     — assign a stable kyuhachiId (UUID) to new onsens in onsen-id-map.json.
             This repo solely owns id assignment. Gated by --commit.
  promote  — advance the (otherwise frozen) snapshot.db baseline from the staging
             scrape: UPDATE changed detail fields, fill name/area/coords from the
             seed, INSERT new onsens as COMPLETE rows, optionally --prune
             confirmed-removed rows. Run this LAST, after a successful publish, so
             the next `detect` diffs against reality. Gated by --commit.

What this driver deliberately does NOT do: write Firestore (that's the publisher
scripts, with their own --commit gate) and re-parse hours with a regex (that's the
session model via recurate-hours; the regex in onsen_scraper/hours.py is unreliable
on Japanese phrasing). promote/mint/status are pure stdlib + offline; only detect
and sample touch the network (they import the catalog-diff scraper lazily).

Usage:
  python catalog_sync.py status
  python catalog_sync.py sample --n 10
  python catalog_sync.py detect
  python catalog_sync.py mint --from-staging            # dry-run; add --commit
  python catalog_sync.py promote                        # dry-run; add --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# This file lives at <repo>/.claude/skills/catalog-sync/catalog_sync.py.
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = REPO_ROOT / "data"
SNAPSHOT_DB = DATA / "snapshot.db"
IDMAP_PATH = DATA / "onsen-id-map.json"
CURATED_PATH = DATA / "hours_curated.json"
STAGING_PATH = DATA / "snapshot.next.json"
CATALOG_DIFF_DIR = REPO_ROOT / ".claude" / "skills" / "catalog-diff"

# The detail-page fields the parser produces. Kept in sync with catalog_diff.FIELDS
# by test_detail_fields_match_catalog_diff so the two can't drift.
DETAIL_FIELDS = (
    "prefecture", "address", "phone", "business_hours", "admission_fee",
    "spring_quality", "website_url", "image_url", "access_info",
    "recommendation", "efficacy", "senjin_benefits", "covid_measures",
)
# snapshot columns the detail page CAN'T supply — sourced from the map seed
# (onsen_scraper.mapseed: name/areaName/lat/lng). `promote` fills these from the
# seed carried in the staging file, completing new rows and syncing coord drift.
SEED_COLS = ("facility_name", "onsen_area_name", "latitude", "longitude")
DETAIL_URL = "https://www.88onsen.com/spot/detail/hid/{id}"  # mirrors fetcher.DETAIL_URL_TEMPLATE


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# --- pure helpers (offline, unit-tested) --------------------------------------

def build_staging(scrape: dict, index_removed=()) -> dict:
    """Turn a catalog-diff `scrape_live` result into a promotable staging doc.

    `scrape` maps hid → parsed FIELDS (live), `{}` (served but no detail →
    soft-removed), or `None` (fetch failed). The staging doc carries the fresh
    detail fields for every onsen with content, plus the removal/failure sets so
    `promote` advances the baseline without a second scrape.
    """
    onsens, soft_removed, fetch_failed = {}, [], []
    for hid, v in scrape.items():
        if v is None:
            fetch_failed.append(int(hid))
        elif not v:                       # {} → soft-removed (HTTP 200, no detail)
            soft_removed.append(int(hid))
        else:
            onsens[str(hid)] = {f: v.get(f) for f in DETAIL_FIELDS}
    # Index membership is authoritative (mirrors catalog_diff.diff): a hid absent
    # from the source index is delisted even if its detail page still renders, so
    # drop it from the promotable set — we retire it, we don't refresh it.
    idx_removed = {int(h) for h in index_removed}
    for hid in idx_removed:
        onsens.pop(str(hid), None)
    removed = sorted(set(soft_removed) | idx_removed)
    return {"onsens": onsens, "removed": removed, "fetchFailed": sorted(fetch_failed)}


def promote_into_db(con: sqlite3.Connection, staging: dict, *, seed: dict | None = None,
                    prune: bool = False, now: str | None = None) -> dict:
    """Apply a staging scrape onto an open snapshot.db connection (no commit here —
    the caller commits or rolls back, which is how `promote` does its dry-run).

    Each onsen's row is recomputed from its existing row with the fresh detail
    fields overlaid, plus the map-seed columns (name/area/lat/lng) when the seed
    carries that hid — so existing rows gain coordinates / sync coord drift and a
    brand-new onsen lands as a COMPLETE row, not detail-only. UPDATEs rows that
    changed, INSERTs new onsens (+ derived URL + scraped_at), and — only with
    prune — DELETEs confirmed-removed rows. Idempotent (content-wise). Every hid
    present in `staging["onsens"]` gets scraped_at bumped to `now`, even when its
    managed fields are unchanged — landing in staging means it was freshly
    re-scraped and reconciled this cycle, which is itself a verification event,
    not just a content-change event. Returns per-action counts.

    `seed` defaults to staging["seed"] (written by `detect`); pass {} to skip.
    """
    now = now or _now()
    seed = staging.get("seed", {}) if seed is None else seed
    managed = [*DETAIL_FIELDS, *SEED_COLS]
    existing = {row[0]: dict(zip(managed, row[1:]))
                for row in con.execute(f"select id,{','.join(managed)} from onsens")}

    updated = inserted = unchanged = seeded = 0
    for hid_s, fields in staging.get("onsens", {}).items():
        hid = int(hid_s)
        # Start from the existing row so columns we don't manage this run survive,
        # then overlay fresh detail fields and (if present) the map-seed columns.
        new = dict(existing.get(hid) or {c: None for c in managed})
        for f in DETAIL_FIELDS:
            new[f] = fields.get(f)
        s = seed.get(hid_s)
        if s:
            seeded += 1
            new["facility_name"], new["onsen_area_name"] = s.get("name"), s.get("areaName")
            new["latitude"], new["longitude"] = s.get("lat"), s.get("lng")

        if hid in existing:
            if existing[hid] == new:
                unchanged += 1
                con.execute("update onsens set scraped_at=? where id=?", (now, hid))
                continue
            assigns = ",".join(f"{c}=?" for c in managed)
            con.execute(f"update onsens set {assigns},scraped_at=? where id=?",
                        [new[c] for c in managed] + [now, hid])
            updated += 1
        else:
            allcols = ["id", *managed, "detail_page_url", "scraped_at"]
            vals = [hid, *[new[c] for c in managed], DETAIL_URL.format(id=hid), now]
            con.execute(f"insert into onsens ({','.join(allcols)}) "
                        f"values ({','.join('?' * len(allcols))})", vals)
            inserted += 1

    pruned = 0
    if prune:
        for hid in staging.get("removed", []):
            cur = con.execute("delete from onsens where id=?", (int(hid),))
            pruned += cur.rowcount
    return {"updated": updated, "inserted": inserted, "unchanged": unchanged,
            "seeded": seeded, "pruned": pruned, "removedSeen": len(staging.get("removed", [])),
            "fetchFailed": len(staging.get("fetchFailed", []))}


def mint_ids(idmap: dict, hids, *, rng=uuid.uuid4) -> dict:
    """Return {hid: new-kyuhachiId} for hids not already in the id map. Pure — does
    not mutate `idmap` or touch disk."""
    return {str(h): str(rng()) for h in hids if str(h) not in idmap}


# --- file I/O -----------------------------------------------------------------

def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_idmap(idmap: dict) -> None:
    """Write onsen-id-map.json with the repo's exact format (2-space indent, no
    ASCII-escaping, numeric key order, trailing newline) — byte-stable round-trip."""
    ordered = {k: idmap[k] for k in sorted(idmap, key=int)}
    IDMAP_PATH.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")


def _snapshot_ids() -> set:
    con = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    try:
        return {r[0] for r in con.execute("select id from onsens")}
    finally:
        con.close()


# --- subcommands --------------------------------------------------------------

def cmd_status(args) -> int:
    snap = _snapshot_ids()
    idmap = _load_json(IDMAP_PATH)
    curated = _load_json(CURATED_PATH)["onsens"]
    print("catalog-sync status (offline)\n")
    print(f"  snapshot.db baseline : {len(snap)} onsens (ids {min(snap)}–{max(snap)})")
    print(f"  onsen-id-map.json    : {len(idmap)} hid→kyuhachiId")
    print(f"  hours_curated.json   : {len(curated)} curated entries")
    no_id = sorted((h for h in snap if str(h) not in idmap))
    no_cur = sorted((h for h in snap if str(h) not in curated))
    if no_id:
        print(f"  !! {len(no_id)} baseline onsen(s) without a kyuhachiId: {no_id}")
    if no_cur:
        print(f"  !! {len(no_cur)} baseline onsen(s) without a curated hours entry: {no_cur}")
    if not no_id and not no_cur:
        print("  coverage: id-map and curated hours both cover the baseline exactly.")
    if STAGING_PATH.exists():
        st = _load_json(STAGING_PATH)
        meta = st.get("_meta", {})
        print(f"\n  pending staging: {STAGING_PATH.relative_to(REPO_ROOT)} "
              f"(scraped {meta.get('scrapedAt', '?')}, {len(st.get('onsens', {}))} onsens, "
              f"{len(st.get('removed', []))} removed) — run `promote` after publishing.")
    else:
        print(f"\n  no pending staging — run `detect` to scrape + diff the source.")
    return 0


def _import_catalog_diff():
    """Import the catalog-diff engine (pulls the network stack). Only detect/sample
    need it, so it's imported lazily to keep promote/mint/status dependency-free."""
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(CATALOG_DIFF_DIR))
    import catalog_diff as cd  # noqa: E402
    return cd


def cmd_sample(args) -> int:
    cd = _import_catalog_diff()
    ids = sorted(cd.load_snapshot())[:args.n]
    sample = cd.scrape_live(ids)
    ok = sum(1 for v in sample.values() if v and any(val for val in v.values()))
    verdict = ("OK — selectors hold" if ok == len(ids)
               else "STOP — fix selectors / allowlist www.88onsen.com before a full run")
    print(f"sample {ok}/{len(ids)} parsed ≥1 field — {verdict}")
    return 0 if ok == len(ids) else 1


def cmd_detect(args) -> int:
    cd = _import_catalog_diff()
    from onsen_scraper import fetch_map_seed  # lazy (network)
    idmap = _load_json(IDMAP_PATH)
    baseline = cd.load_snapshot()

    # The map seed (one fetch) is the authoritative membership set AND supplies the
    # name/area/coords the detail page lacks. Absent from the seed = delisted.
    seed, seed_ids = {}, None
    try:
        seed = fetch_map_seed()
        seed_ids = set(seed)
        print(f"map seed: {len(seed)} listed; baseline {len(baseline)}; "
              f"+{len(seed_ids - set(baseline))} new / -{len(set(baseline) - seed_ids)} delisted")
    except Exception as e:  # noqa: BLE001 — any seed failure → degrade, don't crash
        print(f"!! map seed fetch failed ({e}); membership (ADD/REMOVE) disabled this run")

    ids = sorted(set(baseline) | (seed_ids or set()))
    if args.limit:
        ids = ids[:args.limit]

    scrape = cd.scrape_live(ids)
    changelog = cd.diff(baseline, scrape, idmap, index_ids=seed_ids)
    # Enrich ADDED onsens with the seed's name/area/coords so they're fully
    # identified (and ready for `mint` + the new-onsen publish path).
    for a in changelog.get("added", []):
        s = seed.get(int(a["hid"]))
        if s:
            a.update({"name": s["name"], "areaName": s["areaName"],
                      "lat": s["lat"], "lng": s["lng"]})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir = args.out / stamp
    counts = cd.write_report(changelog, "snapshot", outdir)

    index_removed = (set(baseline) - seed_ids) if seed_ids is not None else set()
    staging = build_staging(scrape, index_removed)
    if seed:
        staging["seed"] = {str(h): seed[h] for h in seed}
    staging["_meta"] = {"scrapedAt": _now(), "seed": bool(seed),
                        "reportDir": str(outdir.relative_to(REPO_ROOT))}
    STAGING_PATH.write_text(json.dumps(staging, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

    # Triage the operator needs to route the rest of the run.
    hours_changed = [m["hid"] for m in changelog["modified"]
                     if "business_hours" in m.get("fields", {})]
    material = [m for m in changelog["modified"] if m["severity"] == "material"]
    added = changelog.get("added", [])
    removed = [r["hid"] for r in changelog.get("removed", [])]
    new_ids = [a["hid"] for a in added if str(a["hid"]) not in idmap]

    print(f"\nreport → {outdir.relative_to(REPO_ROOT)}   {counts}")
    print(f"staging → {STAGING_PATH.relative_to(REPO_ROOT)} "
          f"({len(staging['onsens'])} onsens, {len(staging['removed'])} removed, "
          f"seed {len(seed)})\n")
    print("triage:")
    print(f"  material movers        : {len(material)}  → publisher/apply.py")
    print(f"  business_hours changed : {len(hours_changed)}  → recurate-hours  {hours_changed or ''}")
    print(f"  added (new onsens)     : {len(added)}  → mint + recurate-hours + apply.py add")
    for a in added:
        nm = f"  {a.get('areaName') or '?'}：{a.get('name') or '?'}" if a.get("name") else ""
        print(f"      hid {a['hid']}{nm}")
    if new_ids:
        print(f"      need a kyuhachiId: {new_ids}  → `catalog_sync.py mint --from-staging`")
    print(f"  removed / delisted     : {len(removed)}  → apply.py retire (isActive:false)  {removed or ''}")
    if changelog.get("fetchFailed"):
        print(f"  !! fetch failed        : {[f['hid'] for f in changelog['fetchFailed']]} — re-run detect")
    return 0


def cmd_mint(args) -> int:
    idmap = _load_json(IDMAP_PATH)
    if args.from_staging:
        if not STAGING_PATH.exists():
            raise SystemExit(f"no staging file at {STAGING_PATH} — run `detect` first")
        candidates = [h for h in _load_json(STAGING_PATH).get("onsens", {}) if h not in idmap]
    else:
        candidates = args.hids
    if not candidates:
        print("nothing to mint — every target hid already has a kyuhachiId.")
        return 0

    minted = mint_ids(idmap, candidates)
    already = [str(h) for h in candidates if str(h) in idmap]
    print(f"mint — {'COMMIT' if args.commit else 'DRY-RUN'}   "
          f"{len(minted)} new id(s), {len(already)} already mapped")
    for hid, kid in minted.items():
        print(f"  hid {hid:<5} → {kid}")
    if not minted:
        return 0
    if not args.commit:
        print("\nDry-run — onsen-id-map.json unchanged. Re-run with --commit to assign.")
        return 0
    idmap.update(minted)
    write_idmap(idmap)
    print(f"\nwrote {IDMAP_PATH.relative_to(REPO_ROOT)} (+{len(minted)}). "
          "Next for each: recurate-hours, then `apply.py add` to create the live doc "
          "(name/area/coords come from the map seed in staging).")
    return 0


def cmd_promote(args) -> int:
    staging_path = args.scrape or STAGING_PATH
    if not staging_path.exists():
        raise SystemExit(f"no staging file at {staging_path} — run `detect` first")
    staging = _load_json(staging_path)
    if not staging.get("onsens"):
        raise SystemExit(f"{staging_path} has no scraped onsens to promote")

    con = sqlite3.connect(SNAPSHOT_DB)  # read-write — the only writer of snapshot.db
    try:
        stats = promote_into_db(con, staging, prune=args.prune)
        if args.commit:
            con.commit()
        else:
            con.rollback()
    finally:
        con.close()

    mode = "COMMIT" if args.commit else "DRY-RUN"
    prune_note = "" if args.prune else f" (skipped {stats['removedSeen']} removed; pass --prune)"
    print(f"promote — {mode}   baseline {SNAPSHOT_DB.relative_to(REPO_ROOT)}")
    print(f"  update {stats['updated']}   insert {stats['inserted']}   "
          f"unchanged {stats['unchanged']}   seeded {stats['seeded']}   "
          f"prune {stats['pruned']}{prune_note}")
    if stats["fetchFailed"]:
        print(f"  note: {stats['fetchFailed']} hid(s) failed to fetch and were left untouched.")
    if not args.commit:
        print("\nDry-run — snapshot.db unchanged. Re-run with --commit to advance the baseline.")
    else:
        print("\nBaseline advanced. The next `detect` diffs against this scrape. "
              "(snapshot.db is git-tracked — revert with `git checkout` if needed.)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status", help="offline snapshot of baseline / id-map / curated coverage")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("sample", help="preflight: scrape N pages, report parse health, stop")
    p.add_argument("--n", type=int, default=10, help="pages to sample (default 10)")
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("detect", help="one scrape (+ map seed) → changelog report + staging scrape")
    p.add_argument("--limit", type=int, help="scrape only the first N ids (scoped run)")
    p.add_argument("--out", type=Path, default=REPO_ROOT / "reports", help="report output dir")
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("mint", help="assign kyuhachiId(s) to new onsens in onsen-id-map.json")
    p.add_argument("hids", nargs="*", help="hids to mint (or use --from-staging)")
    p.add_argument("--from-staging", action="store_true",
                   help="mint every staged onsen missing from the id map")
    p.add_argument("--commit", action="store_true", help="write onsen-id-map.json")
    p.set_defaults(func=cmd_mint)

    p = sub.add_parser("promote", help="advance snapshot.db from the staging scrape (run LAST)")
    p.add_argument("--scrape", type=Path, help=f"staging file (default {STAGING_PATH.name})")
    p.add_argument("--prune", action="store_true", help="also DELETE confirmed-removed rows")
    p.add_argument("--commit", action="store_true", help="write snapshot.db")
    p.set_defaults(func=cmd_promote)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
