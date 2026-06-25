---
name: catalog-sync
description: THE single entry point for updating the onsen catalog from 88onsen.com
  end-to-end — detect what changed, publish field/fee/hours updates to the live app
  (Firestore), retire removed onsens, mint ids for new ones, and advance the local
  baseline. Orchestrates the focused tools (catalog-diff, recurate-hours, the
  publisher scripts) and stops at every write for human approval. Use whenever
  someone asks to update / sync / refresh the onsen data, or "run the onsen update".
---

# catalog-sync

This is the **one place to start** any onsen-data update. If you come back in six
months and say "update the onsen information," this is where you (or an agent) get
pointed. It runs the whole pipeline — **detect → publish → propagate → advance the
baseline** — by orchestrating the focused sub-tools, pausing at each write for
approval. It is an aggregator, not a rewrite: the real work still lives in
`catalog-diff` (detection), `recurate-hours` (hours), and `publisher/*` (Firestore
writes); this skill sequences them correctly so you never have to remember the
ordering hazards.

The driver [`catalog_sync.py`](catalog_sync.py) owns the new mechanical glue —
`status`, `sample`, `detect` (one scrape → changelog + a staging scrape), `mint`
(assign kyuhachiIds), and `promote` (advance the otherwise-frozen `snapshot.db`
baseline). Everything offline by default; every Firestore/disk write is gated.

## When to use

- "Update / sync / refresh the onsen catalog from 88onsen."
- Periodic maintenance — see whether the source drifted and propagate it to the app.
- After a long gap, when you don't remember the steps. Start here; follow the phases.

For a quick read-only "did anything change?", `catalog-diff` alone is enough. To fix
one onsen's hours without a full sync, `recurate-hours` alone is enough. This skill
is the full loop.

## Mental model

```
 88onsen.com ──scrape──┐
                       ▼
   detect ──► changelog.json  +  snapshot.next.json (staging)
                       │                    │
        ┌──────────────┼───────────────┐    │
        ▼              ▼               ▼    │
   apply.py        recurate-hours    mint   │   ← publish to the LIVE app (gated)
  (fields/fees/   (LLM hours →       (new   │
   retire/add)     curated → backfill ids)  │
        └──────────────┴───────────────┘    │
                       ▼                     ▼
              Firestore /onsens   ◄── promote advances snapshot.db
              + catalog_meta.version    (run LAST, after publishing)
```

Two sources of truth feed the published `businessHours`: text fields + numeric
`adultFee` come from the **live re-scrape** (apply.py); the structured weekly
`schedule` + `exceptions` + `confidence` come **only** from
[`data/hours_curated.json`](../../../data/hours_curated.json) (the LLM parse, via
recurate-hours). apply.py deliberately never writes a regex schedule.

## The run (phases)

Run from the repo root. Auth (`gcloud auth application-default login`) is needed
only for the `--commit` steps that write Firestore (project `kyuhachi-fddcc`);
detect / promote / mint / status need no auth.

**Phase 0 — Preflight.**
```bash
python .claude/skills/catalog-sync/catalog_sync.py status        # offline: baseline / id-map / curated coverage
python .claude/skills/catalog-sync/catalog_sync.py sample --n 10 # is the source reachable + selectors intact?
```
If `sample` can't fetch, the host isn't allowlisted (`403` from sandboxes) — run from
a networked shell. If pages fetch but parse empty, the DOM drifted — fix selectors in
`onsen_scraper/parser.py` before continuing.

**Phase 1 — Detect.** One polite scrape + the map seed, diffed against the baseline:
```bash
python .claude/skills/catalog-sync/catalog_sync.py detect
```
`detect` fetches the **map seed** (one request to `/map` → every listed onsen's
`hid → {name, areaName, lat, lng, address}`). The seed is the authoritative
membership set (ADDED / REMOVED) and supplies the name + coordinates the detail
page can't. It writes `reports/<ts>/{changelog.json,summary.md}` and
`data/snapshot.next.json` (the staging scrape, **incl. the seed**, for Phase 6),
and prints a **triage** routing each change to its phase — new onsens come out
fully identified (area：name + coords). Read `summary.md`. If nothing material
changed, stop.

**Phase 2 — Publish field / fee / retire / add changes** via the surgical publisher:
```bash
python publisher/apply.py --from-changelog reports/<ts>/changelog.json --out decisions.json
#   → review every action: update / retire / skip  (adjudicate identity: ≥4 changed
#     material fields usually means a replaced facility → retire + remint, not update)
python publisher/apply.py --decisions decisions.json            # DRY-RUN (re-fetches live)
python publisher/apply.py --decisions decisions.json --commit   # writes; derives adultFee; bumps version
```
`update` refreshes the changed material fields (incl. `businessHours.raw`) + numeric
`adultFee`. `retire` sets `isActive:false` (onsen docs are never deleted). New onsens
need Phase 4 first.

**Phase 3 — Re-curate changed hours** (the triage lists every `business_hours`
change; each MUST be re-curated so the grid never ships a wrong regex parse):
```bash
python .claude/skills/recurate-hours/recurate_hours.py targets --changelog reports/<ts>/changelog.json
python .claude/skills/recurate-hours/recurate_hours.py show <hids> --changelog reports/<ts>/changelog.json
#   → re-parse each per docs/hours-schema.md (you, the model — not the regex)
python .claude/skills/recurate-hours/recurate_hours.py set --file refreshed.json
uv run --python 3.12 --with pytest python -m pytest tests/
python publisher/backfill_schedule.py --from-curated            # DRY-RUN diff vs live
python publisher/backfill_schedule.py --from-curated --commit   # writes schedule+exceptions+confidence; bumps version
```
**Order matters:** run this AFTER Phase 2, so the curated schedule lands last and
isn't masked. (apply.py touches only `raw`/`adultFee`, but keep the discipline.)

**Phase 4 — New onsens (ADDED).** `detect` already identified them fully (name /
area / coords from the seed, detail fields from the scrape, both in staging). Mint
the stable id:
```bash
python .claude/skills/catalog-sync/catalog_sync.py mint --from-staging          # DRY-RUN
python .claude/skills/catalog-sync/catalog_sync.py mint --from-staging --commit  # writes onsen-id-map.json
```
Then curate the new onsen's hours (Phase 3). **Creating the live Firestore doc
(`apply.py add`) is the one piece not yet built** — until it lands, a new onsen is
fully *identified and baselined* (it flows into `promote` as a complete row) but its
catalog doc is created by hand from the staging data (name/areaName/lat/lng + detail
fields + curated hours + derived adultFee, isActive:true). **Challenge-pool
membership lives in the app repo** and is always a separate hand-off.

**Phase 5 — Removed onsens** are handled as `retire` actions in the Phase-2 decisions
file (`isActive:false`). Nothing else to do for them in Firestore.

**Phase 6 — Advance the baseline.** Only after the publish steps succeeded:
```bash
python .claude/skills/catalog-sync/catalog_sync.py promote            # DRY-RUN
python .claude/skills/catalog-sync/catalog_sync.py promote --commit   # UPDATE/INSERT snapshot.db from staging
#   fills name/area/coords from the seed (new rows land COMPLETE; coord drift syncs).
#   add --prune to also drop confirmed-removed rows.
```
This is the fix for the long-standing gap: `snapshot.db` was never rewritten, so
every diff was "vs the original scrape." After `promote`, the next `detect` diffs
against reality — "since last update." Run it **last**: if you promote before
publishing and the publish fails, the next detect would show no diff and you'd lose
the changelog.

**Phase 7 — Verify.** `uv run --python 3.12 --with pytest python -m pytest tests/`
(coverage stays exact: id-map + curated cover the baseline). Optionally sanity-check
fees with the `cost-analysis` skill.

## Derived fields published outside the diff loop

Some published fields are *generated* from a stable field rather than re-scraped,
so they have their own idempotent backfill instead of riding the detect→apply loop:

- **`nameKana`** — the hiragana reading (yomi) of `name`, the app's within-prefecture
  gojūon sort key. Readings don't exist upstream and `name` isn't a detail-page field
  (it comes from the map seed, so `apply.py` never sees it change), so it's published
  by [`publisher/backfill_name_kana.py`](../../../publisher/backfill_name_kana.py)
  (generated via `onsen_scraper.readings.name_kana`, folded to hiragana):
  ```bash
  python publisher/backfill_name_kana.py            # DRY-RUN: plan + sample readings
  python publisher/backfill_name_kana.py --show     # also list all 148 readings
  python publisher/backfill_name_kana.py --commit   # writes nameKana; bumps version
  ```
  Idempotent, so re-run it after a new onsen's name lands (or a name correction) to
  republish only what changed. A future `apply.py` `add` action should call
  `name_kana()` when it mints a new doc. Auto-generated, no hand-correction — some
  proper-noun readings will be imperfect (the agreed tradeoff). Consumed by app PR
  PetrCala/kyuhachi#143.

## Ordering rules (the things you'd otherwise rediscover the hard way)

1. **Publish before promote.** The changelog/staging are derived from the diff vs the
   current baseline; advancing the baseline first erases the very diff you're acting on.
2. **Curated hours after apply.** `hours_curated.json` is the sole owner of the weekly
   grid; run `backfill_schedule --from-curated` after `apply.py` so it lands last.
3. **Every `business_hours` change gets re-curated.** apply.py refreshes `raw` but
   leaves the grid stale-but-honest until Phase 3 corrects it. Don't skip it.
4. **Mint before publishing a new onsen.** No kyuhachiId → the publisher can't place it.

## Driver subcommands ([`catalog_sync.py`](catalog_sync.py))

| Command | Effect | Writes |
|---|---|---|
| `status` | Offline: baseline size, id-map + curated coverage, pending staging. | — |
| `sample --n N` | Preflight scrape of N pages → parse-health verdict. | — |
| `detect [--limit N]` | One scrape + map seed → `reports/<ts>/` + `snapshot.next.json` + triage. | report + staging |
| `mint (hids… \| --from-staging) [--commit]` | Assign kyuhachiId(s) to new onsens. | `onsen-id-map.json` (gated) |
| `promote [--scrape PATH] [--prune] [--commit]` | Advance `snapshot.db` from staging (UPDATE/INSERT + seed name/coords, optional prune). | `snapshot.db` (gated) |

## Guarantees

- **Offline + read-only by default.** `status`/`sample`/`detect` never write Firestore;
  `detect` writes only a gitignored report + staging file. `mint` and `promote` are
  dry-run unless `--commit`.
- **Every live write is human-gated** and goes through a dry-run first: `apply.py`,
  `backfill_schedule.py`, `mint`, `promote`.
- **Onsen docs are never deleted** (retire = `isActive:false`); **kyuhachiIds never
  change once assigned**; `snapshot.db` is git-tracked, so `promote` is revertible.
- **The regex never authors hours.** Published schedules come only from the curated
  LLM parse.

## Not yet automated (call these out, don't fake them)

- **New-onsen live-doc creation (`apply.py add`)** — `detect` now identifies new
  onsens fully (name/area/coords from the map seed) and `promote` baselines them, but
  the step that *creates the Firestore doc* from that data is still pending; for now
  it's done by hand from the staging data. (The doc schema is known: `name`,
  `areaName`, `lat`, `lng`, `prefecture`, `address`, `phone`, `admissionFee`,
  `adultFee`, `springQuality`, `websiteUrl`, `imageUrl`, `businessHours`,
  `isActive`, `catalogVersion`.)
- **Challenge-pool membership** — adding a new onsen to a challenge pool lives in the
  **app** repo; always a separate hand-off.
- **`catalog` baseline adapter** — diffing against the *live published* Firestore
  catalog (vs the local snapshot) is still a stub (`catalog_diff.load_catalog`).
- **Shared Firestore REST helper** — `apply.py` / `backfill_*.py` still each carry a
  copy (low-priority DRY cleanup).

## Related

- [`catalog-diff`](../catalog-diff/SKILL.md) — the read-only detection engine `detect` builds on.
- [`recurate-hours`](../recurate-hours/SKILL.md) — the Phase-3 hours re-parse.
- [`cost-analysis`](../cost-analysis/SKILL.md) — fee sanity-check.
- [`docs/hours-schema.md`](../../../docs/hours-schema.md) — the published `businessHours` contract.
