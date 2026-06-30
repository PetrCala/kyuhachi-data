#!/usr/bin/env python3
"""Deliverable 2: hours-aware day-by-day schedule simulator.

Given an ordered route (route_first_pass.json), simulate a realistic walking
clock and, for every onsen, check:
  (a) does the arrival weekday hit its 定休日 (fixed closure)?  -> hard block, SKIP
  (b) does arrival beat last-entry / closing?                  -> early-open wait,
                                                                  or late-miss SKIP
Outputs the TRUE calendar-day count (incl. waits/sleep), a per-day itinerary,
and flagged risk legs. Read-only.

Walking model (empirically grounded; all configurable):
  SPEED_KMH   4.0   loaded moving pace. Strava: moving median 5.05, elapsed 3.97;
                    ~20% load penalty on moving -> ~4.0 (also matches real elapsed).
  VISIT_MIN   20    onsendo.db real stays: median 13, p75 18, p90 25; +stamp/admin.
  ROAD_FACTOR 1.3   great-circle -> real foot distance.
  WAKE/SLEEP  06:00 / 22:00  -> 16 h awake, 8 h sleep (no fixed daily km budget;
                    walk whenever awake & not bathing/waiting).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from config import (CLIMB_MIN_PER_M, DEADLINE, ROAD_FACTOR, SLEEP_MIN,
                    SPEED_KMH, START_DT, VISIT_MIN, WAKE_MIN)

HERE = Path(__file__).resolve().parent
WEEKDAY_JP = "月火水木金土日"


def mod_min(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def advance_walking(clock: datetime, minutes: float) -> datetime:
    """Advance by `minutes` of walking, only during the awake window."""
    remaining = minutes
    guard = 0
    while remaining > 1e-6:
        guard += 1
        if guard > 10000:
            break
        m = mod_min(clock)
        if m < WAKE_MIN:
            clock = clock.replace(hour=6, minute=0, second=0, microsecond=0)
            continue
        if m >= SLEEP_MIN:
            clock = (clock + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
            continue
        avail = SLEEP_MIN - m
        step = min(remaining, avail)
        clock += timedelta(minutes=step)
        remaining -= step
        if remaining > 1e-6:  # hit sleep -> next morning
            clock = (clock + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    return clock


def fmt(dt):
    return dt.strftime("%a %m-%d %H:%M")


def earliest_entry(arrive, open_min, last_min, closed_wd, horizon=8):
    """Earliest datetime >= arrive you can ENTER, respecting fixed closures and
    the opening window. Returns (entry_dt, idle_days) or (None, None) if never."""
    d = arrive
    o = open_min if (open_min is not None and 0 <= open_min < 24 * 60) else WAKE_MIN
    l = last_min if last_min is not None else SLEEP_MIN
    for _ in range(horizon):
        if d.weekday() in closed_wd:
            d = (d + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
            continue
        amin = mod_min(d)
        if amin < o:
            entry = d.replace(hour=o // 60, minute=o % 60, second=0, microsecond=0)
        elif amin <= l:
            entry = d
        else:  # after last entry -> try next day
            d = (d + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
            continue
        idle = (entry.date() - arrive.date()).days
        return entry, idle
    return None, None


def simulate(route, policy="patient", target=88, road_factor=ROAD_FACTOR,
             visit_min=VISIT_MIN, grade=True):
    """policy: 'skip' = miss closed/late onsens (raw yield);
               'patient' = retime to next valid opening (spend idle days).
    road_factor: 1.0 when leg_km are already real (OSRM); 1.3 for great-circle.
    visit_min: per-onsen dwell time; override to model 'fewer but longer' visits.
    grade: add the Naismith climb-time penalty per leg from each stop's 'ascent_m'
           (metres climbed on the leg INTO it; baked into the route by elevation.py).
           A stop without 'ascent_m' contributes 0 — so a route with no elevation
           data, or grade=False, is exactly the old flat model.
    route: a path to a route JSON, or an already-loaded route dict (so callers can
           feed a thinned/edited stop list in memory without writing a file)."""
    r = route if isinstance(route, dict) else json.loads(Path(route).read_text())
    stops = r["stops"]
    clock = START_DT
    events = []
    visited = skip_closed = skip_late = waited = irregular_seen = 0
    idle_days_total = 0
    climb_min_total = 0.0
    max_in_day = 0

    for s in stops:
        leg_km = s["leg_km_gc"] * road_factor
        walk_min = leg_km / SPEED_KMH * 60.0
        if grade:
            climb_min = s.get("ascent_m", 0.0) * CLIMB_MIN_PER_M
            walk_min += climb_min
            climb_min_total += climb_min
        arrive = advance_walking(clock, walk_min)
        # Planned skip (e.g. cluster-thinning): you still WALK the fixed line past
        # it — only the visit is skipped, so advance the clock by the leg but don't
        # bathe. The walking distance is unchanged; only visit time is saved.
        if s.get("_skip_reason"):
            events.append(_ev(s, arrive, "SKIP-capped", s["_skip_reason"], visited))
            clock = arrive
            continue
        amin = mod_min(arrive)
        closed_wd = set(s.get("closed_weekdays") or [])
        open_min = s.get("open_min")
        last_min = s.get("last_min")
        note = ""
        on_closure = arrive.weekday() in closed_wd
        too_late = last_min is not None and amin > last_min and not on_closure
        too_early = (open_min is not None and 0 <= open_min < 24 * 60 and amin < open_min
                     and not on_closure)

        if policy == "skip":
            if on_closure:
                skip_closed += 1
                events.append(_ev(s, arrive, "SKIP-closed",
                                  f"定休日 {''.join(WEEKDAY_JP[d] for d in sorted(closed_wd))}曜", visited))
                clock = arrive
                continue
            if too_late:
                skip_late += 1
                events.append(_ev(s, arrive, "SKIP-late",
                                  f"arr {arrive.strftime('%H:%M')} > 終 {last_min//60}:{last_min%60:02d}", visited))
                clock = arrive
                continue
            entry = arrive
            if too_early:
                entry = arrive.replace(hour=open_min // 60, minute=open_min % 60, second=0, microsecond=0)
                waited += 1
                note = f"opens {open_min//60}:{open_min%60:02d}"
            status = "wait-open" if too_early else "visit"
        else:  # patient
            entry, idle = earliest_entry(arrive, open_min, last_min, closed_wd)
            if entry is None:
                skip_late += 1
                events.append(_ev(s, arrive, "SKIP-unreachable", "no open day within a week", visited))
                clock = arrive
                continue
            if idle >= 1:
                idle_days_total += idle
                status = "wait-closed" if on_closure else "wait-late"
                note = f"retimed +{idle}d to {entry.strftime('%a %H:%M')}"
                if on_closure:
                    note = f"定休日 {''.join(WEEKDAY_JP[d] for d in sorted(closed_wd))}曜 — " + note
                waited += 1
            elif entry > arrive:
                status = "wait-open"
                note = f"opens {open_min//60}:{open_min%60:02d}"
                waited += 1
            else:
                status = "visit"

        if s.get("irregular"):
            irregular_seen += 1
        visited += 1
        events.append(_ev(s, entry, status, note, visited))
        clock = entry + timedelta(minutes=visit_min)

    # max onsens visited in a single calendar day
    from collections import Counter
    day_counts = Counter(e["date"] for e in events if e["status"] in
                         ("visit", "wait-open", "wait-closed", "wait-late"))
    max_in_day = max(day_counts.values()) if day_counts else 0

    finish = clock
    days_used = (finish.date() - START_DT.date()).days + 1
    summary = {
        "policy": policy,
        "start": fmt(START_DT), "finish": fmt(finish),
        "calendar_days_used": days_used,
        "deadline": fmt(DEADLINE),
        "finishes_before_deadline": finish <= DEADLINE,
        "slack_days_to_deadline": (DEADLINE.date() - finish.date()).days,
        "routed_stops": len(stops),
        "visited": visited,
        "visited_ge_88": visited >= 88,
        "skip_closed_定休日": skip_closed,
        "skip_late": skip_late,
        "waits": waited,
        "idle_days_from_waits": idle_days_total,
        "max_onsens_one_day": max_in_day,
        "irregular_不定休_visited(risk)": irregular_seen,
        "model": {"speed_kmh": SPEED_KMH, "visit_min": visit_min, "road_factor": road_factor,
                  "wake": f"{WAKE_MIN//60:02d}:{WAKE_MIN%60:02d}",
                  "sleep": f"{SLEEP_MIN//60:02d}:{SLEEP_MIN%60:02d}",
                  "grade": grade, "climb_hours": round(climb_min_total / 60.0, 1)},
    }
    return summary, events


def _ev(s, dt, status, note, visited_so_far):
    return {
        "order": s["order"], "id": s["id"], "pref": s["pref_short"],
        "name": f'{s["area"]}：{s["name"]}', "arrive": fmt(dt),
        "date": dt.strftime("%Y-%m-%d"), "status": status, "note": note,
        "open": (f'{s["open_min"]//60}:{s["open_min"]%60:02d}' if s.get("open_min") is not None else "?"),
        "last": (f'{s["last_min"]//60}:{s["last_min"]%60:02d}' if s.get("last_min") is not None else "?"),
        "irregular": s.get("irregular", False),
        "is_spur": s.get("is_spur", False),
        "is_buffer": s.get("is_buffer", False),
    }


def write_itinerary(summary, events, path, warnings=None):
    """warnings: optional list of crux-zone dicts {orders: (lo, hi), title, lines}
    (see difficulty.CRUX_ZONES). Each zone is emitted once, as a blockquote at the
    top of the first day that enters its inclusive stop-order range — a heads-up
    before you walk into a hard/remote stretch. Stop orders are route-specific, so
    only pass this for the route the zones were derived from."""
    by_day = {}
    for e in events:
        by_day.setdefault(e["date"], []).append(e)
    zones = list(warnings or [])
    emitted = set()
    lines = ["# Hours-aware schedule simulation", ""]
    for k, v in summary.items():
        lines.append(f"- **{k}**: {v}")
    lines.append("\n---\n")
    for day in sorted(by_day):
        evs = by_day[day]
        visits = sum(1 for e in evs if e["status"] in ("visit", "wait-open", "wait-closed", "wait-late"))
        lines.append(f"### {day}  ({len(evs)} stops, {visits} visited)")
        day_orders = [e["order"] for e in evs]
        for zi, z in enumerate(zones):
            lo, hi = z["orders"]
            if zi not in emitted and any(lo <= o <= hi for o in day_orders):
                emitted.add(zi)
                lines.append("")
                lines.append(f"> ⚠️ **{z['title']}** — stops #{lo}–{hi}")
                for ln in z["lines"]:
                    lines.append(f"> {ln}")
                lines.append("")
        for e in evs:
            flag = {"visit": "✅", "wait-open": "⏳", "wait-closed": "🛌", "wait-late": "🛌",
                    "SKIP-closed": "🚫", "SKIP-late": "⌛", "SKIP-unreachable": "❌",
                    "SKIP-capped": "➖"}.get(e["status"], "·")
            extra = f" — {e['note']}" if e["note"] else ""
            irr = " ⚠️不定休" if e["irregular"] else ""
            tag = " 🅑BUFFER(optional)" if e.get("is_buffer") else (" ➰SPUR" if e.get("is_spur") else "")
            lines.append(f"- {flag} **{e['order']}.** {e['arrive']} {e['pref']} {e['name']}  "
                         f"(開 {e['open']}/終 {e['last']}){extra}{irr}{tag}")
        lines.append("")
    Path(path).write_text("\n".join(lines))


if __name__ == "__main__":
    import sys
    policy = "skip" if "--skip" in sys.argv else "patient"
    route = "route_first_pass.json"
    summary, events = simulate(HERE / route, policy=policy)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    out = HERE / (f"itinerary_{policy}.md")
    write_itinerary(summary, events, out)
    risks = [e for e in events if e["status"].startswith("SKIP")]
    waits = [e for e in events if e["status"] in ("wait-closed", "wait-late")]
    if risks:
        print(f"\nUnrecoverable skips ({len(risks)}):")
        for e in risks:
            print(f"  {e['status']:13s} {e['arrive']}  {e['pref']} {e['name'][:24]:<24} {e['note']}")
    if waits:
        print(f"\nIdle-day waits ({len(waits)}):")
        for e in waits:
            print(f"  {e['arrive']}  {e['pref']} {e['name'][:24]:<24} {e['note']}")
    print(f"\nWrote {out.name}")
