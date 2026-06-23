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

## Components

| Path | Role |
|---|---|
| `onsen_scraper/fetcher.py` | Polite HTTP fetch of a detail page by `hid`. |
| `onsen_scraper/parser.py` | DOM → 13 raw fields (`_FIELD_MAP` over `dl.tableview`). |
| `data/snapshot.db` | Last full scrape (148 onsens, raw fields + `raw_html`). The diff baseline. |
| `data/onsen-id-map.json` | `hid` → `kyuhachiId`. |
| `.claude/skills/catalog-diff/` | Read-only re-scrape + changelog. |

## What NOT to do

- Do not write user/challenge/visit data — that's the app's domain.
- Do not delete onsen documents. Use `isActive: false`.
- Do not change a `kyuhachiId` once assigned.
- Do not make the `catalog-diff` skill mutate the snapshot DB or Firestore —
  it is read-only by contract.
- Do not move app/UI concerns here, and do not move catalog/id concerns into
  the app repo.

## Roadmap (not yet built)

- `catalog` baseline adapter (diff against the live published Firestore catalog).
- Index/listing crawl → ADDED detection + `kyuhachiId` assignment for new onsens.
- `営業時間` → `WeeklySchedule` adapter (single-window cases; fall back to `raw`).
- Catalog publisher (scrape → snapshot DB → Firestore) as a **versioned
  backfill/merge**, not the pre-launch clean-slate wipe.
