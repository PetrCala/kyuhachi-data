#!/usr/bin/env python3
"""Grade-penalty impact: how realistic climb-day pacing changes the schedule.

Re-runs simulate flat vs grade-aware (Naismith on route_elevation.json) and shows
where the climb time lands — aggregate (a day or two) vs per-leg (the crux days
run long). The point isn't the finish date (slack swallows it) but to stop the
flat 4 km/h clock from lying on the Kuju / Kirishima / Aso climbs.

Offline: reads the committed route_elevation.json (build it with elevation.py).
Writes only grade_impact.md. Read-only against the catalog.
"""
from __future__ import annotations

import json
from pathlib import Path

import difficulty
import simulate
from config import CLIMB_MIN_PER_M

HERE = Path(__file__).resolve().parent
ANALYSIS = HERE / "handdrawn_loop_analysis.json"
ELEV = HERE / "route_elevation.json"
OUT = HERE / "grade_impact.md"


def main():
    elev = json.loads(ELEV.read_text())
    estops = elev["stops"]
    meta = elev["meta"]
    add_min = {int(o): v["ascent_m"] * CLIMB_MIN_PER_M for o, v in estops.items()}

    runs = {(pol, g): simulate.simulate(ANALYSIS, policy=pol, road_factor=1.0, grade=g)[0]
            for pol in ("skip", "patient") for g in (False, True)}

    L = ["# Grade penalty — realistic climb-day pacing", ""]
    L.append(f"_Naismith **+1 h / 600 m** ({CLIMB_MIN_PER_M:.2f} min per metre of ascent) on the "
             f"SRTM per-leg ascent in `route_elevation.json` ({meta['dem']}, {meta['step_km']} km "
             f"sampling). Total ascent **{meta['total_ascent_m']:,} m** over {meta['line_km']:.0f} km "
             f"→ **+{sum(add_min.values())/60:.1f} h** of climb time, {_crux_share(estops):.0f}% of it "
             f"inside the named crux zones._")

    L += ["", "## Schedule: flat vs grade-aware", "",
          "| policy | model | finish | days | slack | visited |",
          "|---|---|---|--:|--:|--:|"]
    for pol in ("skip", "patient"):
        label = "skip-lean (realistic)" if pol == "skip" else "patient (catch-everything)"
        for g in (False, True):
            s = runs[(pol, g)]
            L.append(f"| {label if g else ''} | {'**grade**' if g else 'flat'} | {s['finish']} "
                     f"| {s['calendar_days_used']} | +{s['slack_days_to_deadline']}d | {s['visited']} |")
    sk = runs[("skip", True)]["calendar_days_used"] - runs[("skip", False)]["calendar_days_used"]
    pt = runs[("patient", True)]["calendar_days_used"] - runs[("patient", False)]["calendar_days_used"]
    L += ["", f"Aggregate cost: **+{sk} day** skip-lean, **+{pt} days** patient — the ~23 h of "
          f"climbing spreads across the route and slack absorbs it. The finish barely moves; "
          f"the **per-day** picture is where the penalty bites."]

    # per crux zone
    L += ["", "## Where the climb time lands — by crux zone", "",
          "| zone | stops | ascent | added time |", "|---|---|--:|--:|"]
    for z in difficulty.CRUX_ZONES:
        lo, hi = z["orders"]
        asc = sum(estops[str(o)]["ascent_m"] for o in range(lo, hi + 1) if str(o) in estops)
        mins = asc * CLIMB_MIN_PER_M
        title = z["title"].split(" — ")[0]
        L.append(f"| {title} | #{lo}–{hi} | {asc:,} m | +{mins/60:.1f} h |")

    # biggest single legs
    top = sorted(estops.values(), key=lambda v: -v["ascent_m"])[:12]
    L += ["", "## Biggest single climb-legs — the flat clock under-times these", "",
          "_Add the shown time to the flat-model arrival for the leg INTO each onsen._", "",
          "| leg into | ascent | onsen elev | +time | method |", "|---|--:|--:|--:|:--:|"]
    for v in top:
        L.append(f"| #{v['order']} {v['pref']} {v['area']} | {v['ascent_m']:,} m | "
                 f"{v['elev_m']:.0f} m | +{v['ascent_m']*CLIMB_MIN_PER_M:.0f} min | {v['method']} |")

    L += ["", "## Reading", "",
          f"- **Don't trust the per-day clock through the crux zones.** A single big-climb "
          f"leg (Aso south rim #41 ≈ +{estops['41']['ascent_m']*CLIMB_MIN_PER_M:.0f} min, the "
          f"Kuju/法華院 approach, the Kirishima re-climbs) adds **1–1.5 h** the flat model hides. "
          f"On those days plan ~1–2 h less distance, not 32 km.",
          f"- **The goal is never at risk from terrain.** Grade costs only +{sk} day skip-lean "
          f"with ~24 days of slack still in hand. Elevation shapes *which days are hard*, not "
          f"*whether you finish*.",
          f"- **It's a floor.** {meta['step_km']} km sampling misses short rolls and the 3 off-line "
          f"loop/buffer legs are great-circle estimates — true ascent (and time) is somewhat higher. "
          f"Treat crux-day timings as optimistic even after this penalty.",
          f"- **Tune in one place:** `CLIMB_MIN_PER_M` in `config.py` (Naismith = 0.10). Raise it "
          f"for a heavier pack / steeper-is-slower; re-run any scheduler to propagate."]

    OUT.write_text("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\n[written] {OUT.relative_to(HERE.parent)}")


def _crux_share(estops):
    tot = sum(v["ascent_m"] for v in estops.values()) or 1
    crux = sum(estops[str(o)]["ascent_m"] for z in difficulty.CRUX_ZONES
               for o in range(z["orders"][0], z["orders"][1] + 1) if str(o) in estops)
    return 100 * crux / tot


if __name__ == "__main__":
    main()
