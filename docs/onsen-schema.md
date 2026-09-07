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
| `areaId` | string \| null | stable id of the coarse tourism region this onsen rolls up into (the app's area guides). Assigned by `onsen_scraper/regions.py`, written by `publisher/backfill_area_id.py` (and set on create by `apply.py`'s `add`). null until published, or when the region model can't place the onsen yet. See [`docs/area-guides-schema.md`](area-guides-schema.md) |
| `address` | string | live detail scrape (falls back to the seed) |
| `prefecture` | string | live detail scrape |
| `lat`, `lng` | double | `/map` seed |
| `phone` | string | live detail scrape |
| `businessHours` | map | text fields from the live scrape; the structured `schedule`/`exceptions`/`confidence` come only from `data/hours_curated.json` — see [`docs/hours-schema.md`](hours-schema.md) |
| `admissionFee` | string | live detail scrape (free text) |
| `adultFee` | integer \| null | derived numeric yen, parsed from `admissionFee` — `onsen_scraper/fees.py` |
| `springQuality` | string | live detail scrape (泉質) |
| `websiteUrl` | string | live detail scrape |
| `detailPageUrl` | string | the onsen's page on 88onsen.com, derived from the hid (`onsen_scraper.get_detail_url`), not scraped. The app credits each catalog photo back to this page, per the licence granted 2026-08-31 (see `publisher/backfill_detail_page_url.py`) |
| `imageUrl`, `blurhash` | string | rehosted Cloud Storage copy of the source photo — `publisher/image_processor.py` |
| `isActive` | boolean | `true` unless retired; onsen docs are never deleted |
| `catalogVersion` | integer \| null | the live `catalog_meta/current.version` at create time |
| `createdAt` | timestamp | doc creation time |
| `updatedAt` | timestamp | last write time (any field) |
| `dataVerifiedAt` | timestamp \| null | last time this onsen's data was confirmed against the live source — see below |

## Published shape: `/catalog_meta/current`

The one document the app polls to decide whether its cached catalog is stale.

| Field | Type | Source |
|---|---|---|
| `version` | integer | incremented by `bump_catalog_version` on every committed publish; the app refetches the whole catalog when this moves past its cached value |
| `publishedAt` | timestamp | that write's timestamp |
| `totalCount` | integer | onsen documents, **including** retired (`isActive: false`) ones |
| `activeCount` | integer | onsen documents with `isActive: true` |

All four are written together by `bump_catalog_version` in
`publisher/firestore_rest.py`, which every publisher script calls after its
writes land.

**The counts come from the live collection, not from `data/snapshot.db`.** The
snapshot is the diff baseline and retired onsens are pruned out of it, so it
cannot see a document that still exists in Firestore with `isActive: false`.
Counting the snapshot would report the active count as the total and understate
`totalCount` by one for every retirement. Only the live collection knows both
numbers.

The counts are advisory. The app filters on `isActive` itself and does not read
either field, so they are published for correctness rather than for a consumer.
Do not make them load-bearing for eligibility: a challenge's pool is the frozen
snapshot unioned with the live pool, and nothing about that is derived from a
count.


## Published shape: `/catalog_index/current`

A slim, **derived** projection of the catalog for the app repo's public journey
website. It renders seven values per onsen and used to read all 161 `/onsens`
documents, 386 KB, to get them; packed into one document that is 24 KB and a
single document read. Nothing about `/onsens` changes: the app reads it and uses
nearly every field. The reasoning and the measurements are in the app repo's
[ADR-012](https://github.com/PetrCala/kyuhachi/blob/master/docs/adr/012-website-catalog-index.md);
the reader's half of the contract is `CatalogIndexDocument` in its
`shared/src/types/onsen.ts`.

| Field | Type | Source |
|---|---|---|
| `schemaVersion` | integer | `CATALOG_INDEX_SCHEMA_VERSION` in `publisher/firestore_rest.py`; how `entries` is packed |
| `version` | integer | the `catalog_meta/current.version` this was derived from — mirrored, never independently incremented |
| `publishedAt` | timestamp | that write's timestamp |
| `count` | integer | number of entries, for verifying a publish |
| `entries` | string | `json.dumps` of one positional tuple per onsen, see below |

`entries` is one JSON string per publish, not a Firestore array:

```
[[kyuhachiId, name, nameRomaji|null, areaName, prefecture, lat, lng], ...]
```

Four properties of that string are load-bearing, and all four are pinned by
tests in `tests/test_firestore_rest.py`:

- **A string, not an `arrayValue`.** An array of maps re-incurs the per-value
  protobuf-JSON envelope this document exists to remove: 54 KB against 24 KB
  for the same data.
- **Positional tuples, not objects.** Seven keys repeated 161 times cost more
  than the values do. The order is therefore the contract: a later schema may
  **append** a field (readers index by position and ignore extras), but
  reordering or removing one is breaking and must bump `schemaVersion`.
- **`ensure_ascii=False`.** Escaping the Japanese names would double the size of
  the one field the document exists to keep small.
- **Sorted by `kyuhachiId`.** Republishing an unchanged catalog produces a
  byte-identical document, so a diff means something.

**Every onsen is indexed, retired ones included.** The website has to be able to
place a visit to an onsen that was later retired, and a frozen challenge snapshot
can still name one, so filtering on `isActive` here would lose dots the map has
to draw. `isActive` itself is not published: nothing on the site branches on it.

Coordinates are rounded to 5 decimal places (~1.1 m), matching how the app repo
encodes walked tracks. More precision than a map dot can express costs bytes.

**Who writes it.** `bump_catalog_version` in `publisher/firestore_rest.py`
republishes it after every committed publish, from the same live read that
produces the counts above and stamped with the same new version — so the website
can never serve an index derived from a catalog the app has already moved past.
`publisher/publish_catalog_index.py` is the standalone path for the two cases
that loop cannot cover: the very first publish (nothing else would call
`bump_catalog_version`, and publishing an index is not a catalog change, so it
deliberately leaves `version` alone rather than making every device redownload an
unchanged catalog), and rebuilding a deleted or suspect index. Both are dry-run
by default.

The document is 24 KB against Firestore's 1 MiB per-document limit, roughly 40x
the current catalog's worth of headroom, so it never needs to page.

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

**Freshness.** `catalog-sync promote`'s `promote_into_db` bumps `scraped_at` to
`now` on every hid present in that cycle's staging — both an UPDATE (fields
changed) and a confirmed-identical re-scrape (unchanged), since landing in
staging means the hid was freshly re-scraped and reconciled, which is itself a
verification event. `apply.py`'s `update`/`add` actions refresh the live
`dataVerifiedAt` directly the same way — but only for materially-changed
onsens. For the confirmed-unchanged rest of the cycle, the gated
`catalog-publish` workflow runs `publisher/backfill_data_verified_at.py
--commit` immediately after promote, propagating the refreshed `scraped_at`
into the live `dataVerifiedAt` — every publish advances the freshness cue for
the whole re-verified cycle, not just the rows that changed. Rows absent from
a cycle's staging keep their prior `scraped_at`, and the monotonic backfill
leaves their live value alone; for rows never re-promoted since the
`scraped_at` fix landed, that is still the original baseline scrape.

**Monotonic guard.** Like the other backfills, the seed is no-op aware — but
with a forward-only rule instead of plain equality: a doc is written only when
the seed would move its live `dataVerifiedAt` *forward*. Re-running the backfill
after `apply.py` has stamped fresher live-verified values skips those docs
rather than regressing them to the staler snapshot timestamp, and the catalog
version is bumped only when at least one doc is actually written.
