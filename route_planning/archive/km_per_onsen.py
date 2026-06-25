#!/usr/bin/env python3
"""km/onsen analysis.

Two notions:
  (A) AVERAGE km/onsen   = total route km / N        (blunt; route-level)
  (B) MARGINAL km/onsen  = how much each bead ADDS to the route (actionable)

Marginal cost is computed by greedy cheapest-insertion from the fixed path
START -> END(#41): we insert onsens one at a time, each at its cheapest slot,
recording the km it adds. Near-line beads cost ~0; spurs cost a lot. The curve
of marginal-km vs bead# reveals the 'knee' = the natural cutoff N.

Also computes a RISK-ADJUSTED cost: effective km to BANK a bead
  = marginal_km  +  closure_penalty_km
where closure_penalty ~ P(arrive on a bad day) * (km-value of one idle day).
"""
from __future__ import annotations

import json
from pathlib import Path

from onsen_model import load_onsens, haversine_km

HERE = Path(__file__).resolve().parent
START = ("長崎鼻", 31.1556, 130.5944)
END_ID = 41
ROAD_FACTOR = 1.3
IDLE_DAY_KM = 30.0   # opportunity cost of one idle wait-day, in km-equivalent
INCLUDE_SHIMABARA = True
INCLUDE_HIRADO = False
SHIMABARA_IDS = {21, 175, 24, 165}
HIRADO_IDS = {19}


def pt(o):
    return (o.lat, o.lon)


def d(a, b):
    return haversine_km(a[0], a[1], b[0], b[1])


def closure_penalty_km(o):
    """Expected km-equivalent idle cost to bank this onsen given its hours."""
    if o.never_closes:
        base = 0.0
    elif o.closed_weekdays:
        # under patient timing a fixed closure costs ~1 idle day only if you
        # happen to arrive on it: P = closed_days/7
        base = (len(o.closed_weekdays) / 7.0) * IDLE_DAY_KM
    else:
        base = 0.0
    if o.irregular:                      # unplannable surprise, ~12% of the time
        base += 0.12 * IDLE_DAY_KM
    # early closers add a smaller scheduling tax
    if o.effective_last_min is not None and o.effective_last_min <= 15 * 60:
        base += 0.20 * IDLE_DAY_KM
    return base


def greedy_insertion(onsens):
    end = next(o for o in onsens if o.id == END_ID)
    path = [(START[1], START[2]), pt(end)]   # coords
    path_ids = [None, end.id]
    remaining = [o for o in onsens if o.id != END_ID]
    base_len = d(path[0], path[1])
    cur_len = base_len
    rows = []
    while remaining:
        best = None  # (marginal, onsen, pos)
        for o in remaining:
            p = pt(o)
            for i in range(len(path) - 1):
                a, b = path[i], path[i + 1]
                marg = d(a, p) + d(p, b) - d(a, b)
                if best is None or marg < best[0]:
                    best = (marg, o, i)
        marg, o, i = best
        path.insert(i + 1, pt(o))
        path_ids.insert(i + 1, o.id)
        cur_len += marg
        rows.append({
            "k": len(rows) + 1, "id": o.id, "pref": o.pref_short,
            "name": f"{o.area}：{o.name}",
            "marg_gc": marg, "marg_road": marg * ROAD_FACTOR,
            "cum_road": cur_len * ROAD_FACTOR,
            "closure_pen_km": closure_penalty_km(o),
            "eff_cost_km": marg * ROAD_FACTOR + closure_penalty_km(o),
        })
    return rows, base_len


def main():
    ons = load_onsens()
    ons = [o for o in ons if not (o.id in HIRADO_IDS and not INCLUDE_HIRADO)
           and not (o.id in SHIMABARA_IDS and not INCLUDE_SHIMABARA)]

    rows, base = greedy_insertion(ons)
    N = len(rows)
    total_road = rows[-1]["cum_road"]

    print("=" * 68)
    print("(A) AVERAGE km/onsen  (route-level)")
    print("=" * 68)
    print(f"  base START->END direct: {base*ROAD_FACTOR:.0f} km road")
    for n in (88, 100, 108, N):
        cum = rows[n - 1]["cum_road"]
        print(f"  first {n:>3} cheapest beads: {cum:7.0f} km road  -> {cum/n:5.2f} km/onsen avg")

    print()
    print("=" * 68)
    print("(B) MARGINAL km/onsen  (cost each bead ADDS, cheapest-first)")
    print("=" * 68)
    print(f"  {'bead#':>5} {'marg_road':>10} {'cum_road':>9} {'cum_avg':>8}")
    for n in (10, 30, 50, 70, 88, 95, 100, 105, 108, 120, N):
        if n <= N:
            r = rows[n - 1]
            print(f"  {n:>5} {r['marg_road']:>9.1f}km {r['cum_road']:>8.0f}km {r['cum_road']/n:>7.2f}")

    # knee: first bead whose marginal road-km exceeds a threshold band
    print("\n  marginal cost crosses thresholds at bead#:")
    for thr in (5, 10, 15, 20, 30):
        idx = next((r["k"] for r in rows if r["marg_road"] > thr), None)
        print(f"    > {thr:>2} km/onsen marginal : first at bead #{idx}")

    print()
    print("=" * 68)
    print("CHEAPEST 12 beads (near-line, ~free):")
    for r in rows[:12]:
        print(f"  #{r['id']:>3} {r['pref']} {r['name'][:24]:<24} +{r['marg_road']:4.1f}km")
    print("\nMOST EXPENSIVE 12 beads (spurs):")
    for r in sorted(rows, key=lambda x: -x["marg_road"])[:12]:
        print(f"  #{r['id']:>3} {r['pref']} {r['name'][:24]:<24} +{r['marg_road']:5.1f}km  "
              f"(closure +{r['closure_pen_km']:.1f}, eff {r['eff_cost_km']:.1f})")

    print()
    print("=" * 68)
    print("(C) RISK-ADJUSTED: effective km to BANK a bead = marginal + closure tax")
    print("=" * 68)
    by_eff = sorted(rows, key=lambda x: x["eff_cost_km"])
    cum = base * ROAD_FACTOR
    eff88 = eff108 = None
    for n, r in enumerate(by_eff, 1):
        cum += r["marg_road"]
        if n == 88:
            eff88 = cum
        if n == 108:
            eff108 = cum
    print(f"  pick 88 by lowest effective cost  -> ~{eff88:.0f} km road walked")
    print(f"  pick 108 by lowest effective cost -> ~{eff108:.0f} km road walked")
    worst = sorted(rows, key=lambda x: -x["eff_cost_km"])[:8]
    print("  worst value (high detour AND closure-prone) — drop first:")
    for r in worst:
        print(f"    #{r['id']:>3} {r['pref']} {r['name'][:22]:<22} eff {r['eff_cost_km']:5.1f}km "
              f"(detour {r['marg_road']:.1f} + closure {r['closure_pen_km']:.1f})")

    (HERE / "km_per_onsen.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"\nWrote km_per_onsen.json (per-bead marginal + effective cost, cheapest-first)")


if __name__ == "__main__":
    main()
