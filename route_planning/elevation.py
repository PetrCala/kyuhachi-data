#!/usr/bin/env python3
"""Per-leg elevation gain for the foot route — the input to simulate's grade penalty.

Why: simulate's base model walks every leg at a flat 4 km/h. Kyushu-88 has real
climbs (Kirishima, Aso south rim, the Kuju massif). This samples an SRTM-30 m
profile ALONG the hand-drawn line (the same dataset difficulty.py's crux notes
came from), folds the onsen stops onto it, and emits the ascent/descent on the
leg INTO each stop. simulate then adds a Naismith climb-time term per leg.

Method:
  - Decimate the raw hand-drawn line (config.HANDDRAWN_GPX) to ~STEP_KM and query
    opentopodata srtm30m for each point -> elevation profile -> cumulative ascent
    vs along-track km. Per-leg ascent = Δ cumulative ascent between the two stops'
    along-km (captures rolling up-AND-over, not just net endpoint difference).
  - The 7 onsens off the raw line (the Nagasaki loop 嬉野/波佐見/武雄 + the optional
    Beppu buffers) don't have a valid along-km, so any leg touching one is sampled
    directly: SRTM along the great-circle between the two onsen points instead.

Sampling at ~STEP_KM misses sub-STEP_KM rolls, so the totals are a FLOOR (a small
underestimate) — fine for a conservative climb penalty. opentopodata's public
tier is 100 locations/request, 1 req/s, 1000/day; one run stays well under.

Network (SRTM). Run once; writes the committed route_elevation.json so simulate
needs no network. Read-only against the catalog. Regenerate if the line changes.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import numpy as np

import geo
from config import ELEVATION_JSON, HANDDRAWN_GPX, START

HERE = Path(__file__).resolve().parent
ANALYSIS = HERE / "handdrawn_loop_analysis.json"
OUT = ELEVATION_JSON                          # route_elevation.json (the record)
CACHE = HERE / "cache"

STEP_KM = 1.5            # along-line sampling spacing (difficulty.py used ~1.3 km)
OFFLINE_KM = 3.0         # snap farther than this -> sample the leg directly
DEM = "srtm30m"


_last_call = [0.0]


def _throttle(min_gap=1.1):
    """opentopodata public tier is 1 req/s — keep a global min gap between calls."""
    wait = min_gap - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()


def _elev_batch(pts):
    """opentopodata srtm30m elevations for [(lat,lon),...] (<=100), via curl."""
    locs = "|".join(f"{la:.6f},{lo:.6f}" for la, lo in pts)
    url = f"https://api.opentopodata.org/v1/{DEM}?locations={locs}"
    for attempt in range(4):
        _throttle()
        p = subprocess.run(["curl", "-s", "-m", "60", url], capture_output=True, text=True)
        try:
            d = json.loads(p.stdout)
            if d.get("status") == "OK":
                return [r["elevation"] for r in d["results"]]
        except Exception:
            pass
        time.sleep(2 + attempt)
    raise RuntimeError(f"opentopodata failed for batch of {len(pts)}: {p.stdout[:200]}")


def elevations(pts, label=""):
    """Elevation (m) for many points, batched 100/req at ~1 req/s. None->interp."""
    out = []
    for i in range(0, len(pts), 100):
        out += _elev_batch(pts[i:i + 100])
        print(f"  …{label} {min(i+100, len(pts))}/{len(pts)}")
    e = np.array([np.nan if v is None else float(v) for v in out])
    if np.isnan(e).any():                          # SRTM voids -> linear interp
        ok = ~np.isnan(e)
        e[~ok] = np.interp(np.flatnonzero(~ok), np.flatnonzero(ok), e[ok])
    return e


def cum_climb(elev):
    """(cum_ascent, cum_descent) arrays from an elevation profile."""
    d = np.diff(elev)
    asc = np.concatenate([[0.0], np.cumsum(np.clip(d, 0, None))])
    desc = np.concatenate([[0.0], np.cumsum(np.clip(-d, 0, None))])
    return asc, desc


def great_circle_pts(a, b, step_km):
    """Points every ~step_km along the great circle a->b (inclusive of both)."""
    (la1, lo1), (la2, lo2) = a, b
    dist = geo.haversine_km(la1, lo1, la2, lo2)
    n = max(1, int(dist / step_km))
    return [(la1 + (la2 - la1) * t, lo1 + (lo2 - lo1) * t) for t in np.linspace(0, 1, n + 1)]


def leg_climb_direct(a, b):
    """Ascent/descent (m) sampled directly along a->b (for off-line legs)."""
    pts = great_circle_pts(a, b, STEP_KM)
    e = elevations(pts, label="direct")
    asc, desc = cum_climb(e)
    return float(asc[-1]), float(desc[-1])


def main():
    stops = json.loads(ANALYSIS.read_text())["stops"]
    lat, lon, cum = geo.load_track(HANDDRAWN_GPX)

    # 1) elevation profile along the raw line. Everything below is indexed on the
    #    SAME decimated polyline (along, elevation, cumulative climb all aligned) —
    #    don't mix the full-line cum with the decimated profile, the two lengths
    #    differ and the along-positions drift.
    line = geo.decimate(list(zip(lat.tolist(), lon.tolist())), STEP_KM)
    print(f"raw line {cum[-1]:.0f} km -> {len(line)} samples @ {STEP_KM} km")
    dlat = np.array([p[0] for p in line])
    dlon = np.array([p[1] for p in line])
    dalong = geo.cumulative(dlat, dlon)
    CACHE.mkdir(exist_ok=True)
    elev_cache = CACHE / f"line_elev_{len(line)}.json"            # regenerable, gitignored
    if elev_cache.exists():
        print(f"  (line elevations from cache {elev_cache.name})")
        delev = np.array(json.loads(elev_cache.read_text()))
    else:
        delev = elevations(line, label="line")
        elev_cache.write_text(json.dumps(delev.tolist()))
    asc, desc = cum_climb(delev)

    # 2) per-leg ascent: each onsen -> nearest decimated sample (for elev + cum
    #    climb); off-line stops (loop/buffer) are sampled directly point-to-point.
    prev_pt = (START[1], START[2])               # start anchor (name,lat,lon)
    prev_idx, prev_off = 0, False
    out = {}
    for s in stops:
        pt = (s["lat"], s["lon"])
        d, _ = geo.nearest_on_track(s["lat"], s["lon"], lat, lon, cum)   # true snap dist
        off = d > OFFLINE_KM
        idx = geo.nearest_idx(s["lat"], s["lon"], dlat, dlon)
        if off or prev_off:
            a_m, de_m, method = *leg_climb_direct(prev_pt, pt), "direct"
        else:
            a_m = max(0.0, float(asc[idx] - asc[prev_idx]))
            de_m = max(0.0, float(desc[idx] - desc[prev_idx]))
            method = "line"
        out[str(s["order"])] = {
            "order": s["order"], "area": s["area"], "pref": s["pref_short"],
            "elev_m": round(_pt_elev(pt) if off else float(delev[idx]), 1),
            "snap_km": round(d, 2), "along_km": round(float(dalong[idx]), 1),
            "ascent_m": round(a_m), "descent_m": round(de_m), "method": method,
        }
        prev_pt, prev_idx, prev_off = pt, idx, off

    meta = {
        "dem": DEM, "step_km": STEP_KM, "line_km": round(float(cum[-1]), 1),
        "line_samples": len(line),
        "total_ascent_m": round(sum(v["ascent_m"] for v in out.values())),
        "total_descent_m": round(sum(v["descent_m"] for v in out.values())),
        "note": "ascent_m/descent_m = climb on the leg INTO this stop; a FLOOR "
                f"(misses sub-{STEP_KM}km rolls).",
    }
    OUT.write_text(json.dumps({"meta": meta, "stops": out}, ensure_ascii=False, indent=2))
    CACHE.mkdir(exist_ok=True)
    (CACHE / "elev_profile.json").write_text(json.dumps(
        {"along_km": dalong.round(3).tolist(), "elev_m": delev.round(1).tolist()}))

    # 3) bake ascent_m/descent_m back into the analysis so the route is SELF-
    #    describing — simulate reads s["ascent_m"] directly, no global lookup that
    #    could be mis-applied to a differently-ordered route. (Regenerate after any
    #    remap re-snap; a missing field just degrades to the flat model.)
    analysis = json.loads(ANALYSIS.read_text())
    for s in analysis["stops"]:
        v = out[str(s["order"])]
        s["ascent_m"], s["descent_m"] = v["ascent_m"], v["descent_m"]
    ANALYSIS.write_text(json.dumps(analysis, ensure_ascii=False, indent=2))

    # 4) validate against difficulty.py's known climbs
    print(f"\n[written] {OUT.name}  —  total ascent {meta['total_ascent_m']:,} m "
          f"over {meta['line_km']:.0f} km")
    top = sorted(out.values(), key=lambda v: -v["ascent_m"])[:10]
    print("\nbiggest climb legs (leg INTO the named onsen):")
    for v in top:
        print(f"  +{v['ascent_m']:>4} m  #{v['order']:>3} {v['pref']} {v['area']} "
              f"(onsen elev {v['elev_m']:.0f} m, {v['method']})")


def _pt_elev(pt):
    return float(elevations([pt], label="pt")[0])


if __name__ == "__main__":
    main()
