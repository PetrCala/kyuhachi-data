# kyuhachi-data — Roadmap

_Audit snapshot: 2026-06-25. This repo owns the onsen catalog source of truth: scraping 88onsen.com, maintaining stable `kyuhachiId`s, and publishing the catalog to Firestore (`kyuhachi-fddcc`). The app lives in the separate `kyuhachi` repo and only reads the published catalog._

## Current state

The end-to-end update loop now exists and is orchestrated by the **`catalog-sync`** skill
(`detect → publish → retire/mint → promote`). All work below is merged to `master`; no open
PRs. The previously in-flight `feat/catalog-pipeline` branch (changelog-driven `apply.py`)
has landed.

What's in place:

| Capability | Where it lives |
|---|---|
| Polite scraper (fetcher + parser → 13 raw fields), diff baseline, id map | `onsen_scraper/`, `data/snapshot.db`, `data/onsen-id-map.json` |
| Read-only drift report (MODIFIED / REMOVED, MATERIAL vs MUTED tiers, date-stamp suppression) | `.claude/skills/catalog-diff/` |
| **Soft-removal detection** — a delisted onsen serves HTTP 200 + empty detail table; `is_soft_removed()` routes it to REMOVED instead of a spurious "material modification" | `catalog_diff.py` + `tests/test_catalog_diff_soft_removal.py` |
| **ADDED detection + membership from the map seed** — one `/map` fetch is the authoritative membership set and supplies name/area/lat/lng the detail page lacks | `onsen_scraper/mapseed.py`, `catalog-sync detect --discover` |
| **`kyuhachiId` assignment for new onsens** — mints UUIDs, writes `onsen-id-map.json` (human-gated) | `catalog-sync mint` |
| **New-onsen name + coordinates** baselined as complete rows | `catalog-sync promote` (overlays the map-seed columns) |
| Surgical, changelog-driven publisher — `--from-changelog` scaffolds `decisions.json`; `--decisions [--commit]` MERGE-PATCHes only named fields; `update` / `retire` (→ `isActive:false`) / `skip`; never deletes, dry-run by default | `publisher/apply.py` |
| **Shared Firestore REST helpers** — `token` / `_open` / `patch` / `get_fields` / `sval` / `ival` / `dval` / `bval` / `create` / `bump_catalog_version` extracted once, no longer copy-pasted across `apply.py` + the four `backfill_*.py` scripts | `publisher/firestore_rest.py` |
| Numeric `adultFee` — shared parser + publish-time recompute hook + one-time backfill | `onsen_scraper/fees.py`, `apply.py` `build_update()`, `publisher/backfill_fees.py` |
| `営業時間` → `WeeklySchedule` — LLM-curated `data/hours_curated.json` is the source of truth; `backfill_schedule.py --from-curated` owns the published `businessHours.schedule` + `exceptions` + `confidence`; `recurate-hours` skill refreshes drifted hours | `onsen_scraper/hours.py`, `publisher/backfill_schedule.py`, `.claude/skills/recurate-hours/` |
| Generated `nameKana` (hiragana reading, gojūon sort key) — auto + curated corrections overlay (`data/readings_curated.json`, evidence per entry); consumed by app PR kyuhachi#143 | `onsen_scraper/readings.py`, `publisher/backfill_name_kana.py` |
| Generated `nameRomaji` (Hepburn, proper-noun-cased) — display-only pronunciation aid for non-JP users; auto + curated overlay (restores Latin loanwords, e.g. サムソンホテル → "Samson Hotel"); consumed by app PR kyuhachi#183 | `onsen_scraper/readings.py`, `publisher/backfill_name_romaji.py` |
| **Baseline advance after publish** — `snapshot.db` is no longer frozen | `catalog-sync promote` |
| **GitHub-native automation** — monthly `catalog-detect` cron → `catalog-drift` issue → human-prepared `catalog-publish` PR → `catalog-dry-run` posts the live Firestore diff → merge gates the write behind a `production` environment approval | `.github/workflows/{catalog-detect,catalog-dry-run,catalog-publish}.yml`, `.github/CATALOG_AUTOMATION.md` |
| Cost estimator (read-only admission-fee Monte Carlo + bounds) | `.claude/skills/cost-analysis/` |

Data: `data/snapshot.db` = 161 onsens (raw fields + `raw_html`); `data/onsen-id-map.json` =
161 `hid`→`kyuhachiId`. Live catalog carries `admissionFee` (text) + `adultFee` (numeric yen),
`businessHours.schedule`, `nameKana`, and `nameRomaji` per onsen.

Tests: **112 passing** across nine files — `test_fees.py` (12), `test_hours.py` (20),
`test_catalog_sync.py` (11), `test_catalog_diff_soft_removal.py` (14),
`test_publish_schedule.py` (14), `test_apply_add.py` (5), `test_image_processor.py` (10),
`test_readings.py` (21), `test_firestore_rest.py` (5). Run with `pytest -q` (needs Python
≥3.12 and the `dev` extra: `pip install -e '.[dev]'`).

## Remaining roadmap

### A. ✅ Shipped — `apply.py` `add` action — create the live Firestore doc for a new onsen
`ACTIONS = ("update", "retire", "skip", "add")`. A `{"action":"add"}` decision builds the full
`OnsenDocument` from the /map seed (name/areaName/lat/lng) + a live detail scrape (the descriptive
fields) + the curated hours (the weekly grid, never the regex) + a derived `adultFee` + generated
`nameKana`/`nameRomaji` + a rehosted photo, then **creates** `/onsens/{kyuhachiId}`. It's the sole create (vs
PATCH) write: idempotent (skips if the doc already exists), gated behind the `production` approval,
and guarded by a key-set check against the app's `OnsenDocument` contract (plus a live-doc drift
warning) before any write. Challenge-pool membership still lives in the app repo, and the live doc
itself only appears once the gated `catalog-publish` run is approved.

### B. `catalog` baseline adapter (diff vs live Firestore) — Medium; independent
`load_catalog()` is still `raise NotImplementedError`, so the diff can only run against the
local `snapshot.db`, not published truth. Scope: authed REST read of `/onsens` (paginated),
decode Firestore typed values, project onto `FIELDS`, map `kyuhachiId`→`hid`. Why it matters:
lets the diff catch drift between the snapshot and what's actually live. Risk: field-shape
mismatch (camelCase + nested `businessHours.raw` vs the parser's snake_case).

### C. ✅ Shipped — DRY the Firestore REST helpers into `publisher/firestore_rest.py`
`token` / `_open` / `patch` / `get_fields` / `sval` / `ival` / `dval` / `bval` / `create` /
`bump_catalog_version` were copy-pasted across `apply.py`, `backfill_fees.py`,
`backfill_name_kana.py`, `backfill_name_romaji.py`, and `backfill_schedule.py`. Extracted into
`publisher/firestore_rest.py`; every script now imports the shared copy instead of
redefining it. Mechanical — no behavior change, every script's CLI and dry-run/`--commit`
semantics are identical. `tests/test_firestore_rest.py` covers the typed-value encoders and
that each script still imports and builds its plan offline.

### Operational — live-write smoke test under WIF — release gate, not a coding item
The publisher's fetch → derive → PATCH path and the `gcloud`-minted access token have never run
against live Firestore from CI — 88onsen.com 403s from sandboxes, and Workload Identity
Federation is configured but unproven. Before the first real automated publish, open a PR
editing `data/hours_curated.json` and confirm `catalog-dry-run` authenticates and posts a diff
(see `.github/CATALOG_AUTOMATION.md` → "Smoke test"). If token minting fails under WIF, the fix
is a small shim that reads `$GOOGLE_APPLICATION_CREDENTIALS` instead of shelling out to `gcloud`.

### Cross-cutting
- New work in B should ship with tests — the suite already covers fees, hours, sync,
  soft-removal, schedule publish, readings, and the shared Firestore REST helpers.
- Cross-repo: the app (`kyuhachi`) consumes `adultFee`, `businessHours.schedule`, `nameKana`, and
  `nameRomaji` from the published catalog; coordinate any schema change with it.

## Recommended order

1. **B — `catalog` baseline adapter.** The only open item; independent enrichment that gives the
   diff a published-truth baseline alongside the local snapshot.
- **A — `apply.py` `add` action.** ✅ Shipped (see above).
- **C — extract `publisher/firestore_rest.py`.** ✅ Shipped (see above).
- **Operational smoke test:** do opportunistically from an allowlisted env / under WIF before the
  first real automated publish. It's a release gate.
