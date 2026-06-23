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

## Normalization (low-noise diffs)

Before comparing, both sides are NFKC-folded (full-width → half-width),
whitespace/`<br>` collapsed, and the source's site-wide **"as-of" date footer**
(`（2025.3現在）` → `【2026年 4月現在】`) is stripped — that stamp alone flips on
~100% of pages with no real change. Fields split into:

- **material** — `prefecture, address, phone, business_hours, admission_fee,
  spring_quality, website_url`: drive the headline, shown with old → new.
- **muted** — `image_url, covid_measures, efficacy, recommendation,
  senjin_benefits, access_info`: tracked but low-signal (stale notes, rotating
  filenames); shown collapsed.

The report separates **material movers**, **low-signal only**, and
**suppressedDateStampOnly** (changes that were nothing but a refreshed stamp).
An onsen with ≥4 changed material fields is likely a replaced/relocated facility
— **adjudicate identity** (update in place vs. retire + mint a new kyuhachiId)
rather than blind-overwriting, since the upstream `hid` can be reused.

## Arguments

| Flag | Effect |
|---|---|
| `--sample N` | Scrape N pages, report parse health, then stop (preflight). |
| `--baseline snapshot\|catalog` | Baseline source. Default `snapshot`. |
| `--limit N` | Diff only the first N ids (scoped run). |
| `--out PATH` | Report output dir. Default `./reports/`. |

## Scope

- MVP detects **MODIFIED** + **REMOVED** over the known ids — reliable today.
  REMOVED covers both a hard 404 and a **soft delisting** — an HTTP-200 page that
  still serves the site chrome but has dropped its detail table (every material
  field parses empty). Both surface as retire/`isActive:false` candidates, never
  as an "update everything to null" modification.
- **ADDED** (brand-new onsens) needs an index/listing crawl plus a kyuhachiId
  assignment step; not implemented yet.
- The `catalog` baseline adapter (`load_catalog()`) is a TODO: authed REST read
  of `/onsens`, mapping kyuhachiId back to hid.

## Guarantees

- Read-only. Opens the snapshot DB `mode=ro`. No Firestore writes.
- Polite: inherits the fetcher's 1s delay / backoff / browser UA. Sample, don't
  hammer.
