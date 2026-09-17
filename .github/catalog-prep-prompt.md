# Onsen catalog — prep session prompt

The monthly `catalog-detect` workflow opens an issue with this prompt when 88onsen drift
is detected. **Paste it into a fresh Claude Code session on the `kyuhachi-data` repo**
(run it on your Claude subscription — not the metered GitHub `@claude` action). The
session prepares a *review PR*; it must **not** publish to Firestore. You review and merge
the PR; the gated `catalog-publish` workflow does the live write.

---

Run the **catalog-sync** prep for the catalog drift detected this cycle. Do the detection
and preparation phases only, then open a PR for me to review and merge. **Do not run any
`--commit` publish step** (no `apply.py --commit`, no `backfill_schedule.py --commit`) —
the gated publish workflow performs the live Firestore write on merge. The one `--commit`
you *do* run is `catalog_sync.py mint --commit`: it writes `data/onsen-id-map.json` in the
working tree, never Firestore.

1. **Detect fresh.** `python .claude/skills/catalog-sync/catalog_sync.py detect`, then read
   `reports/<ts>/summary.md` and the printed triage. If nothing material changed, say so
   and stop.

2. **Decisions (fields / fees / retire / add).** Scaffold and adjudicate:
   `python publisher/apply.py --from-changelog reports/<ts>/changelog.json --out decisions.json`,
   then review every action (`update` / `retire` / `skip` / `add`; the scaffold defaults
   ADDED onsens to `add`). **Identity rule:** ≥4 changed material fields usually means a
   *replaced facility* → `retire` + remint, not `update`. Call out each such call in the PR.
   Dry-run: `python publisher/apply.py --decisions decisions.json` (re-fetches live; no write).

3. **Hours.** Every `business_hours` change MUST be re-curated — never ship a regex grid.
   `python .claude/skills/recurate-hours/recurate_hours.py targets --changelog reports/<ts>/changelog.json`,
   then `… recurate_hours.py show <hids> --changelog reports/<ts>/changelog.json`, re-parse
   per `docs/hours-schema.md`, `… recurate_hours.py set --file refreshed.json`, run the
   tests, then dry-run `python publisher/backfill_schedule.py --from-curated`.

4. **New onsens (ADDED).** `detect` identified them fully: name/area/coords from the map
   seed, detail fields in the staging scrape. Per catalog-sync SKILL.md Phase 4 the order is
   **mint → curate hours → record an `add` decision**:
   - **Mint the id.** Dry-run `python .claude/skills/catalog-sync/catalog_sync.py mint --from-staging`,
     then `… mint --from-staging --commit` (writes `data/onsen-id-map.json` only). Mint in
     *this* PR: `apply.py add` silently skips any hid without a kyuhachiId when
     `decisions.json` merges.
   - **Curate its hours from scratch** (step 3). `recurate_hours.py show` has no text for an
     ADDED hid (the changelog carries only modified ones), so read `business_hours` out of
     `data/snapshot.next.json`. Without a curated entry the new doc publishes a null
     schedule and the curated ⊇ snapshot coverage test fails after promote.
   - **Keep the `add` decision.** On merge, `apply.py add` creates `/onsens/{kid}`: the full
     `OnsenDocument` assembled from the seed (name/areaName/lat/lng) + a live detail scrape +
     the curated hours + a derived `adultFee` + generated `nameKana`/`nameRomaji` + a rehosted
     photo, `isActive:true`. It's the one create (vs PATCH) write, idempotent (skips an
     existing doc) and gated like every other publish. The step-2 dry-run previews it; don't
     run `--commit` yourself.
   - **Still a hand-off:** challenge-pool membership lives in the **app** repo and is always
     separate. Creating the catalog doc never auto-joins a challenge, so flag every ADDED
     onsen in the PR for it.

5. **Tests.** `uv run --python 3.12 --with pytest python -m pytest tests/`.

6. **Open the PR** to `master`, committing `decisions.json`, `data/hours_curated.json`, and
   `data/onsen-id-map.json` (if you minted). **Label it `catalog-publish`.** In the body
   include: a summary of the changes, your identity-adjudication calls, and the ADDED-onsen
   challenge-pool flags. The `catalog-dry-run` check posts the authoritative Firestore diff
   for me to review.
