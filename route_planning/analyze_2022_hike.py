#!/usr/bin/env python3
"""Derive the walk model from the 2022 hike across Japan (the only ground truth).

The 2022 trip (Hokkaido to Kyushu, 19 Aug to 3 Nov 2022, 2,634 km on foot over
77 days) is the single best predictor of how this hiker actually moves over a
multi-week walk. Strava (`fetch_strava_walks.py`) gives *instantaneous* pace from
day hikes; this gives the thing day hikes cannot: sustained daily output,
rest-day cadence, adaptation, and what an onsen stop costs a day.

Input: `route_planning/data/hike_2022_japan.xlsx` (the hiker's own day log:
distance, steps, onsen yes/no, weight, island per day).

Output: `route_planning/hike_2022_summary.json` plus a printed report.

Read the numbers this way:
  - Daily distance is the PLANNING unit here, not km/h. The 2022 log has no
    hours, so it cannot calibrate `SPEED_KMH`; it calibrates how far a day goes.
  - The Oct/Nov and Kyushu slices matter most: same island, same season, same
    daylight as the Kyushu-88 walk.
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import config  # noqa: E402  (path shim first, as in every route_planning script)

XLSX = Path(os.environ.get("HIKE_2022_XLSX", HERE / "data" / "hike_2022_japan.xlsx"))
OUT_JSON = HERE / "hike_2022_summary.json"
STRAVA_JSON = HERE / "strava_walk_summary.json"  # pace side of the model (optional)

# The Kyushu-88 route as currently packaged (handdrawn_loop_analysis.json).
ROUTE_KM = 1205.0
ROUTE_ONSENS = 119
ROUTE_TARGET = 88


# --- loading ---------------------------------------------------------------
def load_days(path: Path) -> list[dict]:
    """Read the `Overview` sheet into one record per calendar day."""
    try:
        import openpyxl
    except ModuleNotFoundError:  # pragma: no cover - environment guard
        sys.exit("openpyxl is required: pip install openpyxl (or pip install -e .)")

    ws = openpyxl.load_workbook(path, data_only=True)["Overview"]
    days: list[dict] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        day, dt, km, _cum, _pace, steps, _cumsteps, _spd, onsen, weight, island = row[:11]
        if day is None or dt is None:
            continue
        days.append(
            {
                "day": int(day),
                "date": dt.date() if hasattr(dt, "date") else dt,
                "km": float(km or 0.0),
                "steps": int(steps or 0),
                "onsen": bool(onsen),
                "weight": float(weight) if weight is not None else None,
                "island": island,
            }
        )
    return days


# --- helpers ---------------------------------------------------------------
def dist(vals: list[float]) -> dict:
    """Distribution summary; percentiles by nearest rank on the sorted sample."""
    if not vals:
        return {}
    s = sorted(vals)

    def pct(p: float) -> float:
        return round(s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))], 1)

    return {
        "n": len(s),
        "min": round(s[0], 1),
        "p10": pct(10),
        "p25": pct(25),
        "median": round(st.median(s), 1),
        "mean": round(st.fmean(s), 1),
        "p75": pct(75),
        "p90": pct(90),
        "max": round(s[-1], 1),
        "stdev": round(st.stdev(s), 1) if len(s) > 1 else 0.0,
    }


def streaks(days: list[dict]) -> list[int]:
    """Lengths of consecutive walking days between zero-km (rest) days."""
    out, cur = [], 0
    for d in days:
        if d["km"] > 0:
            cur += 1
        else:
            if cur:
                out.append(cur)
            cur = 0
    if cur:
        out.append(cur)
    return out


def slice_stats(days: list[dict], label: str) -> dict:
    walked = [d["km"] for d in days if d["km"] > 0]
    rest = [d for d in days if d["km"] == 0]
    return {
        "label": label,
        "calendar_days": len(days),
        "rest_days": len(rest),
        "total_km": round(sum(d["km"] for d in days), 1),
        "km_per_calendar_day": round(sum(d["km"] for d in days) / len(days), 1) if days else 0,
        "km_per_walking_day": round(st.fmean(walked), 1) if walked else 0,
        "walking_day_dist": dist(walked),
        "onsen_days": sum(1 for d in days if d["onsen"]),
        "onsen_day_share": round(sum(1 for d in days if d["onsen"]) / len(days), 3) if days else 0,
    }


def main() -> None:
    days = load_days(XLSX)
    walked = [d for d in days if d["km"] > 0]
    rest = [d for d in days if d["km"] == 0]
    km_walked = [d["km"] for d in walked]
    total_km = sum(d["km"] for d in days)

    # --- adaptation: is the hiker stronger late than early? ---------------
    # Compare the first 14 walking days with the last 14: the break-in cost.
    first14 = [d["km"] for d in walked[:14]]
    last14 = [d["km"] for d in walked[-14:]]
    # ...and the post-break-in plateau (drop the first 14 walking days).
    plateau = [d["km"] for d in walked[14:]]

    # --- 7-day rolling window (the real "sustainable week") ---------------
    # Rolling over CALENDAR days: a rest day inside the window is part of the cost.
    roll7 = [round(sum(x["km"] for x in days[i : i + 7]), 1) for i in range(0, len(days) - 6)]

    # --- onsen cost: does a bath day walk shorter? ------------------------
    onsen_km = [d["km"] for d in walked if d["onsen"]]
    dry_km = [d["km"] for d in walked if not d["onsen"]]

    # --- what follows a big day? -----------------------------------------
    BIG = 45.0
    after_big = [days[i + 1]["km"] for i, d in enumerate(days[:-1]) if d["km"] >= BIG]
    b2b40 = sum(1 for i in range(len(days) - 1) if days[i]["km"] >= 40 and days[i + 1]["km"] >= 40)

    # --- stride: steps per km (a sanity check and a terrain proxy) --------
    spk = [d["steps"] / d["km"] for d in walked if d["steps"] and d["km"] > 0]

    # --- slices that transfer to Kyushu-88 -------------------------------
    kyushu = [d for d in days if d["island"] == "Kyushu"]
    octnov = [d for d in days if d["date"] >= date(2022, 10, 1)]
    sept = [d for d in days if date(2022, 9, 1) <= d["date"] <= date(2022, 9, 30)]

    weights = [(d["date"], d["weight"]) for d in days if d["weight"] is not None]

    summary = {
        "source": XLSX.name,
        "trip": {
            "start": str(days[0]["date"]),
            "end": str(days[-1]["date"]),
            "calendar_days": len(days),
            "walking_days": len(walked),
            "rest_days": len(rest),
            "rest_day_dates": [str(d["date"]) for d in rest],
            "total_km": round(total_km, 1),
            "km_per_calendar_day": round(total_km / len(days), 2),
            "km_per_walking_day": round(st.fmean(km_walked), 2),
            "total_steps": sum(d["steps"] for d in days),
        },
        "walking_day_km": dist(km_walked),
        "rolling_7day_km": dist([float(x) for x in roll7]),
        "adaptation": {
            "first_14_walking_days_mean_km": round(st.fmean(first14), 1),
            "last_14_walking_days_mean_km": round(st.fmean(last14), 1),
            "after_break_in_mean_km": round(st.fmean(plateau), 1),
            "break_in_penalty_km": round(st.fmean(plateau) - st.fmean(first14), 1),
        },
        "rest_cadence": {
            "walking_streaks": streaks(days),
            "longest_streak_days": max(streaks(days)),
            "mean_streak_days": round(st.fmean(streaks(days)), 1),
            "rest_day_every_n_days": round(len(days) / len(rest), 1) if rest else None,
        },
        "onsen_effect": {
            "onsen_days": sum(1 for d in days if d["onsen"]),
            "onsen_day_share": round(sum(1 for d in days if d["onsen"]) / len(days), 3),
            "mean_km_onsen_day": round(st.fmean(onsen_km), 1) if onsen_km else None,
            "mean_km_no_onsen_day": round(st.fmean(dry_km), 1) if dry_km else None,
            "onsen_day_km_delta": (
                round(st.fmean(onsen_km) - st.fmean(dry_km), 1) if onsen_km and dry_km else None
            ),
        },
        "big_day_recovery": {
            "big_day_threshold_km": BIG,
            "big_days": sum(1 for d in days if d["km"] >= BIG),
            "mean_km_day_after_big": round(st.fmean(after_big), 1) if after_big else None,
            "back_to_back_40km_pairs": b2b40,
            "days_over_40km": sum(1 for d in days if d["km"] >= 40),
            "days_over_50km": sum(1 for d in days if d["km"] >= 50),
        },
        "stride": {
            "steps_per_km": dist(spk),
            "mean_steps_per_day": round(st.fmean([d["steps"] for d in walked]), 0),
        },
        "slices": [
            slice_stats(days, "whole trip"),
            slice_stats([d for d in days if d["island"] == "Hokkaido"], "Hokkaido (Aug 19 to Sep 6)"),
            slice_stats([d for d in days if d["island"] == "Honshu"], "Honshu (Sep 7 to Oct 14)"),
            slice_stats([d for d in days if d["island"] == "Shikoku"], "Shikoku (Oct 15 to 23)"),
            slice_stats(kyushu, "Kyushu (Oct 24 to Nov 3)"),
            slice_stats(sept, "September"),
            slice_stats(octnov, "Oct 1 to Nov 3 (same season as Kyushu-88)"),
        ],
        "weight": {
            "start_kg": weights[0][1],
            "end_kg": weights[-1][1],
            "min_kg": min(w for _, w in weights),
            "change_kg": round(weights[-1][1] - weights[0][1], 1),
            "first_3_weeks_change_kg": round(
                next(w for d, w in weights if d >= date(2022, 9, 8)) - weights[0][1], 1
            ),
        },
    }

    # --- close the loop with Strava: distance/day + pace = hours/day ------
    # The 2022 log has no clock, Strava has no multi-week days. Together they
    # give the one number the scheduler actually consumes: how long a day is.
    if STRAVA_JSON.exists():
        sv = json.loads(STRAVA_JSON.read_text(encoding="utf-8"))
        moving = sv["moving_kmh_dist"]["median"]
        elapsed = sv["elapsed_kmh_dist"]["median"]
        med_day = summary["walking_day_km"]["median"]
        p90_day = summary["walking_day_km"]["p90"]
        summary["day_length"] = {
            "strava_moving_kmh": moving,
            "strava_elapsed_kmh": elapsed,
            "median_day_km": med_day,
            "median_day_moving_h": round(med_day / moving, 1),
            "median_day_elapsed_h": round(med_day / elapsed, 1),
            "p90_day_km": p90_day,
            "p90_day_elapsed_h": round(p90_day / elapsed, 1),
            "config_speed_kmh": config.SPEED_KMH,
            "config_window_h": (config.SLEEP_MIN - config.WAKE_MIN) / 60,
            "verdict": (
                f"A median {med_day:.0f} km day is ~{med_day / elapsed:.1f} h door to door "
                f"(~{med_day / moving:.1f} h moving). config.SPEED_KMH={config.SPEED_KMH} sits "
                f"between Strava's moving {moving} and elapsed {elapsed}, so the "
                f"{(config.SLEEP_MIN - config.WAKE_MIN) / 60:.0f} h window in config.py is the "
                "right shape: it already prices in breaks. The 2022 log confirms the "
                "OUTPUT of that model (34 km/day sustained) rather than contradicting it."
            ),
        }

    # --- what this implies for Kyushu-88 ---------------------------------
    # Three planning paces, all grounded in the log rather than picked:
    #   conservative = the Oct/Nov mean per CALENDAR day (rest days included)
    #   expected     = the whole-trip mean per calendar day
    #   strong       = the plateau mean per WALKING day, rest day every 10
    per_cal_octnov = summary["slices"][-1]["km_per_calendar_day"]
    per_cal_trip = summary["trip"]["km_per_calendar_day"]
    plateau_mean = summary["adaptation"]["after_break_in_mean_km"]
    strong_per_cal = plateau_mean * 9 / 10  # 9 walking days per 10 calendar days

    def days_for(kmpd: float) -> float:
        return round(ROUTE_KM / kmpd, 1)

    summary["kyuhachi_implications"] = {
        "route_km": ROUTE_KM,
        "route_onsens_on_line": ROUTE_ONSENS,
        "target_visits": ROUTE_TARGET,
        "start": config.START_DT.strftime("%Y-%m-%d"),
        "deadline": config.DEADLINE.strftime("%Y-%m-%d"),
        "calendar_days_available": (config.DEADLINE.date() - config.START_DT.date()).days,
        "paces_km_per_calendar_day": {
            "conservative_octnov_2022": per_cal_octnov,
            "expected_whole_trip_2022": per_cal_trip,
            "strong_plateau_with_rest_every_10d": round(strong_per_cal, 1),
        },
        "walking_days_needed": {
            "conservative": days_for(per_cal_octnov),
            "expected": days_for(per_cal_trip),
            "strong": days_for(strong_per_cal),
        },
        "note": (
            "Kyushu-88 is not a pure distance walk: ~119 onsen stops at ~50 min each "
            "is ~99 h, about 8 full walking days of standing still, and opening hours "
            "gate the day far more than legs do. Treat these day counts as the "
            "distance floor, then add the visit and hours overhead from simulate.py."
        ),
    }

    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # --- report ------------------------------------------------------------
    t = summary["trip"]
    print(f"\n=== 2022 hike across Japan: {t['start']} to {t['end']} ===")
    print(
        f"{t['total_km']} km · {t['calendar_days']} calendar days "
        f"({t['walking_days']} walking + {t['rest_days']} rest) · "
        f"{t['km_per_calendar_day']} km/calendar day · {t['km_per_walking_day']} km/walking day"
    )

    d = summary["walking_day_km"]
    print(
        f"\nwalking-day distance: median {d['median']} · mean {d['mean']} +/- {d['stdev']} · "
        f"p10 {d['p10']} · p90 {d['p90']} · max {d['max']} km"
    )
    r = summary["rolling_7day_km"]
    print(f"rolling 7-day block:  median {r['median']} · p10 {r['p10']} · max {r['max']} km/week")

    a = summary["adaptation"]
    print(
        f"\nadaptation: first 14 walking days {a['first_14_walking_days_mean_km']} km/d, "
        f"after break-in {a['after_break_in_mean_km']} km/d "
        f"(break-in costs {a['break_in_penalty_km']} km/d); last 14 days "
        f"{a['last_14_walking_days_mean_km']} km/d"
    )

    c = summary["rest_cadence"]
    print(
        f"rest: {t['rest_days']} zero-km days in {t['calendar_days']} "
        f"(one every ~{c['rest_day_every_n_days']} d) · streaks {c['walking_streaks']} "
        f"· longest {c['longest_streak_days']} d"
    )

    o = summary["onsen_effect"]
    print(
        f"onsen: {o['onsen_days']}/{t['calendar_days']} days ({o['onsen_day_share']:.0%}) · "
        f"bath day {o['mean_km_onsen_day']} km vs dry day {o['mean_km_no_onsen_day']} km "
        f"(delta {o['onsen_day_km_delta']:+} km)"
    )

    b = summary["big_day_recovery"]
    print(
        f"big days: {b['days_over_40km']}x 40+ km, {b['days_over_50km']}x 50+ km · "
        f"day after a {BIG:.0f}+ km day averages {b['mean_km_day_after_big']} km · "
        f"{b['back_to_back_40km_pairs']} back-to-back 40+ pairs"
    )
    s = summary["stride"]["steps_per_km"]
    print(f"stride: {s['median']} steps/km (p10 {s['p10']}, p90 {s['p90']})")
    w = summary["weight"]
    print(
        f"weight: {w['start_kg']} to {w['end_kg']} kg ({w['change_kg']:+} kg), "
        f"min {w['min_kg']}; {w['first_3_weeks_change_kg']:+} kg in the first 3 weeks"
    )

    print("\n--- by section ---")
    for sl in summary["slices"]:
        print(
            f"{sl['label']:<42} {sl['total_km']:>7.1f} km / {sl['calendar_days']:>2} d "
            f"= {sl['km_per_calendar_day']:>5.1f} km/cal-d "
            f"({sl['km_per_walking_day']:>5.1f} km/walk-d, {sl['rest_days']} rest, "
            f"onsen {sl['onsen_day_share']:.0%})"
        )

    if "day_length" in summary:
        dl = summary["day_length"]
        print(
            f"\nday length: median {dl['median_day_km']} km = {dl['median_day_elapsed_h']} h "
            f"door to door ({dl['median_day_moving_h']} h moving) · "
            f"a p90 {dl['p90_day_km']} km day = {dl['p90_day_elapsed_h']} h"
        )

    k = summary["kyuhachi_implications"]
    print(f"\n--- what it implies for Kyushu-88 ({k['route_km']} km) ---")
    for name, kmpd in k["paces_km_per_calendar_day"].items():
        need = k["walking_days_needed"][name.split("_")[0]]
        print(f"{name:<38} {kmpd:>5.1f} km/cal-d -> {need:>5.1f} days of pure walking")
    print(
        f"available: {k['calendar_days_available']} calendar days "
        f"({k['start']} to {k['deadline']})"
    )
    print(f"\nwrote {OUT_JSON.relative_to(config.REPO)}")


if __name__ == "__main__":
    main()
