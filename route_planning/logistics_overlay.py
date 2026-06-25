#!/usr/bin/env python3
"""Logistics overlay (Direction C): pull services from OpenStreetMap (Overpass)
along each stage of the final route, flag no-resupply gaps, and regenerate the
stage maps with toggleable POI layers.

Categories: conbini, supermarket, food (restaurant/fast_food/cafe), water
(drinking_water), lodging (hotel/guest_house/hostel/motel), campsite, station.

Outputs (into final_route/): rewrites stage_NN_map.html with POI layers,
writes logistics.json, appends a "Logistics" section to README.md.
"""
from __future__ import annotations

import json
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from geo import decimate, load_track

HERE = Path(__file__).resolve().parent
OUT = HERE / "final_route"
TRACK_GPX = HERE / "kyuhachi_nagasaki_loop.gpx"
ANALYSIS = HERE / "handdrawn_loop_analysis.json"
N_STAGES = 8
BUFFER_M = 1000          # POIs within 1 km of the line
DECIMATE_KM = 1.2        # sample the line every ~1.2 km for the around-query
RESUPPLY_GAP_KM = 10.0   # flag stretches longer than this with no food/conbini/lodging
WATER_GAP_KM = 15.0
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
CACHE = HERE / "cache"

CAT_STYLE = {  # category: (emoji, color, default_on)
    "conbini":    ("🏪", "#00897b", True),
    "supermarket":("🛒", "#00695c", True),
    "food":       ("🍴", "#fb8c00", False),
    "water":      ("💧", "#039be5", True),
    "lodging":    ("🛏", "#3949ab", True),
    "campsite":   ("⛺", "#2e7d32", True),
    "station":    ("🚉", "#8e24aa", True),
}
RESUPPLY = {"conbini", "supermarket", "food", "lodging"}
PREF_COLORS = {"福岡県": "#e6194B", "佐賀県": "#f58231", "長崎県": "#ffe119",
               "熊本県": "#3cb44b", "大分県": "#4363d8", "宮崎県": "#911eb4", "鹿児島県": "#f032e6"}


def categorize(tags):
    if tags.get("shop") == "convenience":
        return "conbini"
    if tags.get("shop") == "supermarket":
        return "supermarket"
    if tags.get("amenity") in ("restaurant", "fast_food", "cafe"):
        return "food"
    if tags.get("amenity") == "drinking_water":
        return "water"
    if tags.get("tourism") in ("hotel", "guest_house", "hostel", "motel"):
        return "lodging"
    if tags.get("tourism") == "camp_site":
        return "campsite"
    if tags.get("railway") == "station":
        return "station"
    return None


def overpass(poly_pts, stage_n):
    """Query Overpass for one stage, with per-stage caching + mirror fallback.
    Returns (elements, ok). ok=False only when every mirror failed."""
    CACHE.mkdir(exist_ok=True)
    cache_path = CACHE / f"overpass_stage_{stage_n:02d}.json"
    if cache_path.exists():
        print(f"  [overpass] stage {stage_n} from cache")
        return json.loads(cache_path.read_text()), True

    poly = ",".join(f"{la:.5f},{lo:.5f}" for la, lo in poly_pts)
    q = (f"[out:json][timeout:180];("
         f'node(around:{BUFFER_M},{poly})["shop"~"^(convenience|supermarket)$"];'
         f'node(around:{BUFFER_M},{poly})["amenity"~"^(restaurant|fast_food|cafe|drinking_water)$"];'
         f'node(around:{BUFFER_M},{poly})["tourism"~"^(camp_site|hotel|guest_house|hostel|motel)$"];'
         f'node(around:{BUFFER_M},{poly})["railway"="station"];'
         f");out center;")
    for mirror in OVERPASS_MIRRORS:
        for t in range(2):
            p = subprocess.run(["curl", "-s", "-m", "200", "-X", "POST", mirror,
                                "--data-urlencode", f"data={q}"], capture_output=True, text=True)
            if p.returncode == 0 and p.stdout.strip().startswith("{"):
                try:
                    els = json.loads(p.stdout)["elements"]
                    cache_path.write_text(json.dumps(els))
                    return els, True
                except Exception:
                    pass
            time.sleep(6 * (t + 1))
        print(f"  [overpass] stage {stage_n}: mirror failed, trying next...")
    print(f"  [overpass] stage {stage_n} FAILED on all mirrors")
    return [], False


def project_along(plat, plon, lat, lon, cum):
    R = 6371.0
    la1 = np.radians(plat)
    lo1 = np.radians(plon)
    a = (np.sin((np.radians(lat) - la1) / 2) ** 2
         + np.cos(la1) * np.cos(np.radians(lat)) * np.sin((np.radians(lon) - lo1) / 2) ** 2)
    dd = R * 2 * np.arcsin(np.sqrt(a))
    j = int(np.argmin(dd))
    return float(cum[j]), float(dd[j])


def main():
    lat, lon, cum = load_track(TRACK_GPX)
    total = float(cum[-1])
    stops = json.loads(ANALYSIS.read_text())["stops"]

    # rebuild the same stage chunking as build_final_route
    target = total / N_STAGES
    stage_of, k = [], 0
    for s in stops:
        while k < N_STAGES - 1 and s["along_km"] > (k + 1) * target:
            k += 1
        stage_of.append(k)

    all_pois = {}  # id -> poi
    stages = []
    failed_stages = []
    for sidx in range(N_STAGES):
        members = [s for s, st in zip(stops, stage_of) if st == sidx]
        if not members:
            continue
        a_km = 0.0 if sidx == 0 else members[0]["along_km"]
        b_km = total if sidx == N_STAGES - 1 else members[-1]["along_km"]
        mask = (cum >= max(0, a_km - 1)) & (cum <= min(total, b_km + 1))
        track = [(float(la), float(lo)) for la, lo in zip(lat[mask], lon[mask])]
        poly = decimate(track, DECIMATE_KM)
        print(f"Stage {sidx+1}: {len(poly)} query points along {b_km-a_km:.0f} km...")
        els, ok = overpass(poly, sidx + 1)
        if not ok:
            failed_stages.append(sidx + 1)
        for e in els:
            cat = categorize(e.get("tags", {}))
            if not cat:
                continue
            eid = e["id"]
            if eid in all_pois:
                continue
            la2 = e.get("lat") or e.get("center", {}).get("lat")
            lo2 = e.get("lon") or e.get("center", {}).get("lon")
            if la2 is None:
                continue
            along, off = project_along(la2, lo2, lat, lon, cum)
            all_pois[eid] = {"cat": cat, "lat": la2, "lon": lo2,
                             "name": e["tags"].get("name", ""), "along": along, "off_km": off}
        stages.append({"n": sidx + 1, "track": track, "members": members,
                       "a_km": a_km, "b_km": b_km})
        time.sleep(3)

    pois = list(all_pois.values())
    print(f"\nTotal POIs: {len(pois)}  {dict(Counter(p['cat'] for p in pois))}")
    if failed_stages:
        print(f"WARNING: stages {failed_stages} failed — their region's gaps are "
              f"UNRELIABLE (missing data). Re-run to retry just those (others cached).")

    # resupply gaps along the whole route
    resupply_along = sorted(p["along"] for p in pois if p["cat"] in RESUPPLY)
    gaps = find_gaps(resupply_along, total, RESUPPLY_GAP_KM)
    water_along = sorted(p["along"] for p in pois if p["cat"] == "water")
    water_gaps = find_gaps(water_along, total, WATER_GAP_KM)

    # assign POIs to stages by along-km, render enhanced maps
    for st in stages:
        st["pois"] = [p for p in pois if st["a_km"] - 0.5 <= p["along"] <= st["b_km"] + 0.5]
        write_stage_map(st)

    logistics = {
        "buffer_m": BUFFER_M, "total_pois": len(pois),
        "counts": dict(Counter(p["cat"] for p in pois)),
        "resupply_gap_km_threshold": RESUPPLY_GAP_KM,
        "resupply_gaps": gaps, "water_gaps": water_gaps,
        "stage_counts": {st["n"]: dict(Counter(p["cat"] for p in st["pois"])) for st in stages},
    }
    (OUT / "logistics.json").write_text(json.dumps(logistics, ensure_ascii=False, indent=2))
    append_readme(stages, logistics, stops, total)

    print("\nResupply gaps (>%.0f km with no conbini/food/lodging):" % RESUPPLY_GAP_KM)
    for g in gaps:
        near = nearest_onsens(g, stops)
        print(f"  {g['from_km']:.0f}–{g['to_km']:.0f} km ({g['len_km']:.0f} km gap)  near {near}")
    print(f"\nWrote logistics.json + enhanced stage maps; appended README.")


def find_gaps(along_sorted, total, thr):
    pts = [0.0] + list(along_sorted) + [total]
    gaps = []
    for i in range(1, len(pts)):
        d = pts[i] - pts[i - 1]
        if d > thr:
            gaps.append({"from_km": round(pts[i - 1], 1), "to_km": round(pts[i], 1),
                         "len_km": round(d, 1)})
    return gaps


def nearest_onsens(gap, stops):
    mid = (gap["from_km"] + gap["to_km"]) / 2
    near = min(stops, key=lambda s: abs(s["along_km"] - mid))
    return f"#{near['order']} {near['area']}"


def write_stage_map(st):
    n = st["n"]
    onsen_pts = [{"o": m["order"], "id": m["id"], "name": f'{m["area"]}：{m["name"]}',
                  "pref": m["prefecture"], "lat": m["lat"], "lon": m["lon"],
                  "color": PREF_COLORS.get(m["prefecture"], "#888")} for m in st["members"]]
    by_cat = defaultdict(list)
    for p in st["pois"]:
        by_cat[p["cat"]].append({"lat": p["lat"], "lon": p["lon"],
                                 "name": p["name"], "off": round(p["off_km"], 2)})
    cat_js = {c: by_cat.get(c, []) for c in CAT_STYLE}
    style_js = {c: {"e": CAT_STYLE[c][0], "color": CAT_STYLE[c][1], "on": CAT_STYLE[c][2]}
                for c in CAT_STYLE}
    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Stage {n} + logistics</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body{{margin:0;height:100%;font-family:system-ui,sans-serif}}#map{{height:100%}}
.num{{color:#fff;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;
justify-content:center;font-size:11px;font-weight:700;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)}}
.poi{{font-size:15px;text-align:center;line-height:18px;filter:drop-shadow(0 1px 1px rgba(0,0,0,.4))}}</style>
</head><body><div id="map"></div><script>
const ONS={json.dumps(onsen_pts, ensure_ascii=False)};
const LINE={json.dumps(st['track'])};
const CATS={json.dumps(cat_js, ensure_ascii=False)};
const STY={json.dumps(style_js, ensure_ascii=False)};
const map=L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:18,attribution:'&copy; OpenStreetMap'}}).addTo(map);
L.polyline(LINE,{{color:'#1565c0',weight:3,opacity:.8}}).addTo(map);
ONS.forEach(p=>{{const icon=L.divIcon({{className:'',html:`<div class="num" style="background:${{p.color}}">${{p.o}}</div>`,iconSize:[22,22],iconAnchor:[11,11]}});
L.marker([p.lat,p.lon],{{icon}}).addTo(map).bindPopup(`<b>${{p.o}}. ${{p.name}}</b><br>${{p.pref}} · #${{p.id}}`);}});
const overlays={{}};
for(const c in CATS){{const g=L.layerGroup();CATS[c].forEach(p=>{{
  const icon=L.divIcon({{className:'',html:`<div class="poi">${{STY[c].e}}</div>`,iconSize:[18,18],iconAnchor:[9,9]}});
  L.marker([p.lat,p.lon],{{icon}}).addTo(g).bindPopup(`${{STY[c].e}} ${{p.name||c}}<br>${{p.off}}km off route`);}});
  if(STY[c].on)g.addTo(map);
  overlays[`${{STY[c].e}} ${{c}} (${{CATS[c].length}})`]=g;}}
L.control.layers(null,overlays,{{collapsed:false}}).addTo(map);
map.fitBounds(LINE);
</script></body></html>"""
    (OUT / f"stage_{n:02d}_map.html").write_text(html)


def append_readme(stages, logistics, stops, total):
    p = OUT / "README.md"
    txt = p.read_text()
    if "## Logistics" in txt:
        txt = txt.split("## Logistics")[0].rstrip() + "\n\n"
    lines = [txt, "## Logistics (OpenStreetMap, within 1 km of the line)", "",
             f"Total services found: **{logistics['total_pois']}** — "
             + " · ".join(f"{CAT_STYLE[c][0]}{c} {n}" for c, n in logistics["counts"].items()), "",
             f"**No-resupply gaps** (>{RESUPPLY_GAP_KM:.0f} km with no conbini/food/lodging — carry supplies):"]
    if logistics["resupply_gaps"]:
        for g in logistics["resupply_gaps"]:
            lines.append(f"- {g['from_km']:.0f}–{g['to_km']:.0f} km ({g['len_km']:.0f} km) — "
                         f"near {nearest_onsens(g, stops)}")
    else:
        lines.append("- none — resupply available at least every "
                     f"{RESUPPLY_GAP_KM:.0f} km 🎉")
    lines += ["", "Per-stage service counts:", "",
              "| Stage | 🏪 | 🛒 | 🍴 | 💧 | 🛏 | ⛺ | 🚉 |", "|---|---|---|---|---|---|---|---|"]
    for st in stages:
        c = logistics["stage_counts"][st["n"]]
        lines.append(f"| {st['n']} | {c.get('conbini',0)} | {c.get('supermarket',0)} | "
                     f"{c.get('food',0)} | {c.get('water',0)} | {c.get('lodging',0)} | "
                     f"{c.get('campsite',0)} | {c.get('station',0)} |")
    lines.append("\n_Each `stage_NN_map.html` now has toggleable POI layers (top-right)._")
    p.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
