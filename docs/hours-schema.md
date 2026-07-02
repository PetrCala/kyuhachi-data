# Onsen business-hours schema

Canonical spec for the published `businessHours` field, owned by this data repo
and consumed by the app (`kyuhachi`). The app **displays** this; it never
computes open/closed from rules (no holiday calendar, no date math).

## Published shape — `/onsens/{kyuhachiId}.businessHours`

```jsonc
{
  "raw": "10:00～22:00\n水曜休…",          // verbatim 88onsen text — ultimate fallback / "original text"
  "schedule": WeeklySchedule | null,        // the base weekly grid (null → no structured grid)
  "exceptions": ScheduleException[],        // caveats rendered under the grid (+ optional machine rule)
  "confidence": "high" | "medium" | "low",  // drives a subtle "hours may vary — confirm" hint
  "lastEntry": "HH:MM"                      // optional — the facility-wide 最終受付 cutoff (evidence-based)
}

WeeklySchedule    = { monday: DaySchedule|null, …, sunday: DaySchedule|null }  // null day = CLOSED
DaySchedule       = { opens: "HH:MM", closes: "HH:MM",  // 24+ = past midnight (e.g. "25:00" = 1 AM)
                      windows?: [{opens, closes}, …] }  // full truth when the day has ≥2 windows
ScheduleException = { en: string, ja: string, rule?: ClosureRule }
```

Every field beyond `raw`/`schedule` is optional and additive — a reader that knows
only the original `{raw, schedule, exceptions:[{en,ja}], confidence}` shape keeps
working unchanged. On a multi-window day, `opens`/`closes` mirror the **first**
window, so a legacy reader shows one *true* window (it can only err in the
false-closed direction, never false-open).

## Guiding principle — never falsely claim *open*

A false **open** costs a wasted trip; a false **closed** just prompts a double-check.
So the structured `schedule` encodes the **guaranteed baseline** (most-restrictive),
and everything uncertain is surfaced as a **visible exception**, never silently assumed:

- **Seasonal hours** → publish the narrower window (latest open, earliest close); note the rest.
- **Monthly closure** (第N曜 / 毎月N日) → leave the weekday *open* in the grid + an exception
  caption carrying the structured `rule` (accurate, not pessimistic — the caveat is right there,
  and computing consumers get the machine-readable twin).
- **Irregular** (不定休) → publish the base grid, cap the published `confidence` at `low`
  (the call-ahead hint), and carry the honest "confirm before visiting" caption with an
  `{"kind": "irregular"}` rule so computing consumers know the grid is advisory.
- **Split sessions** (2部制) → the day's full window list in `windows`; `opens`/`closes`
  mirror the first window for legacy readers.

## Structured closure rules — `exceptions[i].rule`

A rule is the optional **machine-readable twin of its caption** — it lives on the
exception it mirrors, so a rule can never publish without human-readable text.
Three kinds:

```jsonc
{ "kind": "monthlyWeekday",             // closed the Nth <weekday>(s) of each month (第N曜)
  "weeks": [2, 4],                      // 1..5
  "weekday": "thursday",
  "holidayPolicy": "nextDay",           // optional: nextDay | nextWeekday | skip | varies
  "exceptMonths": [3, 8],               // optional: rule does not apply in these months
  "onlyMonths": [1, 5] }                // optional: rule applies only in these months
{ "kind": "monthlyDay", "days": [5, 15, 25] }   // closed these days of each month (毎月N日)
{ "kind": "irregular" }                 // closes unpredictably (不定休) — the grid is advisory
```

`holidayPolicy` maps the stated holiday behaviour: `nextDay` = 祝日の場合は翌日休,
`nextWeekday` = 翌平日休, `skip` = 祝日は営業 (no closure that week), `varies` =
変更あり. Month-dependent statements compose from two rules (e.g. 第1水曜休、
1・5月は第2水曜 → one rule `weeks:[1], exceptMonths:[1,5]` + one rule
`weeks:[2], onlyMonths:[1,5]`).

**Consumer contract:** a rule is a *closure predicate layered on the open grid*.
Consumers MAY compute "closed that day" from it. Computing around
`holidayPolicy`/`varies` without holiday data must degrade to "confirm before
visiting" — never to "open". The app currently renders only `en`/`ja` and ignores
`rule`; the first computing consumer is this repo's route planner.

## Render contract (app)

1. **Base weekly grid** from `schedule` (a `null` day renders as "Closed"/"定休日").
   A day with `windows` renders every window (e.g. "6:00–10:00 / 13:00–22:00");
   a reader that predates `windows` shows `opens`–`closes` (the first window).
2. **Exceptions** — caption list under the grid (e.g. "2nd & 4th Thu closed").
   These are factual schedule notes. This contract specifies only the **text**;
   any visual indicator (icon, emphasis, color) is the app's choice, so it can be
   tuned without a data-repo change. `rule` is ignored for display — captions are
   already the human rendering of it.
3. **"Show original text"** toggle reveals `raw`.
4. `confidence` of `medium`/`low` → surface a "confirm hours" hint. Again, only
   the meaning is contractual here; wording and visual treatment are the app's.
5. `lastEntry` is the logic channel for the cutoff — the caption remains the
   display channel. An app that later builds a styled last-entry element may
   replace the caption row when `lastEntry` is present.

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

This is **enforced**, not just advised: for the clean single-time form,
`onsen_scraper.hours.last_entry_caption` is the one source of the wording, and both
`recurate-hours validate` and the pytest suite fail if an onsen whose source states a
`最終受付` lacks the matching caption — so a re-curation can't silently re-bury it. The
per-bath/per-day forms return `None` there and stay hand-curated.

The **structured** `businessHours.lastEntry` carries the same cutoff as data, and is
**evidence-based only, never inferred**: a curated `lastEntry` is valid only when
`onsen_scraper.hours.single_last_entry` detects exactly that time in the source text
(enforced by `recurate-hours validate` + pytest). Per-bath/per-day cutoffs stay
caption-only. When the cutoff varies by day, the detector yields the first/base
stated time — publishing it errs in the false-closed direction (entry may actually
be possible later), and the caption spells out the variance.

## Source of truth

`data/hours_curated.json` — one-time LLM parse of `business_hours`, hand-reviewed.
Per onsen: `{ publish, status, window, closed, overrides, lastEntry?, exceptions,
confidence, note }`. `window` (and each `overrides` value) is a single
`[open, close]` pair or a chronological list of pairs for split sessions. The
backfill (`publisher/backfill_schedule.py --from-curated`) expands `schedule` from
`window`/`closed`/`overrides` and publishes `schedule` + `exceptions` +
`confidence` + `lastEntry`, diffing against live and writing only changes. The
published `confidence` is the curated (parse) confidence **capped at `low` when an
`irregular` entry publishes a grid** — see `published_confidence`. `note` is
internal (not published).

Ongoing maintenance is the `/recurate-hours` skill (re-parses onsens whose
`business_hours` changed, per this schema).
