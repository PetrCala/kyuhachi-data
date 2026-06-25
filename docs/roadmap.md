# kyuhachi-data — Roadmap

_Audit snapshot: 2026-06-23. This repo owns the onsen catalog source of truth: scraping 88onsen.com, maintaining stable `kyuhachiId`s, and publishing the catalog to Firestore (`kyuhachi-fddcc`). The app lives in the separate `kyuhachi` repo and only reads the published catalog._

## Current state

All five PRs to date are merged to `master`; no open PRs.

| PR | What landed |
|---|---|
| #1 | `catalog-diff` hardening — `norm()` strips site-wide "as-of" date stamps; MATERIAL vs MUTED field tiers; per-onsen material/muted split + `suppressedDateStampOnly`. |
| #2 | `cost-analysis` skill — read-only 88-cost estimator (Monte Carlo + cheapest/priciest bounds). |
| #3 | Surgical merge-based publisher (`publisher/apply.py`) — MERGE-PATCH only named fields, `retire`→`isActive:false`, never deletes, dry-run by default. |
| #4 | Shared adult-fee parser (`onsen_scraper/fees.py`) + one-time `adultFee` backfill (`publisher/backfill_fees.py`); fetcher/parser made lazy so `fees` needs no network stack. |
| #5 | Publish-time `adultFee` recompute hook in `apply.py` `build_update()` + 30s timeout/retry on the Firestore REST helpers. |

Data: `data/snapshot.db` = 148 onsens; `data/onsen-id-map.json` = 148 `hid`→`kyuhachiId`. Live catalog at `catalog_meta` v2 with `admissionFee` (text) + `adultFee` (numeric yen) per onsen.

**In-flight (not on origin):** `feat/catalog-pipeline` is being developed in the primary local checkout (uncommitted, not pushed). It refactors `apply.py` from a hardcoded `DECISIONS` list into a **changelog-driven** flow: `--from-changelog` scaffolds a `decisions.json` from a catalog-diff `changelog.json`, then `--decisions <file> [--commit]`, adding a `skip` action. Treat anything touching `publisher/apply.py` as colliding with it.

## Remaining roadmap

### A. Soft-removal detection in `catalog-diff` — Small; no collision; high leverage
REMOVED only fires on `FetchError`. A delisted onsen (e.g. hid 248) returns HTTP 200 + page chrome with an empty detail table → parses all-None → surfaces as a spurious "material modification" instead of REMOVED. Fix: detect the empty/delisted parse and route it to `removed`. Why it matters: it's an active correctness bug whose output feeds the changelog the changelog-driven publisher consumes. Risk: false positives on legitimately sparse pages — keep the predicate conservative.

### B. `catalog` baseline adapter (diff vs live Firestore) — Medium; no `apply.py` collision; synergistic
`load_catalog()` is `raise NotImplementedError`. Scope: authed REST read of `/onsens` (paginated), decode Firestore typed values, project onto `FIELDS`, map `kyuhachiId`→`hid`. Why it matters: lets the diff run against published truth, not just the drifting local snapshot; closes the live-diff → decisions → publish loop with `feat/catalog-pipeline`. Risk: field-shape mismatch (camelCase + nested `businessHours.raw` vs parser snake_case).

### C. Index/listing crawl → ADDED detection + `kyuhachiId` assignment — Large; downstream of `feat/catalog-pipeline`; higher risk
`diff()` computes `added` but it's only meaningful once a listing crawl feeds in new ids; today the pipeline is blind to brand-new onsens (MODIFIED/REMOVED over the 148 known hids only). Scope: crawl the listing/map seed, discover new hids, mint UUID `kyuhachiId`s, write `onsen-id-map.json`. Why it matters: the single biggest functional gap — the catalog can't grow without it; prerequisite for the publisher's `add` action. Risk: writes the irreversible id-map — needs idempotency + a human gate.

### D. DRY the Firestore REST helpers into `publisher/firestore_rest.py` — Small; COLLIDES with `feat/catalog-pipeline`
`token`/`_open`/`patch`/`ival` are duplicated across `apply.py` and `backfill_fees.py` (plus `sval` / `get_fields`). Mechanical extraction, low-risk — but it touches `apply.py`, which `feat/catalog-pipeline` is rewriting. Do it immediately AFTER that branch lands.

### E. Versioned-publisher maturation (the `add` action + full-publish path) — Medium; largely == `feat/catalog-pipeline`
`apply.py` is the genesis; `feat/catalog-pipeline` is the changelog-driven maturation. Remaining after it merges: an `add` action for new onsens (blocked on C — no `kyuhachiId` to add a doc), and eventually a full scrape→snapshot→Firestore versioned publish. Don't duplicate the in-flight branch.

### F. `営業時間` → `WeeklySchedule` adapter — Medium; mostly independent; app-facing
**Parser landed** (`onsen_scraper/hours.py` + `tests/test_hours.py` + read-only `hours_report`): `parse_hours()` / `parsed_hours_doc()` project a single-window + explicit `無休`/weekday closure onto the app's `ParsedHours` shape (null day = closed), falling back to `raw` otherwise. Coverage on the snapshot: **56/148 structured** (20 open-all, 36 weekday-closed); the rest are genuinely irregular (`不定休`/`第N曜休`/multi-window) and stay raw. It deliberately does **not** infer "open daily" from a missing closed day — that gap is the official-site cross-check, not this adapter.
**Publish wiring landed** too: `apply.py` `build_update()` now recomputes `businessHours.schedule` from `parsed_hours_doc()` whenever the hours text changes (parallels the `adultFee` hook), and `publisher/backfill_schedule.py` is the one-time fill (offline dry-run; writes 56/148 structured schedules — 20 open-all + 36 weekday-closed — skips raw-only). Policy per owner: `無休`/no-closed-day → open every day per window; no hours text at all → 24/7; hours-present-but-unparseable → `raw` only.
Remaining: **app side** (separate repo): the current `WeeklySchedule` can't hold holiday-exception notes, split windows, or Nth-weekday closures — those survive only in `raw`; richer rendering would need a type extension. The app already renders `businessHours.schedule` (collapsed "Show weekly hours" grid, null day = "Closed"), so the backfill lights it up with no app change — but that render path has never run live, so smoke-test one onsen first. Risk: Japanese hours text is highly irregular — keep the raw fallback dominant.

### G. Live re-publish smoke test of `apply.py` — Operational; BLOCKED on environment
The `adultFee` publish hook's fetch→derive→PATCH path has never run live — 88onsen.com 403s from sandboxes. Needs one run from an allowlisted environment before the next real publish. A release gate, not a coding item.

### Cross-cutting
- Tests are `tests/test_fees.py` only (12 cases); no tests for `catalog_diff` / `apply` / `backfill`, and there's no CI (`.github/workflows`). New work in A/D should ship with tests.
- Cross-repo: the numeric `adultFee` is inert until the **app repo** adds `adultFee` to `OnsenDocument` + the Phase-4 Stats budget card.

## Recommended order

1. **A — soft-removal detection.** Small, zero collision with `feat/catalog-pipeline`, fixes a verified correctness bug whose output feeds the changelog-driven publisher. Best leverage-to-effort.
2. **B — `catalog` baseline adapter.** Independent of `apply.py`; gives the diff a real baseline and sets up the live-diff → publish loop.
3. **D — extract `publisher/firestore_rest.py`** — but only AFTER `feat/catalog-pipeline` merges (else guaranteed `apply.py` conflict).
4. **C — index crawl + ADDED + `kyuhachiId` assignment**, then the publisher `add` action (part of E). Biggest functional gap, but largest/highest-risk and downstream of the in-flight branch.
5. **F — `WeeklySchedule` adapter.** Nice enrichment; needs the app-repo type; raw fallback works today.
- **G (live smoke test):** do opportunistically from an allowlisted env; it's a release gate.

**Collision flags:** D and E touch `apply.py` → do them after `feat/catalog-pipeline` lands. A and B don't touch `apply.py` and both improve the changelog/baseline that branch consumes → safe to start in parallel. C's `add` action is downstream of it.
