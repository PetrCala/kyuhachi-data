<!--
For a catalog-publish PR (decisions / curated hours), keep the checklist below and label
the PR `catalog-publish`. For any other PR, you can delete this template.
-->

## Summary



## Catalog publish checklist

- [ ] **Identity adjudicated** — any onsen with ≥4 changed material fields is handled as
      `retire` + remint (replaced facility), not `update`. List them:
- [ ] **Hours re-curated** — every changed `business_hours` was re-parsed into
      `data/hours_curated.json` (no regex grid shipped).
- [ ] **Dry-run reviewed** — the `catalog-dry-run` check posted its Firestore diff and it
      matches intent.
- [ ] **ADDED onsens flagged** — new onsens are minted + baselined, but their live doc is
      created manually (pending `apply.py add`) and challenge-pool membership is an
      app-repo hand-off. List any ADDED onsens:
- [ ] Tests pass (`uv run --python 3.12 --with pytest python -m pytest tests/`).

Merging this PR triggers the gated `catalog-publish` workflow (paused at the `production`
environment approval before any live write).
