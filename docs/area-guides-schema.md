# Area guides schema

Canonical spec for the published `/area_guides/{areaId}` collection and its
`/area_guides_meta/current` version doc, plus the `areaId` join field on
`/onsens`. Owned by this data repo, consumed read-only by the app (`kyuhachi`).
This is the data repo's half of the app's "area guides" feature (app ADR-008):
evergreen, time-agnostic tourist info for the coarse region a user is in.

The app-side contract is defined in the `kyuhachi` repo (ADR-008,
`docs/specs/firestore-data-model.md`, `shared/src/types/areaGuide.ts`). Keep this
file and those in sync; when they conflict, fix both.

## Why this feature is publish-once

Area guides carry **only time-agnostic, evergreen** content: specialties,
produce, attractions, history, culture. Never opening hours, prices, dated
events, or named shops and restaurants. That is what lets the collection be
authored once and republished only when the editorial copy itself changes,
rather than tracked against the live source like the onsen catalog.

Every user-facing string is bilingual `{ en, ja }`. This is a deliberate
exception to the app's "don't translate Firestore content" rule (which is for
scraped onsen data); guides are editorial copy authored for the app.

## Regions and the `areaId`

`areaId` is a stable UUID this repo owns and assigns, exactly like `kyuhachiId`.
Upstream 88onsen ids are never exposed. Onsens roll up into a small set of
coarse **tourism regions** defined in `onsen_scraper/regions.py`:

- **Single-region prefectures** (Fukuoka, Saga, Nagasaki, Miyazaki, Kagoshima)
  map by prefecture, so any onsen (including ones added later) is placed.
- **Split prefectures** (Oita, Kumamoto) are large and hold several famous,
  unambiguous sub-regions, so they split by `onsen_area_name`. A novel area name
  in a split prefecture is left unplaced (surfaced for the maintainer) rather
  than guessed.

Three reviewable files under `data/` back the feature:

| File | Role |
|---|---|
| `data/area-id-map.json` | Stable ledger, `regionKey -> areaId`. Mirrors `data/onsen-id-map.json`. Ids are assigned once and never changed or reused. |
| `data/area-regions.json` | Generated region model: `areaId`, English label, prefecture, `center` centroid, and member onsen lists. Regenerate with `python -m onsen_scraper.regions --build`. |
| `data/area_guides_curated.json` | Editorial content: bilingual `name`, optional `tagline`, and the `sections`. Human-authored and human-reviewed. |

## `/onsens/{kyuhachiId}` join field

| Field | Type | Source |
|---|---|---|
| `areaId` | string \| null | the region an onsen rolls up into. Written by `publisher/backfill_area_id.py` (and set on create by `apply.py`'s `add`). null until published, or when the region model can't place the onsen yet. |

## `/area_guides/{areaId}`

**Document ID:** the region's `areaId`.

| Field | Type | Notes |
|---|---|---|
| `name` | `{ en, ja }` | region display name, bilingual |
| `tagline` | `{ en, ja } \| null` | optional one-line hero hook (e.g. "Japan's onsen capital") |
| `center` | `{ lat, lng }` | region center: the centroid of member onsen coordinates |
| `sections` | `AreaGuideSection[]` | ordered by `specialties, produce, attractions, history, culture`; only kinds with content are included |
| `version` | `number` | the `area_guides` publish version at write time |
| `updatedAt` | `Timestamp` | last write time |

### `AreaGuideSection`

| Field | Type | Notes |
|---|---|---|
| `kind` | `'specialties' \| 'produce' \| 'attractions' \| 'history' \| 'culture'` | section category |
| `body` | `{ en, ja }` | 2 to 4 evergreen sentences |
| `highlights` | `{ en, ja }[]` (optional) | short bullets, e.g. dish or produce names; never a business |

The authoritative doc key set lives in code as `publish_area_guides.py`'s
`GUIDE_DOC_KEYS`; the publisher asserts against it before every create so this
table and that set can't silently drift apart.

## `/area_guides_meta/current`

Single document tracking the current area-guides version. The app reads it to
decide whether to refetch guides.

**Document ID:** always `current`.

| Field | Type | Notes |
|---|---|---|
| `version` | `number` | monotonically increasing integer; bumped on every publish that writes at least one guide |
| `publishedAt` | `Timestamp` | when this version was published |
| `totalCount` | `number` | number of `area_guides` documents |

## Invariants

- `areaId` never changes once assigned; a retired region keeps its id.
- **No soft-delete flag** (unlike onsens). A region dropped from the curated
  source is simply no longer published; a lingering live doc is reported as an
  orphan and removed only with `publish_area_guides.py --prune`.
- Content is **human-reviewed before publish**. `publish_area_guides.py` refuses
  `--commit` while `data/area_guides_curated.json`'s `_meta.reviewStatus` is not
  `"reviewed"`. A dry-run always runs so the copy can be proofed first.
- Do not invent businesses or anything with a date or price.

## Workflow

```bash
# 1. (re)build the region model + mint any new areaIds (after a catalog change):
python -m onsen_scraper.regions --build

# 2. backfill the areaId join onto /onsens (dry-run, then commit):
#    (also runs automatically, gated, in the catalog-publish workflow after promote;
#     this manual commit is only for an out-of-cycle taxonomy or content update)
python publisher/backfill_area_id.py
python publisher/backfill_area_id.py --commit

# 3. author / edit data/area_guides_curated.json, get it human-reviewed, then
#    flip _meta.reviewStatus to "reviewed".

# 4. publish the guides + bump the version doc (dry-run, then commit):
python publisher/publish_area_guides.py
python publisher/publish_area_guides.py --commit
```

**Access:** authenticated users may read `/area_guides` and
`/area_guides_meta/current`. No user may write. Admin service account may write.
