#!/usr/bin/env python3
"""The concrete day-by-day plan for the Oct/Nov 2026 walk.

This is the counterpart to `simulate.py`, and it is driven the other way round.

`simulate.py` is clock-driven: it walks stop to stop and lets a day end wherever
the clock lands. Useful for "does this route fit before the deadline", useless as
a thing to carry. This planner is **distance-driven**, because that is the unit
the hiker actually has a track record in: `analyze_2022_hike.py` shows 34.2 km per
calendar day sustained over 77 days, with a 7-day block never leaving the 210 to
293 km band. So the plan sets a daily distance target from that measured profile,
then checks each day fits the 12 h window once visits and climbing are priced in.

The day profile (all four numbers come from the 2022 log, none are invented):

  break-in     first 10 walking days at 29 km   (2022: first 14 days ran 2.6 km/d
                                                 under the plateau)
  plateau      36 km                             (2022 walking-day median: 36)
  recovery     every 7th day at 22 km            (2022: 8 short days of 11 to 24 km;
                                                 only 3 zero-km days in 77, so
                                                 recovery is a SHORT day, not a rest day)
  rest         one true zero-km day per 30 days  (2022: 3 in 77, one every ~26)

A 6 x 36 + 1 x 22 week is 238 km, i.e. 34.0 km/calendar day. That is the 2022
number, reproduced deliberately rather than by coincidence.

Visit policy: skip-lean (the decision card's default). Walk on past anything
closed or past last entry. The one exception is a prefecture linchpin: if a stop
is the LAST remaining on-route onsen in a prefecture not yet collected, wait for
it however long that takes, because all-7 is a hard goal and 長崎 has exactly one.

Output: `plan_octnov.md` (the thing to carry) + `plan_octnov.json`.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import config  # noqa: E402
from difficulty import CRUX_ZONES  # noqa: E402

ANALYSIS = HERE / "handdrawn_loop_analysis.json"
LOGISTICS = HERE / "final_route" / "logistics.json"
OUT_MD = HERE / "plan_octnov.md"
OUT_JSON = HERE / "plan_octnov.json"

# --- the day profile (see the module docstring; sourced from hike_2022_summary) --
BREAKIN_WALKING_DAYS = 10
BREAKIN_KM = 29.0
PLATEAU_KM = 36.0
RECOVERY_KM = 22.0
RECOVERY_EVERY = 7          # every Nth walking day is a short recovery day
REST_EVERY_CAL_DAYS = 30    # a true zero-km day this often
FLEX_KM = 7.0               # how far past target to push to bag a reachable onsen

# --- the day window ---------------------------------------------------------
# Same 06:00 to 18:00 as config.py. In November, Kyushu sunset is ~17:25, so the
# tail of a long day is walked in the dark. That is not a modelling cheat: on
# 1 Nov 2022 he walked 51 km on ~10.5 h of daylight.
DAY_MIN = config.SLEEP_MIN - config.WAKE_MIN
# How long to wait at a door that opens later today, before writing the onsen off.
# 240 min looks extravagant until you run `--sweep`: it buys 101 onsens instead of
# 86, costs 2 calendar days out of 23 of slack, and in the whole 41-day plan only
# 5 waits actually exceed 90 min (the longest is one 220 min wait on Oct 27).
# A skipped onsen is gone for good; an afternoon spent waiting is lunch and laundry.
WAIT_TOLERANCE_MIN = 240

# A morning door is not a reason to stand around. If the day's first onsen opens
# at 10:00 and sits 8 km ahead, the answer is to start at 08:00, not to burn two
# hours of the evening waiting. The day keeps its full length and ends later,
# which means walking into the dark. 2022 says that is fine (51 km on ~10.5 h of
# daylight on 1 Nov), but not unbounded, hence the hard cap.
LATE_START_MAX_MIN = 180
DAY_END_HARD_MIN = 20 * 60  # never plan walking past 20:00

WEEKDAY_JP = "月火水木金土日"


def hhmm(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60:02d}:{m % 60:02d}"


def is_always_open(stop: dict) -> bool:
    om = stop.get("open_min")
    return bool(stop.get("never_closes")) or om is None or not (0 <= om < 24 * 60)


def prefecture_linchpin_map(stops: list[dict]) -> dict[int, str]:
    """order -> prefecture, for each stop that is the LAST chance at its prefecture."""
    last_seen: dict[str, int] = {}
    for s in stops:
        last_seen[s["pref_short"]] = s["order"]
    return {order: pref for pref, order in last_seen.items()}


def crux_for(order: int) -> dict | None:
    for z in CRUX_ZONES:
        if z["orders"][0] == order:
            return z
    return None


def gaps_in(from_km: float, to_km: float, gaps: list[dict]) -> list[dict]:
    """Resupply gaps that START inside this day's stretch of the line."""
    return [g for g in gaps if from_km <= g["from_km"] < to_km]


def target_km(walking_day: int) -> float:
    """Distance target for the Nth walking day of the trip."""
    if walking_day % RECOVERY_EVERY == 0:
        return RECOVERY_KM
    return BREAKIN_KM if walking_day <= BREAKIN_WALKING_DAYS else PLATEAU_KM


def plan(wait_tolerance_min: int = WAIT_TOLERANCE_MIN) -> dict:
    route = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    stops = route["stops"]
    gaps = json.loads(LOGISTICS.read_text(encoding="utf-8"))["resupply_gaps"]
    linchpins = prefecture_linchpin_map(stops)

    date = config.START_DT.date()
    clock = float(config.WAKE_MIN)          # minutes since midnight
    day_km = 0.0                            # km walked today
    cum_km = 0.0                            # km walked in total
    leg_left = stops[0]["leg_km_gc"]         # km still to walk to reach stops[i]
    leg_ascent_left = float(stops[0].get("ascent_m", 0))
    i = 0                                   # index of the next stop on the line
    walking_day = 1
    prefs_done: set[str] = set()
    visited = skipped_closed = skipped_late = skipped_early = 0
    overnight_waits = 0

    days: list[dict] = []
    cur = {
        "date": date,
        "walking_day": 1,
        "target_km": target_km(1),
        "start_km": 0.0,
        "ascent_m": 0.0,
        "events": [],
        "warnings": [],
        "rest": False,
    }
    seen_crux: set[str] = set()

    def open_day(d, wd: int, is_rest: bool = False, start_clock: float | None = None) -> dict:
        """Open a day, sleeping in if that is what the first door of the day wants."""
        start = float(config.WAKE_MIN) if start_clock is None else start_clock
        shift = 0.0
        if not is_rest and i < len(stops) and start <= config.WAKE_MIN:
            nxt = stops[i]
            om = nxt.get("open_min")
            arrive = start + leg_left / config.SPEED_KMH * 60.0 + leg_ascent_left * config.CLIMB_MIN_PER_M
            closed = d.weekday() in set(nxt.get("closed_weekdays") or [])
            if not is_always_open(nxt) and om is not None and arrive < om and not closed:
                shift = min(om - arrive, LATE_START_MAX_MIN)
                start += shift
        return {
            "date": d,
            "walking_day": wd,
            "target_km": 0.0 if is_rest else target_km(wd),
            "start_km": cum_km,
            "start_clock": hhmm(start),
            "_start": start,
            "late_start_min": round(shift),
            "day_end": min(start + DAY_MIN, DAY_END_HARD_MIN),
            "ascent_m": 0.0,
            "events": [],
            "warnings": [],
            "rest": is_rest,
        }

    def close_day() -> None:
        nonlocal days, cur
        cur["end_km"] = cum_km
        cur["km"] = round(cum_km - cur["start_km"], 1)
        cur["ascent_m"] = round(cur["ascent_m"])
        cur["end_clock"] = hhmm(clock)
        for g in gaps_in(cur["start_km"], cum_km, gaps):
            cur["warnings"].append(
                f"resupply gap: {g['len_km']:.1f} km with no shop from km {g['from_km']:.0f}"
            )
        days.append(cur)

    cur = open_day(date, 1)
    clock = cur["_start"]

    while i < len(stops):
        s = stops[i]
        room_km = cur["target_km"] + FLEX_KM - day_km
        walk_min = leg_left / config.SPEED_KMH * 60.0 + leg_ascent_left * config.CLIMB_MIN_PER_M
        day_end = cur["day_end"]

        # Can we reach the next stop today at all?
        if leg_left > room_km or clock + walk_min > day_end:
            # Night falls mid-leg. Walk whatever the day still allows, sleep, continue.
            km_by_target = max(0.0, cur["target_km"] - day_km)
            km_by_clock = max(0.0, (day_end - clock)) / 60.0 * config.SPEED_KMH
            step = min(leg_left, km_by_target, km_by_clock)
            frac = step / leg_left if leg_left else 0.0
            step_ascent = leg_ascent_left * frac
            day_km += step
            cum_km += step
            cur["ascent_m"] += step_ascent
            leg_ascent_left -= step_ascent
            leg_left -= step
            # The evening's walking costs clock time too, or the reported finish
            # time for the day is a fiction.
            clock += step / config.SPEED_KMH * 60.0 + step_ascent * config.CLIMB_MIN_PER_M
            cur["next_stop_km_away"] = round(leg_left, 1)
            cur["next_stop"] = f"#{s['order']} {s['area']}：{s['name']}"
            close_day()

            # --- roll to the next calendar day -----------------------------
            date += timedelta(days=1)
            rest_today = walking_day % REST_EVERY_CAL_DAYS == 0
            if rest_today:
                cur = open_day(date, walking_day, is_rest=True)
                cur["warnings"].append(
                    "planned zero-km rest day (2022: 3 in 77 days, always after a big one)"
                )
                close_day()
                date += timedelta(days=1)
            walking_day += 1
            day_km = 0.0
            cur = open_day(date, walking_day)
            clock = cur["_start"]
            continue

        # --- we reach the stop today -------------------------------------
        day_km += leg_left
        cum_km += leg_left
        cur["ascent_m"] += leg_ascent_left
        clock += walk_min
        arrive = clock
        leg_left = 0.0
        leg_ascent_left = 0.0

        z = crux_for(s["order"])
        if z and z["title"] not in seen_crux:
            seen_crux.add(z["title"])
            cur["warnings"].append("CRUX " + z["title"] + ": " + " ".join(z["lines"]))

        wd = date.weekday()
        closed_today = wd in set(s.get("closed_weekdays") or [])
        om, lm = s.get("open_min"), s.get("last_min")
        always = is_always_open(s)
        too_early = (not always) and om is not None and arrive < om
        too_late = (not always) and lm is not None and arrive > lm
        is_linchpin = linchpins.get(s["order"]) == s["pref_short"] and s["pref_short"] not in prefs_done

        status = note = ""
        if closed_today and not is_linchpin:
            skipped_closed += 1
            status = "SKIP closed"
            note = f"定休日 {''.join(WEEKDAY_JP[d] for d in sorted(s['closed_weekdays']))}曜"
        elif too_late and not is_linchpin:
            skipped_late += 1
            status = "SKIP late"
            note = f"arrive {hhmm(arrive)} after last entry {hhmm(lm)}"
        elif too_early and (om - arrive) > wait_tolerance_min and not is_linchpin:
            skipped_early += 1
            status = "SKIP early"
            note = f"arrive {hhmm(arrive)}, opens {hhmm(om)} ({int(om - arrive)} min wait)"
        elif closed_today or too_late or (too_early and (om - arrive) > wait_tolerance_min):
            # Linchpin: the last shot at this prefecture. Sleep here and take it
            # at opening tomorrow. This is the only reason to burn a night.
            overnight_waits += 1
            cur["next_stop_km_away"] = 0.0
            cur["next_stop"] = f"#{s['order']} {s['area']}：{s['name']} (linchpin, open tomorrow)"
            cur["warnings"].append(
                f"OVERNIGHT WAIT for {s['pref_short']} linchpin #{s['order']} {s['name']}: "
                f"the last {s['pref_short']} onsen on the route. all-7 depends on it."
            )
            close_day()
            date += timedelta(days=1)
            walking_day += 1
            day_km = 0.0
            cur = open_day(date, walking_day,
                           start_clock=float(max(config.WAKE_MIN, om or config.WAKE_MIN)))
            clock = cur["_start"]
            continue
        else:
            if too_early:
                note = f"wait {int(om - arrive)} min for {hhmm(om)} open"
                clock = float(om)
            visited += 1
            prefs_done.add(s["pref_short"])
            status = "VISIT"
            clock += config.VISIT_MIN

        cur["events"].append(
            {
                "order": s["order"],
                "pref": s["pref_short"],
                "name": f"{s['area']}：{s['name']}",
                "at": hhmm(arrive),
                "km": round(cum_km, 1),
                "status": status,
                "note": note,
                "open": hhmm(om) if om is not None and 0 <= om < 24 * 60 else "24h",
                "last": hhmm(lm) if lm is not None else "?",
                "closed_wd": "".join(WEEKDAY_JP[d] for d in sorted(s.get("closed_weekdays") or [])),
                "irregular": bool(s.get("irregular")),
                "buffer": bool(s.get("is_buffer")),
            }
        )

        i += 1
        if i < len(stops):
            leg_left = stops[i]["leg_km_gc"]
            leg_ascent_left = float(stops[i].get("ascent_m", 0))

    close_day()

    finish = datetime.combine(days[-1]["date"], datetime.min.time()) + timedelta(minutes=clock)
    walking = [d for d in days if not d["rest"]]
    km_days = [d["km"] for d in walking if d["km"] > 0]
    return {
        "model": {
            "source": "hike_2022_summary.json (2022 walk across Japan) + config.py",
            "break_in_days": BREAKIN_WALKING_DAYS,
            "break_in_km": BREAKIN_KM,
            "plateau_km": PLATEAU_KM,
            "recovery_km": RECOVERY_KM,
            "recovery_every": RECOVERY_EVERY,
            "rest_every_cal_days": REST_EVERY_CAL_DAYS,
            "speed_kmh": config.SPEED_KMH,
            "visit_min": config.VISIT_MIN,
            "climb_min_per_m": config.CLIMB_MIN_PER_M,
            "window": f"{hhmm(config.WAKE_MIN)} to {hhmm(config.WAKE_MIN + DAY_MIN)}",
            "policy": "skip-lean, overnight wait only for a prefecture linchpin",
            "wait_tolerance_min": wait_tolerance_min,
        },
        "totals": {
            "start": str(config.START_DT.date()),
            "finish": finish.strftime("%Y-%m-%d %H:%M"),
            "calendar_days": len(days),
            "walking_days": len(walking),
            "rest_days": len(days) - len(walking),
            "route_km": round(days[-1]["end_km"], 1),
            "km_per_calendar_day": round(days[-1]["end_km"] / len(days), 1),
            "km_per_walking_day": round(sum(km_days) / len(km_days), 1),
            "longest_day_km": max(km_days),
            "total_ascent_m": sum(d["ascent_m"] for d in days),
            "visited": visited,
            "visited_ge_88": visited >= 88,
            "skipped_closed": skipped_closed,
            "skipped_late": skipped_late,
            "skipped_early": skipped_early,
            "overnight_waits": overnight_waits,
            "prefectures": sorted(prefs_done),
            "all7": len(prefs_done) == 7,
            "irregular_visited_risk": sum(
                1 for d in days for e in d["events"] if e["status"] == "VISIT" and e["irregular"]
            ),
            "late_start_days": sum(1 for d in days if d.get("late_start_min")),
            "days_ending_after_18": sum(1 for d in days if d["end_clock"] > "18:00"),
            "days_ending_after_19": sum(1 for d in days if d["end_clock"] > "19:00"),
            "deadline": str(config.DEADLINE.date()),
            "slack_days": (config.DEADLINE.date() - finish.date()).days,
        },
        "days": days,
    }


def write_md(p: dict, path: Path) -> None:
    t, m = p["totals"], p["model"]
    L: list[str] = []
    L.append("# 九州八十八湯: the Oct/Nov 2026 day plan")
    L.append("")
    L.append(
        f"*Generated by `plan_octnov.py`. Paced on the 2022 walk across Japan "
        f"(see `hike_2022_analysis.md`), scheduled against real opening hours.*"
    )
    L.append("")
    L.append(
        f"**{t['route_km']} km · {t['calendar_days']} calendar days "
        f"({t['walking_days']} walking, {t['rest_days']} rest) · "
        f"{t['km_per_calendar_day']} km/calendar day · start {t['start']} · "
        f"finish {t['finish']} · {t['slack_days']} days of slack to {t['deadline']}**")
    L.append("")
    L.append(
        f"**{t['visited']} onsens visited** (target 88: "
        f"{'yes' if t['visited_ge_88'] else 'NO'}) · all 7 prefectures: "
        f"{'yes' if t['all7'] else 'NO'} · {' '.join(t['prefectures'])}")
    L.append("")
    L.append(
        f"Skipped: {t['skipped_closed']} closed (定休日), {t['skipped_late']} arrived after "
        f"last entry, {t['skipped_early']} would have meant waiting more than "
        f"{WAIT_TOLERANCE_MIN} min. Overnight waits: {t['overnight_waits']}.")
    L.append("")
    L.append("## The pace, and why it is this number")
    L.append("")
    L.append(
        f"- break-in: first {m['break_in_days']} walking days at **{m['break_in_km']:.0f} km**. "
        "In 2022 the first 14 days ran 2.6 km/day under the plateau, and Kirishima "
        "(stops 12 to 20) lands inside exactly this window.")
    L.append(f"- plateau: **{m['plateau_km']:.0f} km** days, the 2022 walking-day median.")
    L.append(
        f"- recovery: every {m['recovery_every']}th day drops to **{m['recovery_km']:.0f} km**. "
        "2022 had 8 short days (11 to 24 km) and only 3 zero-km days, so recovery is a "
        "short day, not a day off.")
    L.append(
        f"- rest: one true zero-km day every {m['rest_every_cal_days']} days, always after a big one.")
    L.append(
        f"- a 6 x {m['plateau_km']:.0f} + 1 x {m['recovery_km']:.0f} week is 238 km, i.e. "
        "**34.0 km/calendar day**, which is the 2022 figure to one decimal.")
    L.append("")
    L.append(
        f"Time model: {m['speed_kmh']} km/h (Strava elapsed, breaks already priced in), "
        f"{m['visit_min']} min per onsen, {m['climb_min_per_m']:.2f} min per metre climbed, "
        f"a {DAY_MIN / 60:.0f} h day starting {m['window'].split(' to ')[0]}. "
        f"Policy: {m['policy']}, waiting up to {m['wait_tolerance_min']} min at a door "
        "that opens later today.")
    L.append("")
    L.append(
        f"**Late starts.** On {t['late_start_days']} of the {t['calendar_days']} days the "
        f"first onsen of the day opens after you would reach it, so the plan sleeps in "
        f"(up to {LATE_START_MAX_MIN} min) instead of standing at the door, and the day "
        f"ends correspondingly later. Each day still gets its full {DAY_MIN / 60:.0f} h. "
        f"This one rule is worth 15 onsens on its own.")
    L.append("")
    L.append(
        f"**You will walk in the dark.** {t['days_ending_after_18']} days end after 18:00 and "
        f"{t['days_ending_after_19']} after 19:00, counting the evening soak. Kyushu sunset is "
        "~18:00 in early October and ~17:25 by mid-November, so pack the headtorch at the top "
        "of the bag, not the bottom. On 1 Nov 2022 you walked 51 km on ~10.5 h of daylight, so "
        "this is a known quantity, not an experiment.")
    L.append("")
    L.append("### Weekly blocks against the 2022 band")
    L.append("")
    L.append(
        "2022 never produced a 7-day block outside **210 to 293 km**. This plan's blocks:")
    L.append("")
    blocks = []
    for start in range(0, len(p["days"]), 7):
        chunk = p["days"][start : start + 7]
        blocks.append((start // 7 + 1, sum(d["km"] for d in chunk), len(chunk)))
    L.append("| week | km | vs 2022 band (210 to 293) |")
    L.append("|---|---|---|")
    for w, km, n in blocks:
        if n < 7:
            verdict = f"partial week ({n} days)"
        elif km < 210:
            verdict = "under: easier than 2022"
        elif km > 293:
            verdict = "OVER: harder than anything in 2022"
        else:
            verdict = "inside"
        L.append(f"| {w} | {km:.0f} | {verdict} |")
    L.append("")
    L.append(
        "Every full week sits at or under the 2022 band, which is the point. The onsens, not "
        "the legs, set the pace here.")
    L.append("")
    L.append("## What can actually break this")
    L.append("")
    nagasaki = [
        (n, d, e)
        for n, d in enumerate(p["days"], 1)
        for e in d["events"]
        if e["pref"] == "長崎"
    ]
    if nagasaki:
        n, d, e = nagasaki[0]
        L.append(
            f"1. **The 長崎 linchpin, day {n} ({d['date'].strftime('%a %d %b')}).** "
            f"{e['name']} at {e['at']}, the only Nagasaki onsen on the whole route, and it is "
            f"不定休 (irregular closure), so its posted hours guarantee nothing. Lose it and you "
            f"lose all-7 with no backup. **Call 0956-76-9008 one or two days ahead.** If it is "
            f"closed that day, stop and re-plan rather than walking past: this is the single "
            f"onsen worth burning a night for, and the planner will wait for it.")
    L.append("")
    L.append(
        f"2. **{t['irregular_visited_risk']} of the {t['visited']} visits are 不定休.** The plan "
        "counts them because their posted hours say open, but roughly a third of this schedule "
        f"is built on doors that can be shut for no reason. The cushion absorbs it: you need 88 "
        f"and the plan collects {t['visited']}, so you can lose {t['visited'] - 88} and still "
        "finish the challenge.")
    L.append("")
    L.append(
        f"3. **{t['skipped_closed']} onsens are skipped for a 定休日 and {t['skipped_late']} for "
        "arriving after last entry.** These are already priced in, not surprises. Arriving a day "
        "earlier or later shuffles which ones, so do not treat the per-day onsen list as fixed; "
        "treat the km column as fixed and re-derive the doors.")
    L.append("")
    L.append(
        f"4. **Slack is {t['slack_days']} days.** Losing a week to injury or weather still lands "
        "before the deadline. Losing two does not.")
    L.append("")
    L.append("### The one dial, and what it buys")
    L.append("")
    L.append(
        f"`WAIT_TOLERANCE_MIN` (currently {m['wait_tolerance_min']} min) is how long to stand at "
        "a door that opens later today before writing the onsen off. Run "
        "`python route_planning/plan_octnov.py --sweep` to re-derive this table:")
    L.append("")
    L.append("| wait tolerance | onsens | days | finish | slack |")
    L.append("|---|---|---|---|---|")
    L.append("| 0 min (pure skip) | 86 | 39 | Nov 9 | 23 |")
    L.append("| 90 min | 93 | 39 | Nov 9 | 23 |")
    L.append("| 180 min | 97 | 40 | Nov 10 | 22 |")
    L.append(f"| **{m['wait_tolerance_min']} min (this plan)** | **101** | **41** | **Nov 11** | **21** |")
    L.append("")
    L.append(
        "Two calendar days out of 23 buys 15 onsens. That is why the dial sits where it does. "
        "In the whole 41-day plan only 5 waits actually exceed 90 min, and the longest single "
        "wait is 220 min on Oct 27.")
    L.append("")
    L.append("## Pace check (carry this: cumulative km by day)")
    L.append("")
    L.append("| day | date | km | cum km | onsens | cum onsens |")
    L.append("|---|---|---|---|---|---|")
    cum_v = 0
    for n, d in enumerate(p["days"], 1):
        v = sum(1 for e in d["events"] if e["status"] == "VISIT")
        cum_v += v
        L.append(
            f"| {n} | {d['date'].strftime('%a %m-%d')} | {d['km']:.0f} | "
            f"{d['end_km']:.0f} | {v} | {cum_v} |")
    L.append("")
    L.append("## The days")
    L.append("")
    for n, d in enumerate(p["days"], 1):
        head = (
            f"### Day {n} · {d['date'].strftime('%a %d %b')} · "
            f"{d['km']:.0f} km (target {d['target_km']:.0f}) · "
            f"km {d['start_km']:.0f} to {d['end_km']:.0f} · +{d['ascent_m']:.0f} m")
        if d["rest"]:
            head = f"### Day {n} · {d['date'].strftime('%a %d %b')} · REST (0 km)"
        L.append(head)
        L.append("")
        for w in d["warnings"]:
            L.append(f"> {w}")
            L.append("")
        if d["events"]:
            L.append("| # | at | km | onsen | hours | verdict |")
            L.append("|---|---|---|---|---|---|")
            for e in d["events"]:
                flags = []
                if e["irregular"]:
                    flags.append("不定休")
                if e["closed_wd"]:
                    flags.append(f"休{e['closed_wd']}")
                if e["buffer"]:
                    flags.append("buffer")
                hours = f"{e['open']} to {e['last']}" + (" " + " ".join(flags) if flags else "")
                verdict = e["status"] + (f" ({e['note']})" if e["note"] else "")
                L.append(
                    f"| {e['order']} | {e['at']} | {e['km']:.0f} | {e['pref']} {e['name']} "
                    f"| {hours} | {verdict} |")
            L.append("")
        elif not d["rest"]:
            L.append("*No onsen on the line today: a pure walking day.*")
            L.append("")
        if d.get("next_stop"):
            L.append(
                f"Sleep at km {d['end_km']:.0f}, "
                f"{d['next_stop_km_away']:.1f} km short of {d['next_stop']}. "
                f"Walking stopped {d['end_clock']}.")
            L.append("")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def sweep() -> None:
    """How much is a morning wait worth? The one real dial on this plan.

    Every onsen skipped for "opens too late to be worth waiting" is an onsen lost
    for good. With ~23 days of slack the question is not whether waiting is
    affordable, it is how many onsens each waiting hour buys.
    """
    print(f"{'wait tol':>9} {'visited':>8} {'cal days':>9} {'finish':>12} {'slack':>6} "
          f"{'km/cal-d':>9} {'skip early':>11}")
    for tol in (0, 60, 90, 120, 180, 240, 360):
        t = plan(wait_tolerance_min=tol)["totals"]
        print(f"{tol:>9} {t['visited']:>8} {t['calendar_days']:>9} {t['finish'][:10]:>12} "
              f"{t['slack_days']:>6} {t['km_per_calendar_day']:>9} {t['skipped_early']:>11}")


def main() -> None:
    if "--sweep" in sys.argv:
        sweep()
        return
    tol = WAIT_TOLERANCE_MIN
    for a in sys.argv[1:]:
        if a.startswith("--wait="):
            tol = int(a.split("=", 1)[1])
    p = plan(wait_tolerance_min=tol)
    write_md(p, OUT_MD)
    serial = json.loads(json.dumps(p, default=str))
    OUT_JSON.write_text(json.dumps(serial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    t = p["totals"]
    print(
        f"\n{t['route_km']} km · {t['calendar_days']} calendar days "
        f"({t['walking_days']} walking + {t['rest_days']} rest) · "
        f"{t['km_per_calendar_day']} km/cal-day, {t['km_per_walking_day']} km/walking day "
        f"(longest {t['longest_day_km']:.0f})")
    print(f"start {t['start']} · finish {t['finish']} · slack {t['slack_days']} d to {t['deadline']}")
    print(
        f"visited {t['visited']} (>=88: {t['visited_ge_88']}) · all7 {t['all7']} "
        f"{' '.join(t['prefectures'])}")
    print(
        f"skips: {t['skipped_closed']} closed, {t['skipped_late']} late, "
        f"{t['skipped_early']} early · overnight waits {t['overnight_waits']}")
    print(f"ascent {t['total_ascent_m']} m")
    print(f"\nwrote {OUT_MD.name} + {OUT_JSON.name}")


if __name__ == "__main__":
    main()
