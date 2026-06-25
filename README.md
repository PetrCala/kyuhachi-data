# kyuhachi-data

Private data pipeline for the **九州八十八湯 (Kyushu 88 onsen)** challenge app
([`kyuhachi`](https://github.com/PetrCala/kyuhachi)).

This repo owns the onsen **catalog source of truth**: scraping
[88onsen.com](https://www.88onsen.com), maintaining the stable `kyuhachiId`
assignment, and publishing the catalog to Firestore. The app repo never sees
upstream ids — it only reads the published catalog.

## Layout

```
.
├── onsen_scraper/         # detail-page fetcher + parser + fee/hours parsers
├── publisher/             # surgical Firestore publisher + curated backfills
├── data/
│   ├── snapshot.db        # the diff baseline (148 onsens); advanced by `catalog-sync promote`
│   ├── onsen-id-map.json  # upstream hid → stable kyuhachiId
│   └── hours_curated.json # LLM-curated hours → published businessHours.schedule
└── .claude/skills/
    ├── catalog-sync/      # ► the single entry point: full update loop, end-to-end
    ├── catalog-diff/      # read-only "what changed on the source" report
    ├── recurate-hours/    # LLM re-parse of changed business_hours
    └── cost-analysis/     # admission-fee cost estimator
```

## Updating the catalog

One entry point: the **`catalog-sync`** skill. It runs the whole loop — detect what
changed on 88onsen, publish field/fee/hours updates to the live app, retire removed
onsens, mint ids for new ones, and advance the local baseline — pausing at every
write for approval.

```bash
python .claude/skills/catalog-sync/catalog_sync.py status        # where do things stand?
python .claude/skills/catalog-sync/catalog_sync.py sample --n 10 # preflight the source
python .claude/skills/catalog-sync/catalog_sync.py detect --discover   # scrape + diff + triage
# …then follow the phases in .claude/skills/catalog-sync/SKILL.md
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Catalog diff (read-only)

Check whether the live source has drifted from the last scrape, without writing
anything:

```bash
# preflight: confirm selectors + network egress are healthy, then stop
python .claude/skills/catalog-diff/catalog_diff.py --sample 10

# full diff vs the snapshot baseline → reports/<timestamp>/{changelog.json,summary.md}
python .claude/skills/catalog-diff/catalog_diff.py
```

> `www.88onsen.com` returns `403 Host not in allowlist` from sandboxed
> environments. Run the scraper from an environment that can reach the host.

See [`.claude/skills/catalog-diff/SKILL.md`](.claude/skills/catalog-diff/SKILL.md)
for the full workflow.

## Status / roadmap

- [x] Scraper port (fetcher + parser), baseline snapshot, id map
- [x] `catalog-diff` skill — MODIFIED + REMOVED detection; `--discover` adds ADDED
- [x] `catalog-sync` skill — end-to-end update loop (detect → publish → mint → promote)
- [x] kyuhachiId assignment for new onsens (`catalog-sync mint`)
- [x] `営業時間` → `WeeklySchedule` via LLM-curated `hours_curated.json` + backfill
- [x] Versioned backfill/merge publisher (`publisher/`); baseline advance (`promote`)
- [ ] `catalog` baseline adapter (diff against the live published Firestore catalog)
- [ ] New-onsen name/coords from the map seed + an `apply.py` `add` action
