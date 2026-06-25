---
name: recurate-hours
description: Refresh the structured business-hours parse (data/hours_curated.json)
  for onsens whose 88onsen business_hours changed. Re-parses the changed onsens
  with the session model (NOT the unreliable regex), merges the refreshed entries,
  validates, and previews the publish. Read-only/offline by default — the curated
  edit and the --commit backfill are the explicit human-gated writes. Use when the
  source hours drift and the catalog needs to catch up.
---

# recurate-hours

The maintenance flow for `data/hours_curated.json` — the source of truth for the
published `businessHours.schedule`. That file was a **one-time LLM parse** of the
free-text `business_hours` column in `data/snapshot.db`. When 88onsen edits an
onsen's hours, the matching curated entry goes stale; this skill re-parses just
the changed onsens and refreshes the file, then publishes.

> This is **Phase 3** of the **`catalog-sync`** pipeline. For a full catalog update,
> start at `catalog-sync`; reach for this skill directly to fix one onsen's hours
> without running the whole loop.

**The re-parse is done by the session model, not by a regex.**
`onsen_scraper/hours.py` exists but is deliberately *not* the source of truth — it
misreads Japanese phrasing (e.g. `翌日休` "closed the next day" was parsed as
日曜/Sunday on hids 151 & 224). The helper here only moves source text **in** and
structured entries **out**; the judgement of how the hours map to the schema is
yours, against [docs/hours-schema.md](../../../docs/hours-schema.md).

## When to use

- A `catalog-diff` run shows `business_hours` changed on one or more onsens.
- You want to fix or improve a specific onsen's curated hours entry by hid.
- New onsens were added and need a curated hours entry from scratch.

Not for: bulk re-parsing everything (the curated file is already hand-reviewed),
or writing any field other than the structured hours.

## The schema (read this first)

[docs/hours-schema.md](../../../docs/hours-schema.md) is canonical. The published
model is `businessHours = { raw, schedule, exceptions:[{en,ja}], confidence }`.
Each curated entry expands into that via `publisher/backfill_schedule.py`:

| Field | Meaning |
|---|---|
| `publish` | `true` → expand a `schedule` grid; `false` → `schedule` null, `raw` only. |
| `status` | why it is/isn't published: `structured`, `irregular`, `monthly`, `multi-window`, `seasonal`, `deferred-annual`. |
| `window` | `[open, close]` base daily window (`HH:MM`, `24+` = past midnight). `null` when not published. |
| `closed` | weekday abbrevs (`mon…sun`) that are fully closed in the base week. |
| `overrides` | `{weekday: [open,close] | null}` for days that differ from `window`. |
| `exceptions` | display-only `{en, ja}` captions (holidays, monthly closures, seasonal notes…). |
| `confidence` | `high` / `medium` / `low` — drives a "hours may vary" hint in the app. |
| `note` | internal-only rationale (NOT published). |

**Guiding principle: never claim *open* when actually closed.** Encode the
guaranteed baseline (most-restrictive) in the grid; surface everything uncertain
as a visible exception, never a silent assumption. Status routing:

- `無休` / explicit weekly closure (`火曜休`, `火・金曜休`, `月～木曜休`) → `structured`,
  `publish:true`.
- **pure** `第N曜` / `毎月N日` monthly closure (no weekly 定休日) → `monthly`,
  `publish:false`, with the closure as a caption. When a monthly closure is
  *layered on top of* a weekly closure, keep `structured`/`publish:true` (the
  weekly day in `closed`) and add the monthly as an exception caption — the
  weekday stays open in the grid (e.g. hid 202: `closed:[wed]` + "Also closed the
  2nd & 4th Thursday").
- `不定休` irregular → `irregular`, `publish:false`, honest "confirm before visiting".
- multi-window (2部制) / strong seasonal swings → `multi-window` / `seasonal`,
  `publish:false`, `window:null`.
- annual-only closure (`1/1`, `元旦`, Dec maintenance) → `deferred-annual`,
  `publish:false` (open-all-week policy pending).

Use the standard bilingual wordings in the schema doc's caption table.

## Steps

1. **Pick the targets.** Either pass explicit hids, or detect drift from a
   `catalog-diff` run (that skill is the change-detection source — do not
   reimplement scraping). After running `catalog-diff`, feed its changelog in:
   `python .claude/skills/recurate-hours/recurate_hours.py targets --changelog reports/<ts>/changelog.json`
   → it lists every onsen whose `business_hours` changed (old → new), flags added
   onsens (need a fresh scrape first), and prints the bare `target hids` line.
2. **Re-parse each target.** Dump the source text + current entry:
   `… recurate_hours.py show <hids…> [--changelog reports/<ts>/changelog.json]`
   (`--changelog` shows the freshly-scraped NEW text; without it, the text comes
   from `snapshot.db`). For each, **you** produce the refreshed entry exactly per
   the schema above — bilingual `{en,ja}` exceptions, `window`/`closed`/`overrides`
   for the base week, correct `status` routing, never asserting open from silence.
3. **Merge + validate.** Write the refreshed entries (a `{hid: entry, …}` JSON
   object) back into the curated file:
   `… recurate_hours.py set --file refreshed.json` (or `--hid N --file one.json`
   for a single bare entry; add `--dry-run` to preview the merge first). `set`
   validates every entry's shape and **refuses to write** on any problem, then
   preserves the file's exact formatting + numeric key order. Then run the suite:
   `uv run --python 3.12 --with pytest python -m pytest tests/`
   (`… recurate_hours.py validate` is a faster local pre-check of the same invariants).
4. **Preview, then publish on approval.** Dry-run the backfill:
   `uv run --python 3.12 python publisher/backfill_schedule.py --from-curated`
   — it reads each live doc, diffs the three structured sub-fields, and reports
   what *would* change. Present that diff. **Only on explicit approval**, commit:
   `… backfill_schedule.py --from-curated --commit` (needs gcloud Application
   Default Credentials; run `gcloud auth application-default login` if 401). The
   commit also bumps `catalog_meta/current.version` so the app refetches.

## Subcommands

| Command | Effect |
|---|---|
| `targets --changelog PATH [--json]` | List onsens whose `business_hours` changed in a catalog-diff changelog; print the target hids. Read-only. |
| `show <hids…> [--changelog PATH]` | Dump each hid's `business_hours` text (new-scrape if `--changelog`, else snapshot) + its current curated entry. Read-only. |
| `set (--file PATH \| --json STR \| stdin) [--hid N] [--dry-run]` | Merge refreshed entries into `hours_curated.json` (reads stdin if neither flag given). Validates shape; writes nothing on failure. **The only writer.** |
| `validate` | Re-check every curated entry against the schema invariants + report snapshot coverage. Read-only. |

## Guarantees

- **Read-only by default.** Opens `snapshot.db` `mode=ro`. Only `set` writes, and
  it writes **only** `data/hours_curated.json` — never the snapshot DB, never
  Firestore.
- **Two explicit, human-gated writes:** the `set` merge, and the
  `--from-curated --commit` backfill. Everything else is offline and reversible.
- **No silent corruption.** `set` rejects malformed entries up front and re-emits
  the file byte-stably (a no-op `set` produces an identical file); the pytest
  suite is the final gate.
- **The regex is never the source of truth.** `onsen_scraper/hours.py` is not used
  to populate entries here — the session model does the parse.

## What NOT to do

- Don't let the regex parser (`onsen_scraper/hours.py`) author curated entries.
- Don't `--commit` without showing the dry-run diff and getting explicit approval.
- Don't edit any field beyond the structured hours, and don't touch the snapshot
  DB or Firestore from this skill.
- Don't assume "no stated closed day" means open daily — that's the exact trap the
  schema's never-claim-open principle guards against.
