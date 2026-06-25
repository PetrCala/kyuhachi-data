#!/usr/bin/env python3
"""OSRM foot-profile walking distances + route geometries, via curl.

Public OSRM demo server (routing.openstreetmap.de/routed-foot). We shell out to
curl because this machine's system-Python TLS can't negotiate with the server.
Ferry legs are rejected (foot-only, no islands). Haversine x1.3 is the fallback.
Both the NxN matrix and per-leg geometries are cached to JSON.
"""
from __future__ import annotations

import json
import subprocess
import time

from config import CACHE_DIR, ROAD_FACTOR
from geo import haversine_km

OSRM_BASE = "https://routing.openstreetmap.de/routed-foot"
DELAY = 1.15          # rate limit, slightly over 1 req/s
MAX_TABLE = 100       # max coords per table request on the demo server
GROUP = 50            # block size for chunked table requests


def _curl(url: str, tries: int = 3) -> dict:
    last = None
    for t in range(tries):
        p = subprocess.run(["curl", "-s", "-m", "40", url],
                           capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            try:
                return json.loads(p.stdout)
            except json.JSONDecodeError as e:
                last = e
        time.sleep(DELAY * (t + 1))
    raise RuntimeError(f"curl/OSRM failed after {tries} tries: {last}")


def _table(coords, sources=None, destinations=None) -> dict:
    cs = ";".join(f"{lon},{lat}" for lon, lat in coords)
    url = f"{OSRM_BASE}/table/v1/foot/{cs}?annotations=distance"
    if sources is not None:
        url += "&sources=" + ";".join(str(i) for i in sources)
    if destinations is not None:
        url += "&destinations=" + ";".join(str(i) for i in destinations)
    d = _curl(url)
    if d.get("code") != "Ok":
        raise RuntimeError(f"OSRM table error: {d.get('code')} {d.get('message','')}")
    return d


def build_matrix(coords, cache_name="osrm_matrix.json", refresh=False):
    """coords: list of (lon, lat). Returns NxN walking-distance matrix in km."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CACHE_DIR / cache_name
    key = json.dumps([(round(lo, 6), round(la, 6)) for lo, la in coords])
    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text())
        if cached.get("key") == key:
            print(f"  [osrm] matrix from cache ({cache_name})")
            return cached["matrix"]

    n = len(coords)
    M = [[0.0] * n for _ in range(n)]
    if n <= MAX_TABLE:
        print(f"  [osrm] table {n}x{n} single call...")
        d = _table(coords)
        for i in range(n):
            for j in range(n):
                v = d["distances"][i][j]
                M[i][j] = (v / 1000.0) if v is not None else \
                    haversine_km(coords[i][1], coords[i][0], coords[j][1], coords[j][0]) * ROAD_FACTOR
    else:
        groups = [list(range(s, min(s + GROUP, n))) for s in range(0, n, GROUP)]
        blocks = len(groups) ** 2
        b = 0
        for sg in groups:
            for dg in groups:
                b += 1
                if sg == dg:
                    cc = [coords[i] for i in sg]
                    src = list(range(len(sg)))
                    dst = list(range(len(sg)))
                else:
                    cc = [coords[i] for i in sg] + [coords[i] for i in dg]
                    src = list(range(len(sg)))
                    dst = list(range(len(sg), len(sg) + len(dg)))
                print(f"  [osrm] table block {b}/{blocks} ({len(cc)} coords)...")
                d = _table(cc, sources=src, destinations=dst)
                for ii, gi in enumerate(sg):
                    for jj, gj in enumerate(dg):
                        v = d["distances"][ii][jj]
                        M[gi][gj] = (v / 1000.0) if v is not None else \
                            haversine_km(coords[gi][1], coords[gi][0],
                                         coords[gj][1], coords[gj][0]) * ROAD_FACTOR
                if b < blocks:
                    time.sleep(DELAY)
    cache_path.write_text(json.dumps({"key": key, "matrix": M}))
    print(f"  [osrm] matrix cached -> {cache_name}")
    return M


def geometry(from_lon, from_lat, to_lon, to_lat, via=None, reject_ferry=True):
    """Return (coords[[lat,lon]...], distance_km) or (None, None) on fail/ferry.
    `via` = optional (lon,lat) waypoint, or a list of (lon,lat) waypoints, to
    force the route onto specific roads (e.g. Isahaya gate, or a highway chain)."""
    coords = [(from_lon, from_lat)]
    if via:
        if isinstance(via[0], (int, float)):   # single (lon, lat)
            coords.append((via[0], via[1]))
        else:                                  # list of (lon, lat)
            coords.extend(via)
    coords.append((to_lon, to_lat))
    pts = ";".join(f"{lo},{la}" for lo, la in coords)
    url = (f"{OSRM_BASE}/route/v1/foot/{pts}"
           f"?overview=full&geometries=geojson&steps=true")
    d = _curl(url)
    if d.get("code") != "Ok" or not d.get("routes"):
        return None, None
    route = d["routes"][0]
    if reject_ferry:
        for leg in route.get("legs", []):
            for step in leg.get("steps", []):
                if step.get("mode") == "ferry":
                    return None, None
    coords = route["geometry"]["coordinates"]  # [lon,lat]
    return [[lat, lon] for lon, lat in coords], route["distance"] / 1000.0


def fetch_geometries(legs, cache_name="osrm_geometries.json", refresh=False):
    """legs: list of (from_lon,from_lat,to_lon,to_lat, via_or_None). Returns list
    of (coords|None, dist_km|None), cached by endpoint(+via) key."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CACHE_DIR / cache_name
    cache = {}
    if cache_path.exists() and not refresh:
        cache = json.loads(cache_path.read_text())

    def key(flon, flat, tlon, tlat, via):
        v = f"@{via[0]:.6f},{via[1]:.6f}" if via else ""
        return f"{flon:.6f},{flat:.6f};{tlon:.6f},{tlat:.6f}{v}"

    out, fetched = [], 0
    todo = sum(1 for leg in legs if key(*leg) not in cache)
    for leg in legs:
        flon, flat, tlon, tlat, via = leg
        k = key(*leg)
        if k in cache:
            out.append(cache[k])
            continue
        coords, dist = geometry(flon, flat, tlon, tlat, via=via)
        cache[k] = [coords, dist]
        out.append(cache[k])
        fetched += 1
        print(f"  [osrm] geometry {fetched}/{todo}"
              + ("" if coords else "  (no route / ferry)"))
        time.sleep(DELAY)
    cache_path.write_text(json.dumps(cache))
    return out
