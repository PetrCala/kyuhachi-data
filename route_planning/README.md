# route_planning/

Foot-only route planner for the 九州八十八湯 (Kyushu-88) challenge. Plans a walking
route **on top of a hand-drawn GPX line**, against real onsen opening hours.

> For the conversational workflow, see the **`route-planning` skill**
> (`.claude/skills/route-planning/SKILL.md`). This README is the file map.

## The two layers

1. **The plan** — which onsens, in what order, the hours-aware schedule, all-7
   coverage. Computed by these scripts.
2. **The line** — the hand-drawn GPX (`config.HANDDRAWN_GPX`, drawn on
   plotaroute.com) is the **source of truth for the path**. We don't auto-route it;
   we splice surgical edits (the Nagasaki loop, out-and-back spurs) onto it.

**Current route** = hand-drawn line + Nagasaki loop + spurs = **119 onsens
(115 core + 4 optional buffer), all 7 prefectures, ~1205 km.** Packaged in
`final_route/`.

**Realistic schedule** (12 h walking day, ~50 min blended visit, skip-lean):
**~37 days, finish ~Nov 7, ~25 days slack** to the Dec 2 deadline. Visiting all 119
*and* waiting out every closure is the ~50-day upper bound — you skip-lean instead
(see `decision_card.md`). Walk model in `config.py`, scheduler in `simulate.py`.

## Workflow

```
data/snapshot.db  +  new_onsens_staged.json
   └─ build_overlay_db.py → cache/snapshot_overlay.db   (baseline + staged new onsens)

hand-drawn GPX  +  overlay catalog (via KYUHACHI_SNAPSHOT_DB)
   ├─ remap_nagasaki_loop.py   Nagasaki loop + grafted spurs (OSRM) → handdrawn_loop_analysis.json
   ├─ build_final_route.py     package + chunk into stages → final_route/
   └─ logistics_overlay.py     Overpass POIs + no-resupply gaps → enhances final_route/

   pipeline.py = remap → build → logistics, one command.

# run route scripts against the overlay catalog:
KYUHACHI_SNAPSHOT_DB=route_planning/cache/snapshot_overlay.db python route_planning/pipeline.py
```

## Files

| File | Role |
|---|---|
| **`config.py`** | one source for anchors, walk model (12 h day, ~50 min visit), dates, exclusions, paths |
| **`geo.py`** | shared helpers: haversine, load_track, cumulative, nearest_*, decimate, write_gpx |
| `onsen_model.py` | load onsens + parse Japanese `business_hours` |
| `osrm.py` | OSRM foot distance matrix + geometries (via curl), cached |
| `simulate.py` | hours-aware day-by-day schedule simulator (patient / skip policies) |
| `difficulty.py` | crux-zone warnings injected into the itinerary |
| `build_overlay_db.py` | build the route-only overlay catalog (baseline + staged new onsens) |
| `analyze_handdrawn.py` | snap onsens to the raw line; coverage + schedule (no edits) |
| `remap_nagasaki_loop.py` | the route builder: Nagasaki loop + out-and-back spurs (`SPURS`) |
| `graft_nagasaki.py` | standalone spur-only pattern (reference for the splice technique) |
| `build_final_route.py` | package the route + chunk into stages → `final_route/` |
| `logistics_overlay.py` | OpenStreetMap services + no-resupply gap analysis |
| `pipeline.py` | run remap → build → logistics |
| `build_aso_crater.py` | optional standalone Aso-crater climb-spur GPX |
| `fetch_strava_walks.py` | re-derive walking speed from Strava |
| `new_onsens_staged.json` | staged catalog delta (13 added / 1 removed) folded into the overlay |
| `strava_walk_summary.json` | Strava-derived walk-speed summary (walk-model input) |
| `handdrawn_loop_analysis.json` | snapped onsens + along-track order (the schedule tools' input) |
| `final_route/` | **canonical output** (regenerable): full GPX/map/itinerary + README + 8 stages |
| `decision_card.md` | the one-page on-trail decision card (print it) |
| `aso_crater_spur.gpx` · `aso_crater_map.html` | optional Aso-crater side-trip |
| `cache/` | OSRM/Overpass caches + overlay DB — **gitignored**, regenerable |

## Data sources

- `data/snapshot.db` — onsen catalog + opening hours (read-only baseline).
- `cache/snapshot_overlay.db` — route-only overlay (baseline + staged new onsens),
  built by `build_overlay_db.py`, selected via `KYUHACHI_SNAPSHOT_DB`. Never mutates
  the baseline.
- `config.HANDDRAWN_GPX` — the path (`kyuhachi/local/route_26_02_14/Kyuhachi-3.gpx`).
- `~/code/onsendo` — real visit time (`onsen_visits`) + Strava walking speed.
