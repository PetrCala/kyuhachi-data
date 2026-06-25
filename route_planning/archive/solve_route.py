#!/usr/bin/env python3
"""Deliverable 3: re-solve the foot route with the all-7-prefecture hard
constraint, as a FIXED-ENDPOINT OPEN PATH (no loop, no return leg):

    START = Cape 長崎鼻 (Nagasakibana), southern Kagoshima   [landmark, not counted]
    END   = #41 浜脇温泉 茶房たかさきの湯, Beppu, Oita          [counted onsen, fixed last]

Both endpoints are GIVEN and fixed. Solver: nearest-neighbor seed from START
(END forced last) + open-path 2-opt that never moves the two endpoints.
Nagasaki guaranteed via 波佐見 Hasami (#148), adjacent to the Saga cluster.

Great-circle is a lower bound; real foot distance ~ROAD_FACTOR x longer.

Outputs:
  route_full.json          all foot-eligible onsens, ordered
  route_first_pass.json    trimmed to provision target N, ordered (the headline)
  route_map.html           self-contained Leaflet map (CDN) of the trimmed route
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from onsen_model import load_onsens, haversine_km

HERE = Path(__file__).resolve().parent

START = ("長崎鼻 (Cape Nagasakibana)", 31.1556, 130.5944)  # fixed start, not a counted onsen
END_ID = 41  # 浜脇温泉 茶房たかさきの湯, Beppu — fixed terminus (counted)
ROAD_FACTOR = 1.3
TARGET_N = 108  # provision target from provision.py
ALL7 = ["福岡", "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島"]
PROTECT_IDS = {148, 12, END_ID}  # Hasami (Nagasaki stamp), 嬉野 (its gateway), the terminus

# Optional far spurs (toggle for iteration).
INCLUDE_SHIMABARA = True    # #21,#175,#24,#165  (+~3 days, 4 beads)
INCLUDE_HIRADO = False      # #19  (far NW, ~1.5 days, 1 bead)
SHIMABARA_IDS = {21, 175, 24, 165}
HIRADO_IDS = {19}

PREF_COLORS = {
    "福岡県": "#e6194B", "佐賀県": "#f58231", "長崎県": "#ffe119",
    "熊本県": "#3cb44b", "大分県": "#4363d8", "宮崎県": "#911eb4",
    "鹿児島県": "#f032e6",
}


def build_nodes():
    ons = load_onsens()
    keep = []
    for o in ons:
        if o.id in HIRADO_IDS and not INCLUDE_HIRADO:
            continue
        if o.id in SHIMABARA_IDS and not INCLUDE_SHIMABARA:
            continue
        keep.append(o)
    return keep


def dist(a, b):
    return haversine_km(a[1], a[2], b[1], b[2])


def pt(o):
    return (f"#{o.id}", o.lat, o.lon)


def two_opt_open(points, tour, max_passes=80):
    """Open-path 2-opt; endpoints tour[0] and tour[-1] never move."""
    n = len(tour)
    improved = True
    passes = 0
    while improved and passes < max_passes:
        improved = False
        passes += 1
        for i in range(1, n - 2):
            a = points[tour[i - 1]]
            b = points[tour[i]]
            d_ab = dist(a, b)
            for k in range(i + 1, n - 1):
                c = points[tour[k]]
                d = points[tour[k + 1]]
                if dist(a, c) + dist(b, d) + 1e-9 < d_ab + dist(c, d):
                    tour[i:k + 1] = reversed(tour[i:k + 1])
                    b = points[tour[i]]
                    d_ab = dist(a, b)
                    improved = True
    return tour


def solve_open(onsens):
    """Order onsens between fixed START and fixed END(#41). Returns ordered list."""
    end = next(o for o in onsens if o.id == END_ID)
    middle = [o for o in onsens if o.id != END_ID]
    # index 0 = START anchor; 1..m = middle onsens; m+1 = END
    points = [START] + [pt(o) for o in middle] + [pt(end)]
    end_idx = len(points) - 1
    # nearest-neighbor from START over middle only, then append END
    unvisited = set(range(1, len(points) - 1))
    tour = [0]
    cur = 0
    while unvisited:
        nxt = min(unvisited, key=lambda j: dist(points[cur], points[j]))
        tour.append(nxt)
        unvisited.discard(nxt)
        cur = nxt
    tour.append(end_idx)
    tour = two_opt_open(points, tour)
    # map back to onsen objects in order (drop START at index 0)
    obj = [None] + middle + [end]
    return [obj[i] for i in tour[1:]]


def path_len(ordered):
    seq = [START] + [pt(o) for o in ordered]
    return sum(dist(seq[i], seq[i + 1]) for i in range(len(seq) - 1))


def trim_to_target(onsens, target):
    """Drop highest-detour onsens to `target`, protecting >=1/prefecture + PROTECT_IDS."""
    ordered = solve_open(onsens)
    seq = [START] + [pt(o) for o in ordered]
    # marginal detour cost of each ordered onsen (END has no successor cost)
    mc = {}
    for i, o in enumerate(ordered):
        prev = seq[i]
        cur = seq[i + 1]
        nxt = seq[i + 2] if i + 2 < len(seq) else None
        if nxt is None:
            mc[o.id] = 0.0  # END terminus
        else:
            mc[o.id] = dist(prev, cur) + dist(cur, nxt) - dist(prev, nxt)
    keep = {o.id for o in onsens}
    pref_count = Counter(o.pref_short for o in onsens)
    by_cost = sorted(onsens, key=lambda o: -mc.get(o.id, 0.0))
    n_drop = max(0, len(onsens) - target)
    for o in by_cost:
        if n_drop <= 0:
            break
        if o.id in PROTECT_IDS:
            continue
        if pref_count[o.pref_short] <= 1:
            continue
        keep.discard(o.id)
        pref_count[o.pref_short] -= 1
        n_drop -= 1
    return [o for o in onsens if o.id in keep]


def build_result(onsens, label):
    ordered = solve_open(onsens)
    seq = [START] + [pt(o) for o in ordered]
    stops, cum = [], 0.0
    for i, o in enumerate(ordered):
        leg = dist(seq[i], seq[i + 1])
        cum += leg
        stops.append({
            "order": i + 1, "id": o.id, "area": o.area, "name": o.name,
            "prefecture": o.prefecture, "pref_short": o.pref_short,
            "lat": o.lat, "lon": o.lon,
            "leg_km_gc": round(leg, 2), "cum_km_gc": round(cum, 1),
            "open_min": o.open_min, "last_min": o.effective_last_min,
            "closed_weekdays": sorted(o.closed_weekdays),
            "never_closes": o.never_closes, "irregular": o.irregular,
        })
    pc = Counter(s["pref_short"] for s in stops)
    return {
        "label": label, "shape": "open path (fixed endpoints)",
        "start": START[0], "end": f"#{END_ID} {ordered[-1].area}：{ordered[-1].name}",
        "include_shimabara": INCLUDE_SHIMABARA, "include_hirado": INCLUDE_HIRADO,
        "n_stops": len(stops), "road_factor": ROAD_FACTOR,
        "total_km_greatcircle": round(cum, 1),
        "total_km_road_est": round(cum * ROAD_FACTOR, 1),
        "prefecture_coverage": dict(pc),
        "all7_covered": all(p in pc for p in ALL7),
        "stops": stops,
    }


def main():
    ons = build_nodes()
    full = build_result(ons, "full opportunity set")
    (HERE / "route_full.json").write_text(json.dumps(full, ensure_ascii=False, indent=2))

    kept = trim_to_target(ons, TARGET_N)
    trimmed = build_result(kept, f"trimmed to provision target N={TARGET_N}")
    (HERE / "route_first_pass.json").write_text(json.dumps(trimmed, ensure_ascii=False, indent=2))

    for tag, r in [("FULL", full), ("TRIMMED", trimmed)]:
        print(f"--- {tag}: {r['n_stops']} stops | end = {r['end']} ---")
        print(f"  GC open-path {r['total_km_greatcircle']} km | road-est x{ROAD_FACTOR} {r['total_km_road_est']} km")
        print(f"  all7={r['all7_covered']}  coverage={r['prefecture_coverage']}")
    kept_ids = {o.id for o in kept}
    dropped = [o for o in ons if o.id not in kept_ids]
    print(f"\nDropped {len(dropped)} onsens (highest detour cost), by prefecture:")
    bypref = Counter(o.pref_short for o in dropped)
    print(f"  {dict(bypref)}")

    write_map(trimmed)
    est_days = trimmed["total_km_road_est"] / 34.0
    print(f"\nTrimmed route ~{trimmed['total_km_road_est']} km road-est = ~{est_days:.0f} walking-days @34km/day")
    print(f"Wrote route_full.json, route_first_pass.json (N={TARGET_N}), route_map.html")


def write_map(result):
    stops = result["stops"]
    pts = [{
        "o": s["order"], "id": s["id"], "name": f'{s["area"]}：{s["name"]}',
        "pref": s["prefecture"], "lat": s["lat"], "lon": s["lon"],
        "color": PREF_COLORS.get(s["prefecture"], "#888"), "cum": s["cum_km_gc"],
    } for s in stops]
    start = {"name": START[0], "lat": START[1], "lon": START[2]}
    line = [[START[1], START[2]]] + [[s["lat"], s["lon"]] for s in stops]
    legend_rows = "".join(
        f'<div class="legend-row"><span class="swatch" style="background:{c}"></span>{p}'
        f' ({result["prefecture_coverage"].get(p.replace("県",""),0)})</div>'
        for p, c in PREF_COLORS.items()
    )
    html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>九州八十八湯 — 徒歩ルート ({result['n_stops']}湯)</title>
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
 .popup-name{{font-weight:700;font-size:14px}}
 .popup-meta{{font-size:12px;margin-top:3px;color:#444}}
</style></head><body>
<div id="map"></div>
<script>
const PTS = {json.dumps(pts, ensure_ascii=False)};
const START = {json.dumps(start, ensure_ascii=False)};
const LINE = {json.dumps(line)};
const map = L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
  {{maxZoom:18, attribution:'&copy; OpenStreetMap'}}).addTo(map);
L.polyline(LINE, {{color:'#1565c0', weight:2.5, opacity:.7}}).addTo(map);
// start marker (green square)
L.marker([START.lat,START.lon],{{icon:L.divIcon({{className:'',html:'<div class="term" style="background:#2e7d32"></div>',iconSize:[16,16],iconAnchor:[8,8]}})}})
 .addTo(map).bindPopup('<b>START</b><br>'+START.name);
PTS.forEach((p,i) => {{
  const isEnd = (i===PTS.length-1);
  const icon = L.divIcon({{className:'',
    html: isEnd ? '<div class="term" style="background:#000"></div>'
                : `<div class="num" style="background:${{p.color}}">${{p.o}}</div>`,
    iconSize: isEnd?[16,16]:[22,22], iconAnchor: isEnd?[8,8]:[11,11]}});
  L.marker([p.lat,p.lon],{{icon}}).addTo(map)
    .bindPopup(`<div class="popup-name">${{isEnd?'END · ':''}}${{p.o}}. ${{p.name}}</div>`+
      `<div class="popup-meta">${{p.pref}} · #${{p.id}} · 累積 ${{p.cum}} km</div>`);
}});
const legend = L.control({{position:'topright'}});
legend.onAdd = function() {{
  const d = L.DomUtil.create('div','legend');
  d.innerHTML = `<div class="title">徒歩ルート {result['n_stops']}湯</div>`+
    `<div style="font-size:11px;color:#666;margin-bottom:6px">長崎鼻 → 別府(浜脇)<br>GC {result['total_km_greatcircle']} km · 道路推定 {result['total_km_road_est']} km</div>`+
    `{legend_rows}`;
  return d;
}};
legend.addTo(map);
map.fitBounds(LINE);
</script></body></html>"""
    (HERE / "route_map.html").write_text(html)


if __name__ == "__main__":
    main()
