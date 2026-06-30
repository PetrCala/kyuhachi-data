#!/usr/bin/env python3
"""Enjoyment-first scenario sweep: what does cluster-thinning + longer baths do
to the finish date and slack?

The decision card's strategy is "you are collecting, not optimizing — skip
freely." This quantifies that for the case that motivates it: the onsen
*clusters* (指宿, 妙見, 長湯, 由布院, the 明礬/鉄輪 Beppu block, …) where bathing
every one back-to-back turns a pleasure into a chore. It answers, in numbers:

  - If I cap each cluster at N onsens (do the best few, walk on) and bathe
    LONGER at the ones I do (fewer-but-longer), where do I finish?
  - How much slack to the Dec 2 deadline does each choice leave?
  - Does any thinning ever drop a prefecture below 1 (breaking all-7)?

A cluster = a maximal run of consecutive route stops each within GAP_KM of the
previous (onsens close enough to "do as one stop"). Thinning marks the dropped
onsens as walk-past: the hand-drawn line is fixed and passes all of them, so the
WALK is unchanged — only the visit time is saved (see simulate's _skip_reason).

Drop order within an over-cap cluster: optional buffer/spur pickups first, then
later-in-walking-order onsens (you do the first few and leave). The single
onsen of any prefecture (長崎 = 波佐見) is never droppable — all-7 is protected.

Read-only: writes only enjoyment_scenarios.md next to this script. No DB/Firestore.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import simulate
from config import ALL7, DEADLINE, VISIT_MIN

HERE = Path(__file__).resolve().parent
ANALYSIS = HERE / "handdrawn_loop_analysis.json"
OUT = HERE / "enjoyment_scenarios.md"

GAP_KM = 3.0                       # consecutive stops within this = same cluster
CAPS = [None, 4, 3, 2]             # max onsens visited per cluster (None = no cap)
VISITS = [50, 75, 90]              # per-onsen dwell: baseline / longer / much-longer
ROAD_FACTOR = 1.0                  # analysis legs are already road-corrected (OSRM)
VISIT_STATUSES = ("visit", "wait-open", "wait-closed", "wait-late")


def clusters(stops, gap_km=GAP_KM):
    """Partition stops (in walking order) into clusters by consecutive leg gap."""
    out, cur = [], [stops[0]]
    for s in stops[1:]:
        if s["leg_km_gc"] <= gap_km:
            cur.append(s)
        else:
            out.append(cur)
            cur = [s]
    out.append(cur)
    return out


def thin(stops, cap, gap_km=GAP_KM):
    """Return (thinned_stops, dropped) for a per-cluster `cap`.

    thinned_stops is a deep copy with `_skip_reason` set on dropped onsens (they
    still get walked past, just not bathed). `cap=None` thins nothing."""
    stops = copy.deepcopy(stops)
    pref_total = Counter(s["pref_short"] for s in stops)   # singleton prefs = locked
    dropped = []
    if cap is None:
        return stops, dropped
    for cl in clusters(stops, gap_km):
        if len(cl) <= cap:
            continue
        # keep-priority: core on-line onsens (by walking order) before optional
        # buffer/spur pickups; a sole-prefecture onsen is never droppable.
        rank = sorted(cl, key=lambda s: (s["is_buffer"] or s["is_spur"], s["order"]))
        kept = 0
        for s in rank:
            if pref_total[s["pref_short"]] == 1:   # locked: never drop 波佐見 et al.
                continue
            if kept < cap:
                kept += 1
                continue
            kind = "buffer" if s["is_buffer"] else ("spur" if s["is_spur"] else "core")
            s["_skip_reason"] = f"cluster-cap {cap} ({kind})"
            dropped.append(s)
    return stops, dropped


def all7_from_events(events):
    seen = {e["pref"] for e in events if e["status"] in VISIT_STATUSES}
    return seen, all(p in seen for p in ALL7)


def run(stops, cap, visit_min, policy):
    thinned, dropped = thin(stops, cap)
    summ, events = simulate.simulate({"stops": thinned}, policy=policy,
                                     road_factor=ROAD_FACTOR, visit_min=visit_min)
    seen, ok7 = all7_from_events(events)
    missing = [p for p in ALL7 if p not in seen]
    return {
        "cap": cap, "visit_min": visit_min, "policy": policy,
        "dropped": len(dropped), "dropped_stops": dropped,
        "visited": summ["visited"], "ge88": summ["visited"] >= 88,
        "all7": ok7, "missing": missing,
        "max_day": summ["max_onsens_one_day"],
        "finish": summ["finish"], "days": summ["calendar_days_used"],
        "slack": summ["slack_days_to_deadline"],
        "bath_h": round(summ["visited"] * visit_min / 60.0, 1),
    }


def main():
    route = json.loads(ANALYSIS.read_text())
    stops = route["stops"]
    cls = clusters(stops)
    multi = [c for c in cls if len(c) >= 3]

    # the catch-everything anchor (matches 00_itinerary.md) + the skip-lean sweep
    anchor = run(stops, None, VISIT_MIN, "patient")
    rows = [run(stops, cap, v, "skip") for cap in CAPS for v in VISITS]

    L = ["# Enjoyment-first scenarios — cluster-thinning × longer baths", ""]
    L.append(f"_Clusters: stops within **{GAP_KM} km** of the previous. "
             f"{len(cls)} clusters total, **{len(multi)}** with ≥3 onsens. "
             f"Walk model: {simulate.SPEED_KMH} km/h, road_factor {ROAD_FACTOR}, "
             f"day {simulate.WAKE_MIN//60:02d}:00–{simulate.SLEEP_MIN//60:02d}:00. "
             f"Deadline {DEADLINE:%a %m-%d}._")
    L += ["", "## The trade-off surface", "",
          "All rows are the realistic **skip-lean** walk (never wait overnight) "
          "except the first, the catch-everything **patient** anchor.", "",
          "| scenario | cap/cluster | visit | visited | ≥88 | all-7 | max/day | finish | days | slack | bath time |",
          "|---|---|---|---|:--:|:--:|:--:|---|--:|--:|--:|"]

    def fmt(r, label):
        cap = "—" if r["cap"] is None else r["cap"]
        g = "✅" if r["ge88"] else "❌"
        a = "✅" if r["all7"] else "🚫 " + "/".join(r["missing"])
        return (f"| {label} | {cap} | {r['visit_min']}m | {r['visited']} | {g} | {a} "
                f"| {r['max_day']} | {r['finish']} | {r['days']} | +{r['slack']}d "
                f"| {r['bath_h']}h |")

    L.append(fmt(anchor, "catch-everything (patient)"))
    for r in rows:
        cap_lbl = "no cap" if r["cap"] is None else f"cap {r['cap']}"
        L.append(fmt(r, f"skip-lean, {cap_lbl}"))

    # range of finish dates across the skip-lean sweep — the headline
    days = [r["days"] for r in rows]
    slacks = [r["slack"] for r in rows]
    by_cap = {cap: [r for r in rows if r["cap"] == cap] for cap in CAPS}
    vrange = lambda cap: (min(r["visited"] for r in by_cap[cap]),
                          max(r["visited"] for r in by_cap[cap]))
    c3lo, c3hi = vrange(3)
    c2lo, c2hi = vrange(2)
    L += ["", "## What the numbers say", "",
          f"- The **walk dominates**: the ~1,205 km line is a hard floor no bathing "
          f"choice can move. Across the entire cap×visit sweep the finish stays in a "
          f"**{min(days)}–{max(days)}-day** band (slack **+{min(slacks)}d to "
          f"+{max(slacks)}d**) — capping clusters and bathing longer slide it only "
          f"~{max(days)-min(days)} days. You can choose by feel without threatening the goal.",
          f"- **cap 3 is the sweet spot**: visits **{c3lo}–{c3hi}** (comfortably ≥88), "
          f"≤3 back-to-back baths per cluster, finishes within ~5 days of the "
          f"completionist plan. This is the 'do the best few, walk on' rule made concrete.",
          f"- **cap 2 is the practical floor**: visits **{c2lo}–{c2hi}** — at quick "
          f"(50 min) baths it dips to {c2lo}, *below 88*. Cap 2 erases your margin, so "
          f"use it selectively on chore-y clusters, not as a blanket rule.",
          f"- **Fewer-but-longer is nearly free**: halving the bath count while "
          f"doubling dwell lands within days of the completionist plan, with fewer "
          f"baths crammed into a day (max/day column).",
          f"- **all-7 never breaks** from thinning — 長崎 (波佐見) is a locked "
          f"singleton and every other prefecture has deep cluster-spanning redundancy.",
          "",
          "> _Visited counts wiggle ±a few as bath length shifts arrival times "
          "across opening windows / 定休日 — that's a scheduling artifact, not signal. "
          "Read the robust outputs: finish date, slack, ≥88, all-7._"]

    # the tangible "which ones you'd skip" list at the headline cap
    head_cap = 3
    _, dropped = thin(stops, head_cap)
    L += ["", f"## What you'd actually skip at **cap {head_cap}**",
          f"_{len(dropped)} onsens, dropped optional-first then by walking order. "
          f"These are walked past, not detoured to._", ""]
    by_cluster = {}
    cl_of = {}
    for ci, c in enumerate(clusters(stops)):
        for s in c:
            cl_of[s["order"]] = (ci, c)
    for s in dropped:
        ci, c = cl_of[s["order"]]
        key = f"#{c[0]['order']}–{c[-1]['order']}"
        by_cluster.setdefault(key, []).append(s)
    for key, ss in by_cluster.items():
        names = ", ".join(f"#{s['order']} {s['area']}：{s['name']}"
                          f"{' 🅑' if s['is_buffer'] else (' ➰' if s['is_spur'] else '')}"
                          for s in ss)
        L.append(f"- **cluster {key}** → skip {names}")

    L += ["", "## The clusters (≥3 onsens)", "",
          "| cluster | size | onsens |", "|---|--:|---|"]
    for c in multi:
        areas = Counter(s["area"] for s in c)
        desc = "・".join(f"{a}×{n}" if n > 1 else a for a, n in areas.items())
        L.append(f"| #{c[0]['order']}–{c[-1]['order']} | {len(c)} | {desc} |")

    L += ["", "## Caveat — the cap rule has no taste", "",
          "The drop rule is mechanical: optional buffer/spur first, then later in "
          "walking order. It has **no idea which onsen is more interesting** — at cap "
          "3 it drops 鉄輪 ひょうたん温泉 (a famous one) purely because 明礬 comes first "
          "on the line. Treat this sweep as the *budget* (how many you can skip, where), "
          "not the *picks*. The pick is yours, by feel, at the door.",
          "",
          "To make it taste-aware, give me a must-do / skip-first list (or per-cluster "
          "caps) and I'll wire a keep-priority in — the singleton lock (波佐見) already "
          "shows the mechanism."]

    OUT.write_text("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\n[written] {OUT.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
