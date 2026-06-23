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
├── onsen_scraper/        # detail-page fetcher + parser (ported from the prototype)
├── data/
│   ├── snapshot.db       # last good full scrape — the diff baseline (148 onsens)
│   └── onsen-id-map.json # upstream hid → stable kyuhachiId
└── .claude/skills/
    └── catalog-diff/     # read-only "what changed on the source" report
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
- [x] `catalog-diff` skill — MODIFIED + REMOVED detection over known ids
- [ ] `catalog` baseline adapter (diff against the live published Firestore catalog)
- [ ] Index/listing crawl → ADDED detection + kyuhachiId assignment for new onsens
- [ ] `営業時間` → `WeeklySchedule` adapter (see the app repo's onsen-source-field-audit)
- [ ] Catalog publisher (scrape → snapshot DB → Firestore) as a versioned backfill
