---
name: route-planning
description: Plan and edit the foot-only Kyushu-88 route. Snaps onsens onto a
  hand-drawn GPX line, edits sections via OSRM road-routing, schedules against
  real opening hours, chunks into stages, and overlays logistics. Reads the
  catalog/Strava data; writes only route outputs under route_planning/ — never
  the snapshot DB or Firestore. Use to re-solve, re-route, or re-validate the
  walking route.
---

# route-planning

The foot-route planner lives in `route_planning/`. It is a small set of Python
scripts sharing one config (`config.py`) and one helper module (`geo.py`).

**The mental model — two layers:**

1. **The plan** — *which* onsens, in *what order*, the hours-aware day schedule,
   all-7 coverage. This is what the scripts compute.
2. **The line** — the actual meters walked between onsens. The **hand-drawn GPX
   is the source of truth for the path** (drawn by the user on plotaroute.com).
   We plan *on top of* it; we do not auto-generate the line (OSRM auto-routing
   picks impractical trails — superseded, see `archive/build_route_osrm.py`).

Current best route = the hand-drawn line + a Nagasaki loop edit = **109 onsens,
all 7 prefectures, ~1161 km, finishes ~Nov 7 (25 days slack)**. Packaged in
`route_planning/final_route/`.

## When to use

- "Re-solve / re-validate the foot route" — does it still hit all 7 prefectures
  and ≥88, what's the day count, where are the no-resupply gaps.
- "The route should go through X instead" / "reroute the <region> section."
- "Add onsen Y" or "pick up the onsens near Z."
- "Re-derive my walking speed" / "change the soak time / deadline and re-schedule."

## Steps

Run from the **repo root** (each script puts `route_planning/` on `sys.path`):

1. **Rebuild everything after a change** (the common path):
   `python route_planning/pipeline.py`
   Chains: apply the Nagasaki loop → package into `final_route/` → overlay
   logistics. OSRM + Overpass are cached (`route_planning/cache/`), so it's fast.

2. **The user re-drew the line** (new plotaroute export): point `HANDDRAWN_GPX`
   in `route_planning/config.py` at the new file, then run the pipeline.

3. **Analyze the line standalone** (coverage + schedule, no edits):
   `python route_planning/analyze_handdrawn.py` → prints which onsens the line
   passes, prefecture coverage, and the hours-aware finish date.

4. **Edit a section onto specific roads** — the most common surgery. In
   `route_planning/remap_nagasaki_loop.py`, the `LEG_VIAS` list pins each leg to
   real highways via waypoints; `SPLICE_START_ID`/`SPLICE_END_ID` bound the
   replaced section. Copy this pattern for other regions, then run the pipeline.

5. **Add an out-and-back spur** (pick up off-line onsens): see
   `route_planning/graft_nagasaki.py` — set `SPUR_IDS`, it attaches at the line's
   nearest point and routes the spur on OSRM roads.

6. **Re-derive the walk model**: `python route_planning/fetch_strava_walks.py`
   refreshes walking speed from Strava (token in the `onsendo` repo). Soak time
   comes from `onsendo`'s `onsen_visits.stay_length_minutes` (median 13 min).

## Data sources / source-of-truth

| What | Where |
|---|---|
| Onsen catalog + opening hours | `data/snapshot.db` (read-only) |
| The path (hand-drawn line) | `config.HANDDRAWN_GPX` (plotaroute export) |
| Real soak time + walking speed | `~/code/onsendo` (`onsen_visits`, Strava sync) |
| All shared constants | `route_planning/config.py` |

## Locked decisions (do not re-litigate)

- Fixed endpoints: START = Cape 長崎鼻 (`config.START`), END = #41 浜脇 茶房たかさき.
- **No ferries / no islands.** `config.OFFSHORE_IDS` excluded live; Sakurajima/
  east-bay, east-Miyazaki, Amakusa are policy exclusions.
- Target: **all 7 prefectures + ≥88 onsens**, finish before **Dec 2 2026**.

## Gotchas (hard-won)

- **OSRM foot silently uses ferries** and the demo server has no `exclude=ferry`.
  Any trans-Ariake-Sea pair (Kumamoto/Fukuoka ↔ Nagasaki) is an invalid ferry
  shortcut. When routing into Nagasaki, attach only via the Saga isthmus by land
  and verify the final route has **0 ferry/none legs** (the geometry fetch
  rejects ferries → `None`).
- **Via-points must sit on the actual road**, or OSRM detours (a 263 via once
  looped through mountains). When in doubt, keep the user's hand-drawn geometry
  for that stretch instead of re-routing.
- **Caching**: OSRM matrix/geometry and Overpass POIs cache under
  `route_planning/cache/`. City stages time out on `overpass-api.de` — mirrors +
  per-stage cache (`overpass_stage_NN.json`) handle it; re-run retries only fails.
- **`drinking_water` and `camp_site` are badly under-tagged in Japan** — vending
  machines/conbini are the real water source. Trust the 🏪 conbini layer, not the
  scary 💧 water gaps.

## Validation

After any edit, confirm from the run output / `final_route/README.md`:
all 7 prefectures present · ≥88 banked · finish before Dec 2 · **0 ferry legs**.

## Guarantees

- Read-only against the catalog (`snapshot.db`) and Firestore — never writes them.
- Writes only route artifacts under `route_planning/` (`final_route/`, the loop
  intermediates, `cache/`). All are regenerable by `pipeline.py`.
- Needs outbound HTTP for OSRM (route edits) and Overpass (logistics); both cache.
