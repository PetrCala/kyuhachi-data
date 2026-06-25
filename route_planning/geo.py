#!/usr/bin/env python3
"""Shared geometry + GPX helpers — the formerly copy-pasted utilities, in one place.

Previously duplicated across analyze_handdrawn / build_final_route / chunk_stages /
graft_nagasaki / remap_nagasaki_loop / logistics_overlay. All copies were byte-identical
(or trivially so); this is the single canonical version.
"""
from __future__ import annotations

import math
import xml.dom.minidom as minidom
from pathlib import Path

import numpy as np

R_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance (km), scalar. asin form (matches the numpy helpers)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R_KM * 2 * math.asin(math.sqrt(a))


def cumulative(lat, lon) -> np.ndarray:
    """Cumulative along-track distance (km) for pre-parsed lat/lon arrays."""
    la, lo = np.radians(lat), np.radians(lon)
    a = (np.sin(np.diff(la) / 2) ** 2
         + np.cos(la[:-1]) * np.cos(la[1:]) * np.sin(np.diff(lo) / 2) ** 2)
    return np.concatenate([[0.0], np.cumsum(R_KM * 2 * np.arcsin(np.sqrt(a)))])


def load_track(path):
    """Parse a GPX track -> (lat, lon, cum) numpy arrays (cum = along-track km)."""
    d = minidom.parse(str(path))
    tp = d.getElementsByTagName("trkpt")
    lat = np.array([float(t.getAttribute("lat")) for t in tp])
    lon = np.array([float(t.getAttribute("lon")) for t in tp])
    return lat, lon, cumulative(lat, lon)


def nearest_on_track(olat, olon, lat, lon, cum):
    """Nearest track point to (olat,olon). Returns (dist_km, along_km)."""
    la1, lo1 = math.radians(olat), math.radians(olon)
    la2, lo2 = np.radians(lat), np.radians(lon)
    a = (np.sin((la2 - la1) / 2) ** 2
         + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2)
    dist = R_KM * 2 * np.arcsin(np.sqrt(a))
    i = int(np.argmin(dist))
    return float(dist[i]), float(cum[i])


def nearest_idx(olat, olon, lat, lon) -> int:
    """Index of the nearest track vertex to (olat,olon) — for splicing."""
    la1 = math.radians(olat)
    lo1 = math.radians(olon)
    a = (np.sin((np.radians(lat) - la1) / 2) ** 2
         + np.cos(la1) * np.cos(np.radians(lat)) * np.sin((np.radians(lon) - lo1) / 2) ** 2)
    return int(np.argmin(R_KM * 2 * np.arcsin(np.sqrt(a))))


def decimate(track, step_km=1.0):
    """Sample a [(lat,lon),...] track ~every step_km, keeping first & last."""
    if len(track) < 2:
        return track
    out = [track[0]]
    acc = 0.0
    for i in range(1, len(track)):
        la1, lo1 = np.radians(track[i - 1])
        la2, lo2 = np.radians(track[i])
        a = (np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2)
        acc += R_KM * 2 * np.arcsin(np.sqrt(a))
        if acc >= step_km:
            out.append(track[i])
            acc = 0.0
    out.append(track[-1])
    return out


def write_gpx(path, track, stops, *, meta_name, trk_name, tag_fn=None):
    """Write a GPX of `track` ([(lat,lon),...]) + onsen waypoints from `stops`.
    `tag_fn(stop)` returns an optional suffix (e.g. ' [LOOP]')."""
    seg = "".join(f'<trkpt lat="{la:.6f}" lon="{lo:.6f}"></trkpt>' for la, lo in track)
    wpts = []
    for s in stops:
        nm = f'{s["order"]}. {s["area"]}：{s["name"]}'.replace("&", "&amp;").replace("<", "＜")
        tag = tag_fn(s) if tag_fn else ""
        wpts.append(f'<wpt lat="{s["lat"]:.6f}" lon="{s["lon"]:.6f}"><name>{nm}{tag}</name>'
                    f'<desc>{s["prefecture"]} #{s["id"]}</desc></wpt>')
    gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" '
           'creator="kyuhachi-data/route_planning" xmlns="http://www.topografix.com/GPX/1/1">\n'
           f'<metadata><name>{meta_name}</name></metadata>\n'
           + "\n".join(wpts) + f'\n<trk><name>{trk_name}</name><trkseg>{seg}</trkseg></trk>\n</gpx>\n')
    Path(path).write_text(gpx)
