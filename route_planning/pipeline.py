#!/usr/bin/env python3
"""Regenerate the canonical final_route/ from the current hand-drawn line.

One command for "I edited the line (or the walk model) — rebuild everything":
  1. remap_nagasaki_loop  — apply the Nagasaki loop edit -> kyuhachi_nagasaki_loop.gpx
                            + handdrawn_loop_analysis.json   (needs OSRM for the loop legs)
  2. elevation            — SRTM per-leg ascent -> route_elevation.json + bake ascent_m
                            into the analysis (needs opentopodata; the grade penalty input)
  3. build_final_route    — package + chunk -> final_route/  (full GPX/map/itinerary + stages)
  4. logistics_overlay    — Overpass POIs + no-resupply gaps -> enhances final_route/

elevation runs AFTER remap (a re-snap drops ascent_m) and BEFORE build (so the
itinerary is grade-aware). OSRM/Overpass/SRTM results are cached (cache/), so
re-runs are fast and deterministic.
"""
from __future__ import annotations

import build_final_route
import elevation
import logistics_overlay
import remap_nagasaki_loop


def main():
    print("=== 1/4  remap: apply Nagasaki loop ===")
    remap_nagasaki_loop.main()
    print("\n=== 2/4  elevation: SRTM per-leg ascent -> grade penalty ===")
    elevation.main()
    print("\n=== 3/4  build_final_route: package + chunk -> final_route/ ===")
    build_final_route.main()
    print("\n=== 4/4  logistics_overlay: Overpass POIs + gaps ===")
    logistics_overlay.main()
    print("\nDone. final_route/ regenerated.")


if __name__ == "__main__":
    main()
