---
name: catalog-diff
description: Re-scrape 88onsen.com and report what changed vs. the last catalog
  snapshot. Read-only — writes nothing to the snapshot DB or Firestore. Use to
  check whether the onsen catalog is up to date, or to produce a changelog
  before a reseed/backfill.
---

# catalog-diff

Read-only "what changed on the source" report. Reuses the scraper's fetcher +
parser (`onsen_scraper/`), scrapes into memory, and diffs against a baseline.
Never mutates the canonical snapshot DB (`data/snapshot.db`) or Firestore — the
output is a changelog the operator acts on deliberately.

## When to use

- "Has anything changed on 88onsen.com since the last scrape?"
- Before a reseed/backfill, to see the delta first instead of a blind overwrite.

## Steps

1. **Preflight — spot-check first.** Run from the repo root:
   `python .claude/skills/catalog-diff/catalog_diff.py --sample 10`
   - `www.88onsen.com` returns `403 Host not in allowlist` from sandboxed
     environments. If the sample fails to fetch, the host isn't allowlisted —
     stop and fix that before anything else.
   - If pages fetch but parse empty, the DOM drifted — fix selectors in
     `onsen_scraper/parser.py` BEFORE any full run.
2. **Full diff:** `python .claude/skills/catalog-diff/catalog_diff.py`
   (baseline = the last snapshot). Add `--baseline catalog` to diff against the
   live published catalog instead (adapter is a TODO — see below).
3. **Read `reports/<timestamp>/summary.md`.** Present the material changes;
   treat the volatile section (image filenames, covid notes, recommendation)
   as low-signal.
4. **Propose, don't apply.** Map changes to catalog updates, and `isActive:false`
   for removals (onsen docs are never deleted). The reseed/backfill is a
   separate, explicit step in the publish pipeline.

## Arguments

| Flag | Effect |
|---|---|
| `--sample N` | Scrape N pages, report parse health, then stop (preflight). |
| `--baseline snapshot\|catalog` | Baseline source. Default `snapshot`. |
| `--limit N` | Diff only the first N ids (scoped run). |
| `--out PATH` | Report output dir. Default `./reports/`. |

## Scope

- MVP detects **MODIFIED** + **REMOVED** over the known ids — reliable today.
- **ADDED** (brand-new onsens) needs an index/listing crawl plus a kyuhachiId
  assignment step; not implemented yet.
- The `catalog` baseline adapter (`load_catalog()`) is a TODO: authed REST read
  of `/onsens`, mapping kyuhachiId back to hid.

## Guarantees

- Read-only. Opens the snapshot DB `mode=ro`. No Firestore writes.
- Polite: inherits the fetcher's 1s delay / backoff / browser UA. Sample, don't
  hammer.
