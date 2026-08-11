#!/usr/bin/env python3
"""Regenerate everything downstream of the hand-drawn line.

One command for "I edited the line (or the walk model), rebuild it all":
  1. remap_nagasaki_loop  apply the Nagasaki loop edit -> kyuhachi_nagasaki_loop.gpx
                          + handdrawn_loop_analysis.json   (needs OSRM for the loop legs)
  2. elevation            SRTM per-leg ascent -> route_elevation.json + bake ascent_m
                          into the analysis (needs opentopodata; the grade penalty input)
  3. build_final_route    package + chunk -> final_route/  (full GPX/map/itinerary + stages)
  4. logistics_overlay    Overpass POIs + no-resupply gaps -> enhances final_route/
  5. plan_octnov          the day-by-day plan you carry -> plan_octnov.md + .json
  6. render_html          standalone offline HTML of the reports -> html/

elevation runs AFTER remap (a re-snap drops ascent_m) and BEFORE build (so the
itinerary is grade-aware). plan runs last because it consumes both the re-snapped
analysis and final_route/logistics.json. OSRM/Overpass/SRTM results are cached
(cache/), so re-runs are fast and deterministic.

Steps 1 to 4 need network. Steps 5 and 6 do not, and are the ones you actually
re-run day to day:

    python route_planning/plan_octnov.py          # re-plan (deadline, pace, wait dial)
    python route_planning/render_html.py --open   # re-read it in a browser

so `--plan-only` skips straight to those.
"""
from __future__ import annotations

import sys

import build_final_route
import elevation
import logistics_overlay
import plan_octnov
import remap_nagasaki_loop
import render_html


def main():
    plan_only = "--plan-only" in sys.argv
    if not plan_only:
        print("=== 1/6  remap: apply Nagasaki loop ===")
        remap_nagasaki_loop.main()
        print("\n=== 2/6  elevation: SRTM per-leg ascent -> grade penalty ===")
        elevation.main()
        print("\n=== 3/6  build_final_route: package + chunk -> final_route/ ===")
        build_final_route.main()
        print("\n=== 4/6  logistics_overlay: Overpass POIs + gaps ===")
        logistics_overlay.main()
    else:
        print("--plan-only: skipping the route rebuild (steps 1 to 4)")
    print("\n=== 5/6  plan_octnov: the day-by-day plan ===")
    plan_octnov.main([])
    print("\n=== 6/6  render_html: offline HTML reports ===")
    # --open and --app are the only flags worth forwarding here.
    passthru = [a for a in sys.argv[1:] if a in ("--open",)]
    if "--app" in sys.argv:
        passthru += ["--app", sys.argv[sys.argv.index("--app") + 1]]
    render_html.main(passthru)
    print("\nDone." if plan_only else "\nDone. final_route/ and the plan regenerated.")


if __name__ == "__main__":
    main()
