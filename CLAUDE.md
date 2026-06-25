# kyuhachi-data — Claude Context

## What this repo is

The **private data repo** for the Kyushu 88 onsen app. It owns the onsen
**catalog source of truth** and everything upstream of Firestore:

- scraping [88onsen.com](https://www.88onsen.com) detail pages,
- assigning and maintaining the stable **`kyuhachiId`** for every onsen,
- publishing the onsen catalog to Firestore.

The app lives in a **separate repo** (`kyuhachi`: Expo app + Firebase Functions
+ shared types + firebase config). This is the two-repo split. The app never
sees upstream ids — it reads only the published catalog.

## Locked decisions (do not challenge without instruction)

- **Stable ids.** Every onsen has a `kyuhachiId` (UUID) that never changes.
  Upstream ids (88onsen `hid`) are unstable and live ONLY in this repo, in
  `data/onsen-id-map.json` (`hid` → `kyuhachiId`). This repo is solely
  responsible for assigning and maintaining them.
- **Onsen documents are never deleted.** A removed/deprecated onsen gets
  `isActive: false` in the published catalog, never a delete.
- **Catalog snapshots are frozen per challenge** in the app. Catalog changes
  never mutate existing user challenges. (Relevant because a reseed must not
  assume it can rewrite history.)
- **Be a polite scraper.** 1s delay, exponential backoff, browser UA. Sample,
  don't hammer. (Enforced in `onsen_scraper/fetcher.py`.)

## Source structure reference

The 88onsen detail-page DOM, every field's selector, and per-field coverage are
documented in the **app repo** at `docs/onsen-source-field-audit.md`. That is
the canonical reference for what's on the source and where. `onsen_scraper/` is
the working implementation of those selectors.

URL pattern: `https://www.88onsen.com/spot/detail/hid/{hid}`.

## Updating the catalog — start here

**`.claude/skills/catalog-sync/`** is the single entry point for any onsen-data
update. Ask to "update / sync the onsen catalog" → that skill runs the whole loop
(detect → publish to Firestore → retire/mint → advance the baseline), orchestrating
the focused tools below and gating every write. Don't reinvent the sequence; follow
its phases.

## Components

| Path | Role |
|---|---|
| `.claude/skills/catalog-sync/` | **Orchestrator** — the end-to-end update runbook + `catalog_sync.py` driver (`status`/`sample`/`detect`/`mint`/`promote`). |
| `.claude/skills/catalog-diff/` | Read-only re-scrape + changelog (the detection engine `catalog-sync detect` builds on). |
| `.claude/skills/recurate-hours/` | LLM re-parse of changed `business_hours` → `data/hours_curated.json`. |
| `onsen_scraper/fetcher.py` | Polite HTTP fetch of a detail page by `hid`. |
| `onsen_scraper/parser.py` | DOM → 13 raw fields (`_FIELD_MAP` over `dl.tableview`). |
| `onsen_scraper/mapseed.py` | One fetch of `/map` → `hid → {name, areaName, lat, lng, address}` (the fields the detail page lacks; also the authoritative membership set). |
| `onsen_scraper/{fees,hours}.py` | Free-text → numeric `adultFee` / regex `WeeklySchedule` (the regex is NOT the hours source of truth). |
| `publisher/apply.py` | Surgical, decisions-driven Firestore publisher: `update`/`retire`/`skip` (writes text fields + `adultFee`; **not** the schedule). |
| `publisher/backfill_schedule.py` | `--from-curated`: expand `hours_curated.json` → `businessHours.schedule`+`exceptions`+`confidence`. Sole owner of the published grid. |
| `data/snapshot.db` | Diff baseline (148 onsens, raw fields + `raw_html`). Advanced only by `catalog-sync promote`. |
| `data/onsen-id-map.json` | `hid` → `kyuhachiId`. Minted by `catalog-sync mint`. |
| `data/hours_curated.json` | LLM-curated hours, the source of truth for the published schedule. |

## What NOT to do

- Do not write user/challenge/visit data — that's the app's domain.
- Do not delete onsen documents. Use `isActive: false`.
- Do not change a `kyuhachiId` once assigned.
- Do not make the `catalog-diff` skill mutate the snapshot DB or Firestore —
  it is read-only by contract.
- Do not move app/UI concerns here, and do not move catalog/id concerns into
  the app repo.

## Roadmap

Done (the end-to-end loop now exists behind `catalog-sync`):
- ✅ Authoritative ADDED/REMOVED + membership from the **map seed** (`detect`).
- ✅ `kyuhachiId` assignment for new onsens (`catalog-sync mint`).
- ✅ New-onsen **name + coordinates** from the map seed (`onsen_scraper/mapseed.py`);
  `detect` identifies new onsens fully, `promote` baselines them as complete rows.
- ✅ `営業時間` → `WeeklySchedule` (LLM-curated `hours_curated.json` + `backfill_schedule --from-curated`).
- ✅ Versioned backfill/merge publisher (`publisher/apply.py` + the backfills) — never a clean-slate wipe.
- ✅ Baseline advance after publish (`catalog-sync promote`) — `snapshot.db` is no longer frozen.

Still open:
- **`apply.py` `add` action** — create the live Firestore doc for a new onsen from
  the staging data (map seed + detail + curated hours + derived fee). The doc schema
  is known; until this lands, a new onsen is identified + baselined but its catalog
  doc is created by hand. Challenge-pool membership stays in the app repo.
- `catalog` baseline adapter (diff against the live published Firestore catalog, not
  the local snapshot) — `catalog_diff.load_catalog` is a stub.
- Shared `publisher/firestore_rest.py` (the REST/auth helper is copied across the
  publisher scripts).
