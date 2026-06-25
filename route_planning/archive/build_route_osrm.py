#!/usr/bin/env python3
"""Re-solve the foot route on REAL OSRM walking distances (no great-circle).

START = Cape 長崎鼻 (anchor, not counted)  ->  END = #41 浜脇 茶房たかさきの湯 (fixed).
Exclusions: islands + Amakusa + Sakurajima/east-Kagoshima-bay + east-Miyazaki.
Shimabara/Unzen kept. All-7 prefectures enforced (Hasami #148 mandatory). Target 108.

Pipeline: load -> OSRM matrix -> NN+2-opt+trim -> OSRM geometries -> map + GPX + JSON.
Outputs: route_osrm.json, route_osrm_map.html, kyuhachi_osrm.gpx
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from onsen_model import load_onsens  # already drops offshore islands {130,219,176,237}
import osrm

HERE = Path(__file__).resolve().parent
START = ("長崎鼻 (Cape Nagasakibana)", 31.1556, 130.5944)
END_ID = 41
TARGET_N = 108
ALL7 = ["福岡", "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島"]

# Additional exclusions on top of the offshore islands.
AMAKUSA = {90}
SAKURAJIMA_EASTBAY = {116, 140, 217}      # 古里(桜島), 海潟(垂水), テイエム牧場(垂水)
EAST_MIYAZAKI = {95, 96, 100, 189, 205, 224, 231, 246}
EXCLUDE = AMAKUSA | SAKURAJIMA_EASTBAY | EAST_MIYAZAKI

# Shimabara/Unzen peninsula: foot-reachable ONLY via the Isahaya land gateway
# (the Kumamoto-side approach needs a ferry). We route these in/out via the gate.
SHIMABARA_IDS = {21, 24, 165, 175}
GATEWAY = ("諫早 (Isahaya gate)", 32.840, 130.040)  # land base of the peninsula

PROTECT_IDS = {148, 12, END_ID} | SHIMABARA_IDS   # keep Nagasaki + 嬉野 + terminus + Shimabara

PREF_COLORS = {
    "福岡県": "#e6194B", "佐賀県": "#f58231", "長崎県": "#ffe119",
    "熊本県": "#3cb44b", "大分県": "#4363d8", "宮崎県": "#911eb4", "鹿児島県": "#f032e6",
}


def nn(M, allowed, start, end):
    unv = set(allowed) - {start, end}
    tour, cur = [start], start
    while unv:
        nxt = min(unv, key=lambda j: M[cur][j])
        tour.append(nxt)
        unv.discard(nxt)
        cur = nxt
    tour.append(end)
    return tour


def two_opt(M, tour, max_passes=80):
    n = len(tour)
    improved, p = True, 0
    while improved and p < max_passes:
        improved, p = False, p + 1
        for i in range(1, n - 2):
            a, b = tour[i - 1], tour[i]
            dab = M[a][b]
            for k in range(i + 1, n - 1):
                c, d = tour[k], tour[k + 1]
                if M[a][c] + M[b][d] + 1e-9 < dab + M[c][d]:
                    tour[i:k + 1] = reversed(tour[i:k + 1])
                    b = tour[i]
                    dab = M[a][b]
                    improved = True
    return tour


def main():
    ons = [o for o in load_onsens() if o.id not in EXCLUDE]
    print(f"Eligible after exclusions: {len(ons)} onsens")
    by_pref = Counter(o.pref_short for o in ons)
    print(f"  by prefecture: {dict(by_pref)}")

    # nodes: 0 = START anchor, 1..n = onsens, last = Isahaya gateway (not visited)
    nodes_onsen = {i + 1: o for i, o in enumerate(ons)}
    coords = ([(START[2], START[1])] + [(o.lon, o.lat) for o in ons]
              + [(GATEWAY[2], GATEWAY[1])])
    end_node = next(i for i, o in nodes_onsen.items() if o.id == END_ID)
    gate_node = len(coords) - 1
    n_nodes = len(coords)

    print("Building OSRM foot distance matrix...")
    M = osrm.build_matrix(coords, cache_name="osrm_matrix_v2.json")

    # Ferry fix. OSRM foot silently ferries across the Ariake Sea, so every
    # Kumamoto/Fukuoka <-> Nagasaki matrix entry is an invalid (ferry) shortcut.
    # The whole Nagasaki pocket connects to the mainland by LAND only through the
    # Saga isthmus. So:
    #   (1) forbid any Nagasaki onsen from attaching outside the Nagasaki/Saga
    #       pocket (BIG) -> the route can only enter Nagasaki from Saga, by land;
    #   (2) within the pocket, route the Shimabara peninsula in/out via the
    #       Isahaya land gate (Shimabara<->Nagasaki-city would otherwise ferry).
    BIG = 1e6
    nagasaki_nodes = {nd for nd, o in nodes_onsen.items() if o.pref_short == "長崎"}
    saga_nodes = {nd for nd, o in nodes_onsen.items() if o.pref_short == "佐賀"}
    pocket = nagasaki_nodes | saga_nodes
    shima_nodes = {nd for nd, o in nodes_onsen.items() if o.id in SHIMABARA_IDS}

    for n in nagasaki_nodes:                      # (1) seal the pocket
        for x in range(n_nodes):
            if x == n or x == gate_node or x in pocket:
                continue
            M[x][n] = M[n][x] = BIG
    for s in shima_nodes:                         # (2) Shimabara via Isahaya
        for x in range(n_nodes):
            if x == s or x == gate_node or x in shima_nodes:
                continue
            if x in pocket:
                M[x][s] = M[s][x] = M[x][gate_node] + M[gate_node][s]

    # visitable nodes exclude the gateway
    allowed = set(nodes_onsen) | {0}
    full = two_opt(M, nn(M, allowed, 0, end_node))

    # marginal detour per onsen-node in `full`
    pos = {node: i for i, node in enumerate(full)}
    mc = {}
    for i in range(1, len(full) - 1):
        a, c, b = full[i - 1], full[i], full[i + 1]
        mc[full[i]] = M[a][c] + M[c][b] - M[a][b]

    # trim to target: drop highest-detour, protect >=1/pref + PROTECT_IDS
    keep = set(full)
    pref_count = Counter(nodes_onsen[nd].pref_short for nd in full if nd != 0)
    n_drop = max(0, (len(full) - 1) - TARGET_N)  # -1 for START
    for nd in sorted((x for x in full if x not in (0, end_node)), key=lambda x: -mc.get(x, 0)):
        if n_drop <= 0:
            break
        o = nodes_onsen[nd]
        if o.id in PROTECT_IDS or pref_count[o.pref_short] <= 1:
            continue
        keep.discard(nd)
        pref_count[o.pref_short] -= 1
        n_drop -= 1

    # final order over kept nodes
    final = two_opt(M, nn(M, keep, 0, end_node))
    final_onsen_nodes = [nd for nd in final if nd != 0]

    # leg distances (real OSRM km) and stops
    stops, cum = [], 0.0
    prev = 0
    for nd in final_onsen_nodes:
        o = nodes_onsen[nd]
        leg = M[prev][nd]
        cum += leg
        stops.append({
            "order": len(stops) + 1, "id": o.id, "area": o.area, "name": o.name,
            "prefecture": o.prefecture, "pref_short": o.pref_short,
            "lat": o.lat, "lon": o.lon,
            "leg_km_gc": round(leg, 2),       # real OSRM km (field name kept for simulate.py)
            "cum_km_gc": round(cum, 1),
            "open_min": o.open_min, "last_min": o.effective_last_min,
            "closed_weekdays": sorted(o.closed_weekdays),
            "never_closes": o.never_closes, "irregular": o.irregular,
        })
        prev = nd
    pc = Counter(s["pref_short"] for s in stops)
    result = {
        "label": "OSRM real-distance route", "shape": "open path (fixed endpoints)",
        "distance_source": "osrm_foot", "start": START[0],
        "end": f"#{END_ID} {stops[-1]['area']}：{stops[-1]['name']}",
        "n_stops": len(stops), "total_km_osrm": round(cum, 1),
        "prefecture_coverage": dict(pc),
        "all7_covered": all(p in pc for p in ALL7),
        "excluded_ids": sorted(EXCLUDE), "stops": stops,
    }
    (HERE / "route_osrm.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nFinal OSRM route: {len(stops)} stops, {cum:.1f} km real walking")
    print(f"  all7={result['all7_covered']}  coverage={dict(pc)}")
    print(f"  end = {result['end']}")

    # fetch geometries for the final legs (START -> s1 -> ... -> END)
    print("\nFetching OSRM route geometries for final legs...")
    pts = [(START[2], START[1])] + [(s["lon"], s["lat"]) for s in stops]
    is_shima = [False] + [s["id"] in SHIMABARA_IDS for s in stops]
    gate_via = (GATEWAY[2], GATEWAY[1])
    legs = []
    for i in range(len(pts) - 1):
        # route via Isahaya when crossing the mainland<->peninsula boundary
        via = gate_via if (is_shima[i] != is_shima[i + 1]) else None
        legs.append((pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], via))
    geoms = osrm.fetch_geometries(legs, cache_name="osrm_geoms_v3.json")
    drawn_km = sum(g[1] for g in geoms if g[1])
    n_ferry = sum(1 for g in geoms if g[0] is None)
    print(f"  drawn distance {drawn_km:.1f} km; legs w/o route (ferry/none): {n_ferry}")

    write_map(result, geoms)
    write_gpx(result, geoms)
    print("Wrote route_osrm.json, route_osrm_map.html, kyuhachi_osrm.gpx")
    return result, geoms


def write_map(result, geoms):
    stops = result["stops"]
    line = []
    for g, _ in geoms:
        if g:
            line.extend(g)
    if not line:  # fallback straight
        line = [[START[1], START[2]]] + [[s["lat"], s["lon"]] for s in stops]
    pts = [{"o": s["order"], "id": s["id"], "name": f'{s["area"]}：{s["name"]}',
            "pref": s["prefecture"], "lat": s["lat"], "lon": s["lon"],
            "color": PREF_COLORS.get(s["prefecture"], "#888"), "cum": s["cum_km_gc"]}
           for s in stops]
    start = {"name": START[0], "lat": START[1], "lon": START[2]}
    legend_rows = "".join(
        f'<div class="legend-row"><span class="swatch" style="background:{c}"></span>{p}'
        f' ({result["prefecture_coverage"].get(p.replace("県",""),0)})</div>'
        for p, c in PREF_COLORS.items())
    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>九州八十八湯 — OSRM徒歩ルート ({result['n_stops']}湯)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 html,body{{margin:0;height:100%;font-family:-apple-system,system-ui,sans-serif}}
 #map{{height:100%;width:100%}}
 .legend{{background:rgba(255,255,255,.95);padding:10px 12px;border-radius:8px;
   box-shadow:0 1px 4px rgba(0,0,0,.3);font-size:13px;line-height:1.5;max-height:70vh;overflow:auto}}
 .legend .title{{font-weight:700;margin-bottom:4px}}
 .legend-row{{display:flex;align-items:center}}
 .swatch{{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:6px;border:1px solid rgba(0,0,0,.3)}}
 .num{{color:#fff;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;
   justify-content:center;font-size:11px;font-weight:700;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)}}
 .term{{width:16px;height:16px;border-radius:3px;border:3px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.5)}}
 .popup-name{{font-weight:700;font-size:14px}} .popup-meta{{font-size:12px;margin-top:3px;color:#444}}
</style></head><body><div id="map"></div><script>
const PTS={json.dumps(pts, ensure_ascii=False)};
const START={json.dumps(start, ensure_ascii=False)};
const LINE={json.dumps(line)};
const map=L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:18,attribution:'&copy; OpenStreetMap'}}).addTo(map);
L.polyline(LINE,{{color:'#1565c0',weight:3,opacity:.75}}).addTo(map);
L.marker([START.lat,START.lon],{{icon:L.divIcon({{className:'',html:'<div class="term" style="background:#2e7d32"></div>',iconSize:[16,16],iconAnchor:[8,8]}})}}).addTo(map).bindPopup('<b>START</b><br>'+START.name);
PTS.forEach((p,i)=>{{const isEnd=(i===PTS.length-1);
 const icon=L.divIcon({{className:'',html:isEnd?'<div class="term" style="background:#000"></div>':`<div class="num" style="background:${{p.color}}">${{p.o}}</div>`,iconSize:isEnd?[16,16]:[22,22],iconAnchor:isEnd?[8,8]:[11,11]}});
 L.marker([p.lat,p.lon],{{icon}}).addTo(map).bindPopup(`<div class="popup-name">${{isEnd?'END · ':''}}${{p.o}}. ${{p.name}}</div><div class="popup-meta">${{p.pref}} · #${{p.id}} · 累積 ${{p.cum}} km</div>`);}});
const legend=L.control({{position:'topright'}});
legend.onAdd=function(){{const d=L.DomUtil.create('div','legend');
 d.innerHTML=`<div class="title">OSRM徒歩 {result['n_stops']}湯</div><div style="font-size:11px;color:#666;margin-bottom:6px">長崎鼻 → 別府(浜脇)<br>実歩行 {result['total_km_osrm']} km</div>{legend_rows}`;return d;}};
legend.addTo(map); map.fitBounds(LINE);
</script></body></html>"""
    (HERE / "route_osrm_map.html").write_text(html)


def write_gpx(result, geoms):
    stops = result["stops"]
    trkpts = []
    for g, _ in geoms:
        if g:
            trkpts.extend(g)
    seg = "".join(f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}"></trkpt>' for lat, lon in trkpts)
    wpts = [f'<wpt lat="{START[1]:.6f}" lon="{START[2]:.6f}"><name>START 長崎鼻</name><sym>Flag, Green</sym></wpt>']
    for s in stops:
        nm = f'{s["order"]}. {s["area"]}：{s["name"]}'.replace("&", "&amp;").replace("<", "＜")
        wpts.append(f'<wpt lat="{s["lat"]:.6f}" lon="{s["lon"]:.6f}"><name>{nm}</name>'
                    f'<desc>{s["prefecture"]} #{s["id"]} cum {s["cum_km_gc"]}km</desc></wpt>')
    gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<gpx version="1.1" creator="kyuhachi-data/route_planning" '
           'xmlns="http://www.topografix.com/GPX/1/1">\n'
           '<metadata><name>Kyuhachi OSRM foot route</name>'
           f'<desc>{result["n_stops"]} onsens, {result["total_km_osrm"]} km, 長崎鼻→別府</desc></metadata>\n'
           + "\n".join(wpts) + "\n"
           '<trk><name>Kyuhachi route</name><trkseg>' + seg + '</trkseg></trk>\n</gpx>\n')
    (HERE / "kyuhachi_osrm.gpx").write_text(gpx)


if __name__ == "__main__":
    main()
