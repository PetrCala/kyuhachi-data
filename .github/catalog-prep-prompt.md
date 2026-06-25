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
the gated publish workflow performs the live Firestore write on merge.

1. **Detect fresh.** `python .claude/skills/catalog-sync/catalog_sync.py detect`, then read
   `reports/<ts>/summary.md`. If nothing material changed, say so and stop.

2. **Decisions (fields / fees / retire).** Scaffold and adjudicate:
   `python publisher/apply.py --from-changelog reports/<ts>/changelog.json --out decisions.json`,
   then review every action. **Identity rule:** ≥4 changed material fields usually means a
   *replaced facility* → `retire` + remint, not `update`. Call out each such call in the PR.
   Dry-run: `python publisher/apply.py --decisions decisions.json` (re-fetches live; no write).

3. **Hours.** Every `business_hours` change MUST be re-curated — never ship a regex grid.
   `recurate_hours.py targets/show … --changelog reports/<ts>/changelog.json`, re-parse per
   `docs/hours-schema.md`, `recurate_hours.py set --file refreshed.json`, then dry-run
   `python publisher/backfill_schedule.py --from-curated`.

4. **New onsens (ADDED).** The map seed already identified them (name/area/coords). Mint ids:
   `python .claude/skills/catalog-sync/catalog_sync.py mint --from-staging --commit`.
   **Creating the live Firestore doc (`apply.py add`) is not built yet** — flag each ADDED
   onsen in the PR as needing manual doc-creation **and** an app-repo challenge-pool hand-off.
   Do not attempt to publish a new-onsen doc.

5. **Tests.** `uv run --python 3.12 --with pytest python -m pytest tests/`.

6. **Open the PR** to `master`, committing `decisions.json`, `data/hours_curated.json`, and
   `data/onsen-id-map.json` (if you minted). **Label it `catalog-publish`.** In the body
   include: a summary of the changes, your identity-adjudication calls, and the ADDED-onsen
   flags. The `catalog-dry-run` check posts the authoritative Firestore diff for me to review.
