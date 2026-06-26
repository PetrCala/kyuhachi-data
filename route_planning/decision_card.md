# 九州八十八湯 — trail decision card

*Print this. One page. It survives a dead battery in the Kuju massif; the phone does not.*
*Derived from `handdrawn_loop_analysis.json` + `simulate.py`. Carry it; trust it; confirm at the door.*

---

## The one fact that sets the whole strategy

You pass **~119 onsens on the line** for a target of **88** — about **30 to spare**.
At a realistic **12 h walking day + ~50 min/visit, skip-lean** (never wait overnight, miss
anything closed/late) you **visit ~102 ≥ 88 and finish ~Nov 7, ~25 days early.** Visiting
*everything* and waiting out every closure is the **~50-day / Nov 20** upper bound — you don't.

> **So: skip freely. You are not optimizing — you are collecting. When in doubt, walk on.**
> The day-to-day "visit this / skip that" call almost never threatens the goal. Only two
> things do — the **Nagasaki linchpin** and **finishing healthy**. Guard those.

---

## Decision gate — at each onsen, top to bottom, first match wins

| What you see | Do | Why |
|---|---|---|
| On-line, **open now**, not yet visited | **✅ VISIT** | collect it — in a cluster grab *every* open one, each is its own stamp (no per-area limit) |
| **Closed today** (定休日 weekday) | **🚫 SKIP** | hard block, no judgement needed |
| Arrived **after last entry** | **⌛ SKIP** | don't wait overnight for one onsen |
| Opens **later today**, wait **< ~2 h** | **⏳ WAIT** | a few hours for a morning/midday open is fine |
| Opens only **tomorrow** | **🚫 SKIP** — *unless* it's **波佐見** or the **last of a prefecture** | overnight waits are for all-7 only |
| **Off-line / spur** (not on the line) | **🚫 SKIP** *unless phone-confirmed open today AND you're ahead of pace* | never detour on a guess |
| **不定休** (irregular) | **opportunistic** — visit it if you find it open, never plan around it | luck, not a plan (37 of them) |

**Reading a door (Japanese):** 定休日 = closed day · 不定休 = irregular closure · 最終受付 = last
entry · 営業時間 = hours · 本日休業 = closed today · 無休 = never closes.

---

## 🔴 LINCHPIN — 波佐見 (the only Nagasaki onsen on the route)

> Without it you **lose all-7**, and there is **no backup** — every other Nagasaki onsen is
> off the foot line (Shimabara/Unzen peninsula or offshore Iki).

- **波佐見温泉 はさみ温泉 湯治楼** — stop **#59**, on the line (0.01 km).
- Hours **10:00–22:00**, 最終受付 **21:30** — but **不定休**, so hours alone don't guarantee it's open.
- ☎ **0956-76-9008** — **call 1–2 days ahead** to confirm it's open the day you'll pass.
- If the call says closed: **stop and re-plan** (wifi + `simulate.py`), don't just walk past.
  This is the one onsen worth bending the schedule — even an overnight wait — for.

---

## All-7 prefecture tracker — tick when you visit your first in each

`[ ] 鹿児島`   `[ ] 宮崎`   `[ ] 熊本`   `[ ] 福岡`   `[ ] 佐賀`   `[ ] 長崎(=波佐見)`   `[ ] 大分`

On-line cushion per prefecture: 大分 34 · 鹿児島 27 · 熊本 25 · 福岡 16 · 宮崎 9 · **佐賀 7** · **長崎 1**.
**長崎 = 1 (critical), 佐賀 = 7 (thin)** — don't leave either short. The rest have deep redundancy; skip at will.

---

## Pace & skip-mode

- Default is **skip-mode** from day one. Switch to *patient* (wait for same-day opens) only
  when you're **ahead of pace** or it **completes a prefecture / bags 波佐見**.
- Rough check: **visited ÷ days-elapsed ≥ ~2.5/day** keeps you safely ahead. Behind that two
  days running → tighten to pure skip-mode, drop all spurs and buffers.
- Walk model baked into the plan: **4 km/h loaded, ~50 min/visit (blended), walking day 06:00–18:00 (12 h, ~30–40 km).**
- **Leeway budget:** ~25 days of slack are yours for long stays, rest days, and double-day
  clusters. Rule of thumb: **every +20 min on your average visit ≈ +2–3 days** — even averaging
  2 h per onsen still lands ~mid-Nov. Linger where it's worth it.

---

## ⚠️ Remote stretches — carry food & water BEFORE these (from `difficulty.py`)

- **#12–20 Kirishima highlands** — 55 km no-resupply near 白鳥, big climbs.
- **#30–32 紫尾山地** — **61 km, the longest no-shop stretch on the loop.** Stock up.
- **#35–42 Yatsushiro → Aso south rim** — biggest sustained climb; 40 km coast gap before it.
- **#85–92 Kuju massif — THE crux.** Alpine. **法華院 (#91, ~1,250 m) is FOOT-ACCESS ONLY** —
  treat it as a mountain hut. Stacked no-resupply gaps; cold and early dark in November.
- **#96–100 Yufuin → Beppu** — a climbing finish, not a coast-down; 22 km gap near 塚原.

---

## Optional side-trip — Aso crater (草千里 / 中岳)

**Not** on the route and **not** an onsen — a ~20 km out-and-back climb (+~400 m) from the
地獄/垂玉 junction. Separate file `aso_crater_spur.gpx` (+ `aso_crater_map.html`). Do it only
if comfortably ahead; crater access depends on the volcanic alert level (often ropeway-only).

---

*Start 長崎鼻 (Cape Nagasakibana), Oct 2 · Finish 浜脇温泉 茶房たかさきの湯 (Beppu, #119) ·
Deadline Dec 2 · ~1,205 km. When the phone is dead or has no signal, this card is the plan.*
