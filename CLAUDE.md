# kyuhachi-data — Claude Context

## What this repo is

The **private data repo** for the 九州八十八湯 (Kyushu 88 onsen) app. It owns the
onsen **catalog source of truth** and everything upstream of Firestore: scraping
[88onsen.com](https://www.88onsen.com), assigning the stable **`kyuhachiId`** for
every onsen, and publishing the catalog to Firestore.

The app lives in a **separate repo**
([`kyuhachi`](https://github.com/PetrCala/kyuhachi)) — the two-repo split. The app
never sees upstream ids; it reads only the published catalog. Don't move app/UI
concerns here, or catalog/id concerns into the app repo.

## Locked decisions (do not challenge without instruction)

- **Stable ids.** Every onsen has a `kyuhachiId` (UUID) that never changes. Upstream
  88onsen ids (`hid`) are unstable and live ONLY in this repo. This repo is solely
  responsible for assigning and maintaining them.
- **Onsen documents are never deleted.** A removed onsen gets `isActive: false`.
- **Catalog snapshots are frozen per challenge** in the app. Catalog changes never
  mutate existing user challenges — a reseed cannot rewrite history.
- **Be a polite scraper.** Delay, exponential backoff, browser UA. Sample, don't hammer.
- **The regex never authors hours.** The published weekly schedule comes only from the
  LLM-curated hours, never from the fallback parser.
- **Name readings are generated, never hand-edited.** Each onsen's `nameKana` reading
  has no upstream source — it's machine-generated and folded to **hiragana**, the hard
  contract the app's gojūon name sort relies on (katakana/kanji/romaji would break it).
- **Visit, not soak/bank.** The unit of challenge progress is a **visit** — the app's
  challenge model is "completion = unique eligible *visits* ≥ 88" (see the
  [`kyuhachi`](https://github.com/PetrCala/kyuhachi) repo's `CLAUDE.md`). In code, docs,
  and route outputs, an onsen that counts toward the 88 is **visited**, and the running
  tally is **visits/visited**. The per-onsen dwell time is `VISIT_MIN`. The words
  "bank/banked" and "soak/soaked" are not used anywhere in this repo.
- **Every live write is human-gated** and runs a dry-run first.

## Updating the catalog

The [`catalog-sync`](.claude/skills/catalog-sync/SKILL.md) skill is the **single
entry point** for any onsen-data update. Ask to "update / sync the onsen catalog" and
it runs the whole loop — detect what changed → publish to Firestore → retire/mint →
advance the baseline — gating every write. Start there and follow its phases; don't
reinvent the sequence.

It orchestrates the focused, single-purpose skills, each usable on its own:
[`catalog-diff`](.claude/skills/catalog-diff/SKILL.md) (read-only "what changed"),
[`recurate-hours`](.claude/skills/recurate-hours/SKILL.md) (re-parse changed hours),
and [`cost-analysis`](.claude/skills/cost-analysis/SKILL.md) (fee sanity-check). The
skills are self-documenting — read the relevant `SKILL.md` rather than relying on any
commands restated elsewhere.

The GitHub-native automation (operator-as-approver) is documented in
[`.github/CATALOG_AUTOMATION.md`](.github/CATALOG_AUTOMATION.md).

## Structure

- `onsen_scraper/` — fetch + parse 88onsen detail pages and the `/map` seed; derive fees/hours and generated name readings.
- `publisher/` — surgical, dry-run-by-default Firestore writers. Never a clean-slate wipe.
- `data/` — the diff baseline, the `hid → kyuhachiId` map, and the curated hours.
- `.claude/skills/` — the operational tools above. **Start here for any update.**
- `docs/` — the published-schema contracts and roadmap.

The 88onsen DOM/selectors and per-field coverage are audited in the **app repo**
(`docs/onsen-source-field-audit.md`); `onsen_scraper/` implements them.

## What NOT to do

- Don't write user/challenge/visit data — that's the app's domain.
- Don't delete onsen documents (use `isActive: false`) or change a `kyuhachiId`.
- Don't let `catalog-diff` mutate the snapshot or Firestore — it is read-only by contract.
- Don't let the fallback regex author a published schedule — only curated hours do.
- Don't advance the baseline before the publish succeeds — you'd erase the diff you're acting on.

## Delivering changes

Deliver code changes as an open PR against `master` (branch, commit, push,
`gh pr create`), never a direct push to `master`. Skip for read-only sessions.
