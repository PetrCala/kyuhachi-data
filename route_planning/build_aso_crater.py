#!/usr/bin/env python3
"""Build the OPTIONAL Aso-crater climb-spur as a STANDALONE gpx that branches off
the main onsen route (the main route is left untouched).

It attaches at the main line's nearest vertex to 草千里 (right by 地獄/垂玉), then
routes on OSRM foot roads up to 草千里ヶ浜 → 阿蘇山上 (中岳 crater viewpoint) and
back — an out-and-back sightseeing side-trip (~+400 m climb). Load it alongside
00_full_route.gpx and it visibly forks from the main line at the junction.

Outputs: aso_crater_spur.gpx, aso_crater_map.html
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

import osrm
from geo import haversine_km

HERE = Path(__file__).resolve().parent
MAIN_GPX = HERE / "final_route" / "00_full_route.gpx"
NS = "{http://www.topografix.com/GPX/1/1}"

# sightseeing targets (lon, lat) — accessible crater viewpoint, not the restricted rim
KUSASENRI = (131.0760, 32.8855)   # 草千里ヶ浜
SANJO = (131.0866, 32.8846)       # 阿蘇山上広場 / ropeway (中岳火口 viewpoint)
WPTS = [("草千里ヶ浜 Kusasenri (~1140 m)", KUSASENRI),
        ("阿蘇山上・中岳火口 viewpoint (~1100 m)", SANJO)]


def main():
    main_line = [(float(p.get("lat")), float(p.get("lon")))
                 for p in ET.parse(MAIN_GPX).iter(f"{NS}trkpt")]
    la = np.array([p[0] for p in main_line]); lo = np.array([p[1] for p in main_line])
    # junction = nearest main-line vertex to 草千里 (lands at 地獄/垂玉)
    d = np.array([haversine_km(KUSASENRI[1], KUSASENRI[0], a, b) for a, b in zip(la, lo)])
    j = int(np.argmin(d))
    jlat, jlon = main_line[j]
    print(f"junction @ ({jlat:.4f},{jlon:.4f})  (main-line vertex nearest 草千里, {d[j]:.1f} km out)")

    legs = [(jlon, jlat, *KUSASENRI), (*KUSASENRI, *SANJO), (*SANJO, jlon, jlat)]
    labels = ["junction→草千里", "草千里→阿蘇山上", "阿蘇山上→junction"]
    track, km = [], 0.0
    for (flon, flat, tlon, tlat), lab in zip(legs, labels):
        g, dist = osrm.geometry(flon, flat, tlon, tlat)
        if g is None:
            print(f"  WARN no foot route {lab}; straight fallback")
            g = [[flat, flon], [tlat, tlon]]; dist = haversine_km(flat, flon, tlat, tlon)
        track += g
        km += dist
        print(f"  {lab:22} {dist:5.1f} km")
    print(f"Crater spur out-and-back: {km:.1f} km (+~400 m climb)")

    write_gpx(track, jlat, jlon, km)
    write_map(main_line, track, jlat, jlon, km)
    print("Wrote aso_crater_spur.gpx, aso_crater_map.html")


def write_gpx(track, jlat, jlon, km):
    def wpt(lat, lon, name):
        return (f'  <wpt lat="{lat:.6f}" lon="{lon:.6f}"><name>{name}</name></wpt>')
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="kyuhachi-aso-crater" '
             'xmlns="http://www.topografix.com/GPX/1/1">',
             f'  <metadata><name>Aso crater optional spur (+{km:.1f} km, ~400 m climb)</name></metadata>',
             wpt(jlat, jlon, "⛰ JUNCTION — leave main route here (地獄/垂玉)")]
    for name, (lon, lat) in WPTS:
        parts.append(wpt(lat, lon, name))
    parts.append('  <trk><name>Aso crater spur</name><trkseg>')
    for lat, lon in track:
        parts.append(f'    <trkpt lat="{lat:.6f}" lon="{lon:.6f}"></trkpt>')
    parts.append('  </trkseg></trk>')
    parts.append('</gpx>')
    (HERE / "aso_crater_spur.gpx").write_text("\n".join(parts), encoding="utf-8")


def write_map(main_line, track, jlat, jlon, km):
    wp = [{"lat": jlat, "lon": jlon, "name": "JUNCTION (leave main route)", "c": "#d50000"}]
    wp += [{"lat": lat, "lon": lon, "name": name, "c": "#00695c"} for name, (lon, lat) in WPTS]
    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Aso crater optional spur (+{km:.1f} km)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body{{margin:0;height:100%;font-family:system-ui,sans-serif}}#map{{height:100%}}
.pin{{color:#fff;border-radius:50%;width:14px;height:14px;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.5)}}</style>
</head><body><div id="map"></div><script>
const MAIN={json.dumps(main_line)};const SPUR={json.dumps(track)};const WP={json.dumps(wp, ensure_ascii=False)};
const map=L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:18,attribution:'&copy; OpenStreetMap'}}).addTo(map);
L.polyline(MAIN,{{color:'#90a4ae',weight:3,opacity:.6}}).addTo(map);
L.polyline(SPUR,{{color:'#d50000',weight:5,opacity:.95}}).addTo(map);
WP.forEach(p=>{{L.marker([p.lat,p.lon],{{icon:L.divIcon({{className:'',html:`<div class="pin" style="background:${{p.c}}"></div>`,iconSize:[14,14],iconAnchor:[7,7]}})}}).addTo(map).bindPopup(p.name);}});
map.fitBounds(SPUR);
</script></body></html>"""
    (HERE / "aso_crater_map.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
