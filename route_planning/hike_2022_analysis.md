# The 2022 hike as a walk model for Kyushu-88

*Source: `data/hike_2022_japan.xlsx` ("Statistics - Hike across Japan"), the hiker's own
day log. Regenerate everything here with `python route_planning/analyze_2022_hike.py`
(writes `hike_2022_summary.json`).*

Why this file exists: `strava_walk_summary.json` measures **pace on day hikes** (median
5.05 km/h moving, 3.97 km/h elapsed). It cannot measure the thing that decides whether
Kyushu-88 finishes: **what happens on day 40**. The 2022 walk across Japan can, and it
ends on Kyushu in early November, in the same daylight the Kyushu-88 walk will have.

---

## The trip

**2,634 km on foot, 19 Aug to 3 Nov 2022, 77 calendar days.** Hokkaido to Kyushu,
across four islands, soaking on 65 of the 77 days.

| | |
|---|---|
| km per calendar day | **34.2** (rest days included) |
| km per walking day | **35.6** |
| walking days / rest days | 74 / 3 |
| walking-day distance | median **36 km**, p10 24, p90 48, max 55 |
| rolling 7-day block | median **243 km**, p10 215, max 293 |
| steps | 3,656,809 total; 1,408 steps/km |
| weight | 69.0 to 65.7 kg (min 63.7); **-4.3 kg in the first 3 weeks**, then stable |

---

## Seven findings that change the plan

### 1. The sustainable number is 34 km per calendar day, and it is remarkably flat

Every single 7-day block of the trip landed between **210 and 293 km**. Not one bad
week, not one blow-up week. Split into thirds: 32.7, 36.3, 33.6 km/calendar day. This
is a hiker with a very narrow output band, which is exactly what makes a 60-day plan
predictable. Plan on 34 and the variance is in the terrain, not in the legs.

### 2. Rest days are almost nonexistent; short days do the recovery

**3 zero-km days in 77** (Sep 3, Sep 20, Oct 29), one roughly every 26 days. The longest
unbroken walking streak was **38 days**. Each rest day followed a big day (38, 36, 44 km)
and was followed by a full day again (35, 48, 36 km), so a zero day is a hard reset, not
a taper.

Recovery instead happens through **short days**: 8 days of 11 to 24 km, scattered through
the trip. That is the real pattern to build into the schedule. Do not pencil in weekly
rest days he will not take. Pencil in **20 km days**.

### 3. An onsen does not cost a day distance

Bath days averaged **36.6 km**; days without a bath averaged **30.0 km**. The sign is the
opposite of the intuition, because the dry days were the odd short ones, not the other way
round. On 97% of the Honshu section he walked a full day *and* soaked.

This is the single most reassuring finding for Kyushu-88: soaking is his default day
structure, not an interruption to it. What Kyushu-88 adds is not "a bath" but **three or
four baths mid-walk**, each with a door time to hit. That is a scheduling problem, not a
stamina problem.

### 4. Big days are available, and they are not free

23 days over 40 km, 6 over 50 km, max 55. But the day after a 45+ km day averaged
**34.7 km**, i.e. right back to normal, and only **2 back-to-back 40+ pairs** in 77 days.
Read that as: a 45 to 50 km day is a tool he can reach for roughly once a week to buy
back schedule, and it costs nothing the next day, but he does not stack them.

### 5. Break-in costs about 2.6 km/day for two weeks

First 14 walking days: 33.5 km/d. After that: 36.1 km/d. Last 14 days: 36.9 km/d, the
strongest of the trip, i.e. **no end-of-trip decay at all** over 77 days. The Kyushu-88
walk is shorter than that, so fatigue collapse is not the risk to plan against. The
opening two weeks are.

Weight says the same thing louder: **-4.3 kg in the first three weeks**, then flat for
the remaining eight. The body absorbed the load early and then held.

### 6. The Kyushu section in this exact season held up

Oct 24 to Nov 3 2022, on Kyushu: 356 km in 11 days, **32.4 km/calendar day** (35.6 per
walking day) including one rest day, with a **51 km day on Nov 1**. Daylight in Kyushu in
early November runs roughly 06:40 to 17:20, about 10.5 hours, and he still turned in
35 km walking days. Some of that was walked in the dark, and it worked.

Kyushu was the trip's slowest island per calendar day (32.4) but not per walking day
(35.6), and the difference is one rest day out of eleven.

### 7. Stride confirms road walking, not trail

1,408 steps/km median (about a 0.71 m stride), p10 1,259 and p90 1,545. The high end
marks the climbing days. Kyushu-88 is a road route with ~14,000 m of ascent, so expect
the upper half of that band on the Kirishima, Aso and Kuju sections.

---

## The calibrated model

The 2022 log has no clock, so it cannot set km/h. Combined with Strava's elapsed pace it
sets the thing the scheduler consumes, **how long a day is**:

- median **36 km day = 9.1 h door to door** (7.1 h moving)
- p90 **48 km day = 12.1 h door to door**

`config.py` currently runs `SPEED_KMH = 4.0` inside a 12-hour window (06:00 to 18:00).
That sits between Strava's moving 5.05 and elapsed 3.97, so the window already prices in
breaks, and 12 hours is exactly the p90 day. **The existing walk model is validated, not
contradicted.** Its output, ~31.7 km per effective walking day in the packaged schedule,
is about 8% under his demonstrated 34.2, which is the right direction to be wrong given
Kyushu-88's ascent and its 119 door times.

### Distance floor for the 1,205 km route

| pace basis | km/calendar day | days of pure walking |
|---|---|---|
| Oct/Nov 2022 mean | 34.2 | **35.2** |
| whole-trip 2022 mean | 34.2 | 35.2 |
| plateau pace, rest day every 10 | 32.5 | 37.1 |

Against **61 calendar days available** (Oct 2 to Dec 2 2026).

The gap between 35 days and 61 is the whole planning question. It is not spent on walking.
It is spent on **119 onsen visits at ~50 min each (~99 h, about 8 walking days of standing
still)** and on **opening hours**: the packaged patient schedule burns 12 idle days waiting
out closures. Legs are not the binding constraint on this trip. Doors are.

---

## What this data cannot tell us

- **No hours per day.** Start and finish times, break structure and night walking are all
  absent. Day length above is inferred from Strava's elapsed pace.
- **No elevation.** 2022 ascent is unrecorded, so it cannot calibrate the Naismith
  penalty; `CLIMB_MIN_PER_M` stays at the textbook 0.10 min/m.
- **No pack weight, weather or surface.**
- **One data point on rest.** Three rest days is enough to say "he does not take many",
  not enough to model when he needs one.
- The workbook's own `Simple stats` sheet reports 64 onsen days; the day rows give **65**
  (the Hokkaido cell is off by one). Numbers here come from the day rows.

---

## Carry into the Oct/Nov plan

1. Pace the schedule at **34 km/calendar day**, not 30, and not 40.
2. Build recovery as **20 to 24 km days**, not zero days. Budget roughly one per week and
   one true zero day per month.
3. Treat **45 to 50 km** as a once-a-week recovery tool for buying back a slipped day.
4. **Start soft**: 28 to 30 km days for the first ten days, then step up. That is the
   measured break-in cost, and Kyushu-88's first big climb (Kirishima, stops 12 to 20)
   lands inside exactly that window.
5. Expect the first three weeks to take **4 kg** off. Plan food accordingly; the plateau
   after it is real.
6. Plan the day around **door times, not distance**. Distance is the solved part.
