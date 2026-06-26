# Onsen business-hours schema

Canonical spec for the published `businessHours` field, owned by this data repo
and consumed by the app (`kyuhachi`). The app **displays** this; it never
computes open/closed from rules (no holiday calendar, no date math).

## Published shape — `/onsens/{kyuhachiId}.businessHours`

```jsonc
{
  "raw": "10:00～22:00\n水曜休…",          // verbatim 88onsen text — ultimate fallback / "original text"
  "schedule": WeeklySchedule | null,        // the base weekly grid (null → no structured grid)
  "exceptions": LocalizedText[],            // display-only caveats, rendered under the grid
  "confidence": "high" | "medium" | "low"   // drives a subtle "hours may vary — confirm" hint
}

WeeklySchedule = { monday: DaySchedule|null, …, sunday: DaySchedule|null }  // null day = CLOSED
DaySchedule    = { opens: "HH:MM", closes: "HH:MM" }   // 24+ = past midnight (e.g. "25:00" = 1 AM)
LocalizedText  = { en: string, ja: string }
```

## Guiding principle — never falsely claim *open*

A false **open** costs a wasted trip; a false **closed** just prompts a double-check.
So the structured `schedule` encodes the **guaranteed baseline** (most-restrictive),
and everything uncertain is surfaced as a **visible exception**, never silently assumed:

- **Seasonal hours** → publish the narrower window (latest open, earliest close); note the rest.
- **Monthly closure** (第N曜) → leave the weekday *open* in the grid + add an exception caption
  (accurate, not pessimistic, and not misleading — the caveat is right there).
- **Irregular** (不定休) → no grid; an honest "confirm before visiting" caption.

## Render contract (app)

1. **Base weekly grid** from `schedule` (a `null` day renders as "Closed"/"定休日").
2. **Exceptions** — caption list under the grid (e.g. "2nd & 4th Thu closed").
   These are factual schedule notes. This contract specifies only the **text**;
   any visual indicator (icon, emphasis, color) is the app's choice, so it can be
   tuned without a data-repo change.
3. **"Show original text"** toggle reveals `raw`.
4. `confidence` of `medium`/`low` → surface a "confirm hours" hint. Again, only
   the meaning is contractual here; wording and visual treatment are the app's.

If `schedule` is `null`, show `raw` (+ exceptions) only. `exceptions` may be empty.

## Caption conventions

Exceptions are short, factual, bilingual. Standard wordings by category:

| Category | en | ja |
|---|---|---|
| Last entry (最終受付) | Last entry by 21:00 | 最終受付 21:00 |
| Open on holidays | Open on public holidays | 祝日は営業 |
| Holiday → next day | If the closing day is a public holiday, it closes the next day instead | 定休日が祝日の場合は翌日休 |
| Monthly closure | Also closed the 2nd & 4th Thursday | 第2・第4木曜も休 |
| Monthly (raw, no grid) | Closed the 1st Tuesday each month | 毎月第1火曜休 |
| Seasonal hours | Winter (Nov–Apr) until 19:00 | 冬期（11〜4月）は19:00まで |
| Irregular | Irregular closing days — confirm before visiting | 不定休 — 事前にご確認ください |
| Confirm by phone | Call ahead to confirm | 事前に電話でご確認ください |
| Split sessions (raw) | Open in separate sessions — see original text | 時間帯が分かれます — 元の表記をご確認ください |
| Partial day | Tuesday: bathing only after 16:00 | 火曜は16:00以降のみ入浴可 |
| Annual only | Open year-round (closed only Jan 1) | 通年営業（1/1のみ休） |

The **last-entry** (`最終受付`) caption is the one mechanical case: 88onsen states it
inline in the `business_hours` text (`…（最終受付21:00）`), where it is otherwise hidden
in the "show original text" fallback. Carry it forward as a visible caption — last entry
is a hard cutoff that changes whether a trip is worth making, so it earns the same
billing as the other tips. List it first. When the cutoff differs by bath or by day,
spell that out (e.g. `Last entry: main bath 19:30, family bath 19:00`).

## Source of truth

`data/hours_curated.json` — one-time LLM parse of `business_hours`, hand-reviewed.
Per onsen: `{ publish, status, window, closed, overrides, exceptions, confidence, note }`.
The backfill (`publisher/backfill_schedule.py --from-curated`) expands `schedule` from
`window`/`closed`/`overrides` and publishes `schedule` + `exceptions` + `confidence`,
diffing against live and writing only changes. `note` is internal (not published).

Long-term maintenance (a `/recurate-hours` skill that re-runs the LLM parse for onsens
whose `business_hours` changed) is written against THIS schema — out of scope until the
structure ships.
