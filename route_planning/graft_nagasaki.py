#!/usr/bin/env python3
"""Graft a Saga->Nagasaki out-and-back spur onto the hand-drawn line.

Spur (in visit order): 武雄 #11 -> 嬉野 #12 (western Saga) -> 波佐見 #148 (Hasami,
the cheap Nagasaki stamp) -> return. No Shimabara/Unzen. Attaches at the line's
nearest point to 武雄; spur legs routed on real OSRM foot roads (ferry-rejected).

Outputs: kyuhachi_nagasaki.gpx, handdrawn_nagasaki_analysis.json,
itinerary_nagasaki.md, route_nagasaki_map.html
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

import geo
import osrm
import simulate
from config import ALL7, HANDDRAWN_GPX, PASS_KM
from geo import cumulative, load_track, nearest_on_track
from onsen_model import load_onsens

HERE = Path(__file__).resolve().parent
GPX_IN = HANDDRAWN_GPX
SPUR_IDS = [11, 12, 148]          # 武雄 -> 嬉野 -> 波佐見(Hasami), out then back
PREF_COLORS = {
    "福岡県": "#e6194B", "佐賀県": "#f58231", "長崎県": "#ffe119",
    "熊本県": "#3cb44b", "大分県": "#4363d8", "宮崎県": "#911eb4", "鹿児島県": "#f032e6",
}


def main():
    lat, lon, cum = load_track(GPX_IN)
    ons = {o.id: o for o in load_onsens()}
    spur = [ons[i] for i in SPUR_IDS]

    # attach at the line vertex nearest 武雄 (the spur entry)
    R = 6371.0
    la1, lo1 = np.radians(spur[0].lat), np.radians(spur[0].lon)
    a = (np.sin((np.radians(lat) - la1) / 2) ** 2
         + np.cos(la1) * np.cos(np.radians(lat)) * np.sin((np.radians(lon) - lo1) / 2) ** 2)
    attach = int(np.argmin(R * 2 * np.arcsin(np.sqrt(a))))
    atlat, atlon = float(lat[attach]), float(lon[attach])
    print(f"Attach point: track[{attach}] ({atlat:.4f},{atlon:.4f}), "
          f"along {cum[attach]:.0f} km — nearest to 武雄")

    # OSRM spur legs: attach -> 武雄 -> 嬉野 -> Hasami -> attach
    pts = [(atlon, atlat)] + [(o.lon, o.lat) for o in spur] + [(atlon, atlat)]
    labels = ["attach", "武雄", "嬉野", "波佐見", "attach(return)"]
    spur_geom, spur_km = [], 0.0
    for i in range(len(pts) - 1):
        g, dist = osrm.geometry(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        if g is None:
            print(f"  WARNING no foot route {labels[i]}->{labels[i+1]}, using straight")
            g = [[pts[i][1], pts[i][0]], [pts[i + 1][1], pts[i + 1][0]]]
            dist = 0.0
        spur_geom.append(g)
        spur_km += dist
        print(f"  leg {labels[i]:>14} -> {labels[i+1]:<14} {dist:6.1f} km")
    print(f"Spur total (out-and-back): {spur_km:.1f} km for {len(spur)} onsens")

    # splice spur geometry into the track at the attach point
    spur_pts = [p for leg in spur_geom for p in leg]
    pre = list(zip(lat[:attach + 1].tolist(), lon[:attach + 1].tolist()))
    post = list(zip(lat[attach + 1:].tolist(), lon[attach + 1:].tolist()))
    combined = pre + spur_pts + post
    clat = np.array([p[0] for p in combined])
    clon = np.array([p[1] for p in combined])
    ccum = cumulative(clat, clon)
    print(f"Combined line: {ccum[-1]:.0f} km ({len(combined)} pts) "
          f"= 1039 + {ccum[-1]-1039:.0f} km spur")

    # re-snap ALL onsens onto the combined line
    rows = []
    for o in ons.values():
        dkm, along = nearest_on_track(o.lat, o.lon, clat, clon, ccum)
        rows.append({"o": o, "dist_km": dkm, "along_km": along})
    passed = sorted((r for r in rows if r["dist_km"] <= PASS_KM), key=lambda r: r["along_km"])
    pc = Counter(r["o"].pref_short for r in passed)

    osrm_ids = {s["id"] for s in json.loads((HERE / "route_osrm.json").read_text())["stops"]} \
        if (HERE / "route_osrm.json").exists() else set()
    stops, prev = [], 0.0
    for i, r in enumerate(passed):
        o = r["o"]
        leg = max(0.0, r["along_km"] - prev)
        prev = r["along_km"]
        stops.append({
            "order": i + 1, "id": o.id, "area": o.area, "name": o.name,
            "prefecture": o.prefecture, "pref_short": o.pref_short, "lat": o.lat, "lon": o.lon,
            "dist_to_line_km": round(r["dist_km"], 2), "along_km": round(r["along_km"], 1),
            "leg_km_gc": round(leg, 2), "cum_km_gc": round(r["along_km"], 1),
            "open_min": o.open_min, "last_min": o.effective_last_min,
            "closed_weekdays": sorted(o.closed_weekdays),
            "never_closes": o.never_closes, "irregular": o.irregular,
            "in_osrm_108": o.id in osrm_ids, "is_spur": o.id in SPUR_IDS,
        })
    result = {
        "source": "Kyuhachi-3 + Nagasaki spur", "line_km": round(float(ccum[-1]), 1),
        "spur_km": round(spur_km, 1), "spur_ids": SPUR_IDS, "passed": len(passed),
        "prefecture_coverage": dict(pc), "all7": all(p in pc for p in ALL7),
        "ge_88": len(passed) >= 88, "stops": stops,
    }
    (HERE / "handdrawn_nagasaki_analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    write_gpx(combined, stops)
    write_map(combined, stops, result)

    summ, ev = simulate.simulate(HERE / "handdrawn_nagasaki_analysis.json",
                                 policy="patient", road_factor=1.0)
    simulate.write_itinerary(summ, ev, HERE / "itinerary_nagasaki.md")

    print("\n" + "=" * 60)
    print(f"NOW: {len(passed)} onsens, coverage {dict(pc)}")
    print(f"all 7 prefectures: {result['all7']}")
    print(f"schedule: finish {summ['finish']}, {summ['calendar_days_used']} days, "
          f"{summ['slack_days_to_deadline']} slack, visited {summ['visited']}")
    print("Wrote kyuhachi_nagasaki.gpx, handdrawn_nagasaki_analysis.json, "
          "itinerary_nagasaki.md, route_nagasaki_map.html")


def write_gpx(combined, stops):
    geo.write_gpx(HERE / "kyuhachi_nagasaki.gpx", combined, stops,
                  meta_name="Kyuhachi hand-drawn + Nagasaki spur", trk_name="Kyuhachi+Nagasaki",
                  tag_fn=lambda s: " [SPUR]" if s.get("is_spur") else "")


def write_map(combined, stops, result):
    pts = [{"o": s["order"], "id": s["id"], "name": f'{s["area"]}：{s["name"]}',
            "pref": s["prefecture"], "lat": s["lat"], "lon": s["lon"],
            "color": PREF_COLORS.get(s["prefecture"], "#888"), "spur": s.get("is_spur", False)}
           for s in stops]
    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Kyuhachi + Nagasaki spur ({result['passed']}湯)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body{{margin:0;height:100%;font-family:system-ui,sans-serif}}#map{{height:100%}}
.num{{color:#fff;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;
justify-content:center;font-size:11px;font-weight:700;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)}}
.spur{{box-shadow:0 0 0 3px #ffe119,0 1px 3px rgba(0,0,0,.5)}}</style>
</head><body><div id="map"></div><script>
const PTS={json.dumps(pts, ensure_ascii=False)};const LINE={json.dumps(combined)};
const map=L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:18,attribution:'&copy; OpenStreetMap'}}).addTo(map);
L.polyline(LINE,{{color:'#1565c0',weight:3,opacity:.75}}).addTo(map);
PTS.forEach(p=>{{const icon=L.divIcon({{className:'',html:`<div class="num ${{p.spur?'spur':''}}" style="background:${{p.color}}">${{p.o}}</div>`,iconSize:[22,22],iconAnchor:[11,11]}});
L.marker([p.lat,p.lon],{{icon}}).addTo(map).bindPopup(`<b>${{p.o}}. ${{p.name}}</b><br>${{p.pref}} · #${{p.id}}${{p.spur?' · NAGASAKI SPUR':''}}`);}});
map.fitBounds(LINE);
</script></body></html>"""
    (HERE / "route_nagasaki_map.html").write_text(html)


if __name__ == "__main__":
    main()
