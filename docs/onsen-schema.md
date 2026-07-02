# Onsen document schema

Canonical spec for the published `/onsens/{kyuhachiId}` document — every
top-level field this repo writes, and where each one comes from. Owned by this
data repo, consumed read-only by the app (`kyuhachi`). The nested `businessHours`
shape has its own contract: [`docs/hours-schema.md`](hours-schema.md).

The authoritative key set lives in code as `apply.py`'s `ONSEN_DOC_KEYS` — the
`add` action hard-fails if a proposed doc's keys don't match it exactly, so this
table and that set can't silently drift apart.

## Published shape — `/onsens/{kyuhachiId}`

| Field | Type | Source |
|---|---|---|
| `name` | string | `/map` seed |
| `nameKana` | string | generated hiragana reading (gojūon sort key) + curated overlay — `onsen_scraper/readings.py`, `data/readings_curated.json` |
| `nameRomaji` | string | generated Hepburn romaji (display-only) + curated overlay — same module |
| `areaName` | string | `/map` seed |
| `address` | string | live detail scrape (falls back to the seed) |
| `prefecture` | string | live detail scrape |
| `lat`, `lng` | double | `/map` seed |
| `phone` | string | live detail scrape |
| `businessHours` | map | text fields from the live scrape; the structured `schedule`/`exceptions`/`confidence` come only from `data/hours_curated.json` — see [`docs/hours-schema.md`](hours-schema.md) |
| `admissionFee` | string | live detail scrape (free text) |
| `adultFee` | integer \| null | derived numeric yen, parsed from `admissionFee` — `onsen_scraper/fees.py` |
| `springQuality` | string | live detail scrape (泉質) |
| `websiteUrl` | string | live detail scrape |
| `imageUrl`, `blurhash` | string | rehosted Cloud Storage copy of the source photo — `publisher/image_processor.py` |
| `isActive` | boolean | `true` unless retired; onsen docs are never deleted |
| `catalogVersion` | integer \| null | the live `catalog_meta/current.version` at create time |
| `createdAt` | timestamp | doc creation time |
| `updatedAt` | timestamp | last write time (any field) |
| `dataVerifiedAt` | timestamp \| null | last time this onsen's data was confirmed against the live source — see below |

## `dataVerifiedAt` — freshness cue

The app displays this as a freshness cue (e.g. "data last verified 2026-06") so
fee/hours drift between `catalog-sync` runs doesn't read as silently wrong —
managing the expectation that this catalog is periodically re-verified, not
continuously live.

**Ongoing path.** `publisher/apply.py`'s `update` and `add` actions both re-fetch
the live detail page before writing, so the write's own `now` timestamp genuinely
*is* the moment this onsen's data was confirmed against the source — the same
instant already used for `updatedAt`/`createdAt`. `retire` does not touch it
(retiring confirms delisting, not fee/hours accuracy).

**Initial seed.** Existing onsens get their first `dataVerifiedAt` from the
one-time `publisher/backfill_data_verified_at.py`, sourced from
`data/snapshot.db`'s per-row `scraped_at` (the best per-onsen signal available
without re-fetching all 161 detail pages just to stamp a date).

**Known limitation.** `scraped_at` is only refreshed by `catalog-sync promote`
when a row is *inserted* (a brand-new onsen) — the `promote_into_db` UPDATE path
does not currently touch it. So for most pre-existing onsens, the seeded
`dataVerifiedAt` reflects the *original* baseline scrape, not the most recent
re-verification, until either an `apply.py` write on that onsen lands (which
refreshes it correctly) or `promote_into_db` is taught to bump `scraped_at` on
every promoted row (tracked as a follow-up, not yet done).

**Monotonic guard.** Like the other backfills, the seed is no-op aware — but
with a forward-only rule instead of plain equality: a doc is written only when
the seed would move its live `dataVerifiedAt` *forward*. Re-running the backfill
after `apply.py` has stamped fresher live-verified values skips those docs
rather than regressing them to the staler snapshot timestamp, and the catalog
version is bumped only when at least one doc is actually written.
