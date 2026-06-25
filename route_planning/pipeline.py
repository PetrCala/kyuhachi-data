#!/usr/bin/env python3
"""Regenerate the canonical final_route/ from the current hand-drawn line.

One command for "I edited the line (or the walk model) — rebuild everything":
  1. remap_nagasaki_loop  — apply the Nagasaki loop edit -> kyuhachi_nagasaki_loop.gpx
                            + handdrawn_loop_analysis.json   (needs OSRM for the loop legs)
  2. build_final_route    — package + chunk -> final_route/  (full GPX/map/itinerary + stages)
  3. logistics_overlay    — Overpass POIs + no-resupply gaps -> enhances final_route/

OSRM + Overpass results are cached (cache/), so re-runs are fast and deterministic.
"""
from __future__ import annotations

import build_final_route
import logistics_overlay
import remap_nagasaki_loop


def main():
    print("=== 1/3  remap: apply Nagasaki loop ===")
    remap_nagasaki_loop.main()
    print("\n=== 2/3  build_final_route: package + chunk -> final_route/ ===")
    build_final_route.main()
    print("\n=== 3/3  logistics_overlay: Overpass POIs + gaps ===")
    logistics_overlay.main()
    print("\nDone. final_route/ regenerated.")


if __name__ == "__main__":
    main()
