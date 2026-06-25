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

> Part of the **`catalog-sync`** pipeline. For a full end-to-end update (detect →
> publish → retire/mint → advance the baseline), start at `catalog-sync` — it wraps
> this detection step (`catalog_sync.py detect`) and routes the rest. Use this skill
> directly when you only want a read-only "what changed?" report.

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
   (baseline = the last snapshot). Add **`--discover`** to crawl the source index
   first — this detects **ADDED** onsens and uses index membership as the
   authoritative **REMOVED** signal. Add `--baseline catalog` to diff against the
   live published catalog instead (adapter is a TODO — see below).
3. **Read `reports/<timestamp>/summary.md`.** Present the material changes;
   treat the low-signal section (image filenames, covid notes, recommendation)
   as noise.
4. **Hand to the publisher (propose, don't auto-apply).** Scaffold a decisions
   file from the changelog, review it, then apply:
   `python publisher/apply.py --from-changelog reports/<ts>/changelog.json --out decisions.json`
   → edit each `action` (`update`/`retire`/`skip`) → dry-run → `--commit`.
   Removals → `isActive:false` (onsen docs are never deleted). New onsens need a
   `kyuhachiId` assigned first (the publisher won't add them automatically).

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
| `--discover` | Crawl the source index first → detect ADDED + authoritative REMOVED. |
| `--baseline snapshot\|catalog` | Baseline source. Default `snapshot`. |
| `--limit N` | Diff only the first N ids (scoped run). |
| `--out PATH` | Report output dir. Default `./reports/`. |

## Scope

- Detects **MODIFIED**, **REMOVED**, and (with `--discover`) **ADDED**.
- **REMOVED** fires on: an **empty detail page** (the source soft-removes with
  HTTP 200 + generic chrome, not a 404, so every material field parses empty —
  see `is_soft_removed`), or — with `--discover` — **absence from the source
  index** (authoritative). Both surface as retire/`isActive:false` candidates,
  never as an "update everything to null" modification. A genuine **fetch
  error** is reported separately under **fetch failed** (re-run before
  deciding), not treated as a removal.
- **ADDED** requires `--discover`. New onsens are reported with prefecture +
  address; assigning their `kyuhachiId` is a manual step (this repo owns ids).
- The `catalog` baseline adapter (`load_catalog()`) is still a TODO: authed REST
  read of `/onsens`, mapping kyuhachiId back to hid.

## Guarantees

- Read-only. Opens the snapshot DB `mode=ro`. No Firestore writes.
- Polite: inherits the fetcher's 1s delay / backoff / browser UA. Sample, don't
  hammer.
