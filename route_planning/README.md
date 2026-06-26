# route_planning/

Foot-only route planner for the 九州八十八湯 (Kyushu-88) challenge. Plans a walking
route **on top of a hand-drawn GPX line**, against real onsen opening hours.

> For the conversational workflow, see the **`route-planning` skill**
> (`.claude/skills/route-planning/SKILL.md`). This README is the file map.

## The two layers

1. **The plan** — which onsens, what order, the hours-aware day schedule, all-7
   coverage. Computed by these scripts.
2. **The line** — the hand-drawn GPX (`config.HANDDRAWN_GPX`, drawn on
   plotaroute.com) is the **source of truth for the path**. We don't auto-route it.

Current route = hand-drawn line + Nagasaki loop = **109 onsens, all 7, ~1161 km,
finish ~Nov 7**. Output in `final_route/`.

## Workflow

```
hand-drawn GPX  +  snapshot.db (onsens + hours)
      │
  remap_nagasaki_loop.py   apply the Nagasaki loop edit (OSRM road-routing)
      │   → kyuhachi_nagasaki_loop.gpx + handdrawn_loop_analysis.json
  build_final_route.py     package + chunk into stages → final_route/
      │
  logistics_overlay.py     Overpass POIs + no-resupply gaps → enhances final_route/

  pipeline.py = all three, one command (run after editing the line or config.py)
```

## Files

| File | Role |
|---|---|
| **`config.py`** | the one source for anchors, walk model, dates, exclusions, paths |
| **`geo.py`** | shared helpers: haversine, load_track, cumulative, nearest_*, decimate, write_gpx |
| `onsen_model.py` | load onsens + parse Japanese `business_hours` |
| `osrm.py` | OSRM foot distance matrix + geometries (via curl), cached |
| `simulate.py` | hours-aware day-by-day schedule simulator |
| `analyze_handdrawn.py` | snap onsens to the line; coverage + schedule (no edits) |
| `remap_nagasaki_loop.py` | **edit pattern A**: remap a section onto specific roads (`LEG_VIAS`) |
| `graft_nagasaki.py` | **edit pattern B**: add an out-and-back spur (`SPUR_IDS`) |
| `build_final_route.py` | package the route + chunk into stages |
| `logistics_overlay.py` | OpenStreetMap services + gap analysis |
| `pipeline.py` | run remap → build → logistics |
| `fetch_strava_walks.py` | re-derive walking speed from Strava |
| `final_route/` | **canonical output** (regenerable): full GPX/map/itinerary + 8 stages |
| `cache/` | OSRM + Overpass caches (regenerable) |
| `archive/` | superseded scripts (great-circle solver, OSRM auto-router, …) + old artifacts — reference only, not runnable from there |

## Data sources

- `data/snapshot.db` — onsen catalog + opening hours (read-only).
- `config.HANDDRAWN_GPX` — the path (`kyuhachi/local/route_26_02_14/Kyuhachi-3.gpx`).
- `~/code/onsendo` — real per-visit dwell time (`onsen_visits`) + Strava walking speed.

## Not done (Tier 2/3, if this becomes a recurring tool)

- Consolidate the per-script `write_map` HTML behind one flexible Leaflet template
  (left divergent on purpose — route vs spur vs loop vs stage vs stage+POI).
- Promote to a `trail/` package + an argparse CLI (`trail snap|edit|build|logistics`)
  with tests.
