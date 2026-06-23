---
name: cost-analysis
description: Estimate the admission cost of completing the 88-onsen challenge from
  the catalog's admission fees. Reports pool stats, a Monte Carlo of a random
  88-visit total, and the cheapest/priciest possible 88. Read-only — writes
  nothing to the snapshot DB or Firestore. Use to answer "what does the challenge
  cost" or to sanity-check parsed fees before publishing a numeric adultFee.
---

# cost-analysis

Read-only cost estimator for the 88-onsen challenge. Parses an **adult
single-visit admission fee** out of each onsen's free-text `admission_fee`
(`data/snapshot.db`), then reports how much money completing the challenge takes.

It answers two different questions:

- **"What would a random run cost?"** — a Monte Carlo: pick 88 onsens at random,
  sum the fees, repeat over many trials, average. This is the expected cost with
  no route planning.
- **"What are the real bounds?"** — the cheapest-possible and priciest-possible
  88 (sum of the 88 lowest / highest fees), since a real challenger *chooses*
  which eligible onsens to visit.

## When to use

- "How much does the 88-onsen challenge cost?" (in yen, or any currency via `--rate`).
- Sanity-check the fee parse before the catalog publisher writes a numeric
  `adultFee` field — `--show-prices` dumps the extracted value + method per onsen.

## Steps

1. **Run it** from the repo root:
   `python .claude/skills/cost-analysis/cost_analysis.py`
   (defaults: 88 picks, 30 trials, seed 88 — reproducible).
2. **Convert currency** with `--rate` (yen multiplier) and `--currency`:
   `... --rate 0.130899 --currency CZK`. Rates are passed in, not fetched — the
   sandbox has no network and the rate shouldn't be silently stale.
3. **Audit the parse** with `--show-prices` if a number looks off, or `--json`
   for machine output. `--svg cost.svg` writes a dependency-free bar chart of the
   trial totals.
4. **Propose, don't apply.** This skill only reports. The durable fix is a
   numeric `adultFee` on the published catalog (see CAVEATS) — that's a separate,
   explicit change to the publisher.

## How the fee is parsed

`admission_fee` is free Japanese text (e.g. `大人 350円（土日祝450円）`). The
parser NFKC-folds it (full-width → half-width so `１，０２０円` reads as `1,020`),
then extracts the **adult weekday walk-in** price by priority:

| Method | Rule |
|---|---|
| `adult` | first `…円` after a 大人 / おとな marker |
| `jhs+` | first `…円` after 中学生以上 (adult-equivalent when no 大人) |
| `free` | 無料 with no yen figure → ¥0 |
| `fallback` | first `…円` on the page (age-gated or private-bath-only facilities) |
| `corrected` | hand-fixed in `CORRECTIONS` (see below) |

Three ids are hand-corrected in `CORRECTIONS` because the text defeats the
heuristic or has no individual walk-in price:

- **151** → ¥700 (heuristic grabbed the 70才以上 senior 500; adult is 13才以上 700)
- **192** → ¥1,200 (private-bath-only; the solo "一人湯 ￥1,200" rate)
- **239** → ¥600 (heuristic grabbed a 貸切 private-bath 1,200; walk-in is 中学生以上 600)

## CAVEATS

- **Weekday adult only.** Weekend/holiday surcharges (¥50–200 at many onsen) and
  child/senior rates are ignored.
- **~6 private/family-bath-only facilities** have no individual admission; they
  fall through to `fallback` = the lowest listed room rate (what a solo visitor
  pays). One onsen is "free with a cafe purchase" → ¥0.
- **Heuristic, not authoritative.** This parse lives in the skill. The catalog
  doesn't yet publish a numeric fee; when it does, the app and this skill should
  read that field instead of re-parsing text. Until then, treat figures as ±10%.
- Sampled from the **148** onsens with a fee in the snapshot, not the full
  eligible pool.

## Arguments

| Flag | Effect |
|---|---|
| `--pick N` | Onsens per trial. Default 88. |
| `--trials N` | Number of Monte Carlo trials. Default 30. |
| `--seed N` | RNG seed. Default 88 (reproducible). |
| `--rate R` | Multiply every yen figure by R (e.g. `0.130899` → CZK). |
| `--currency C` | Currency label when `--rate` is given. Default `CZK`. |
| `--show-prices` | Dump per-onsen extracted fee + method. |
| `--svg PATH` | Write a bar chart of the trial totals (no dependencies). |
| `--json` | Machine-readable output. |
| `--db PATH` | Snapshot DB path. Default `data/snapshot.db`. |

## Guarantees

- Read-only. Opens the snapshot DB `mode=ro`. No Firestore writes, no DB writes.
- Deterministic for a given `--seed`.
- Pure stdlib (sqlite3, random, re, statistics, unicodedata) — no new deps.
