#!/usr/bin/env python3
"""Remap the Nagasaki section as a hand-specified LOOP (replaces the out-and-back).

Per user road-level guidance, replace the original line segment 久留米(#5)→古湯(#10)
with a loop routed on the practical roads:

  久留米 #5 ──(SW through the southern plain near the Ariake bay)──► 嬉野 #12
         ──► 波佐見 #148 ──► 武雄 #11
         ──(east on rte24/25 into the Saga basin, then rte44 north up the 嘉瀬川
            valley)──► 佐賀大和 #241 ──► 熊の川 #157 ──► 熊の川 #15 ──► 古湯 #10
         ──(original line continues as before)

Outputs: kyuhachi_nagasaki_loop.gpx, route_nagasaki_loop_map.html,
handdrawn_loop_analysis.json, itinerary_loop.md
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

import difficulty
import geo
import osrm
import simulate
from config import ALL7, HANDDRAWN_GPX, PASS_KM
from geo import cumulative, load_track, nearest_idx, nearest_on_track
from onsen_model import load_onsens

HERE = Path(__file__).resolve().parent
GPX_IN = HANDDRAWN_GPX
PREF_COLORS = {"福岡県": "#e6194B", "佐賀県": "#f58231", "長崎県": "#ffe119",
               "熊本県": "#3cb44b", "大分県": "#4363d8", "宮崎県": "#911eb4", "鹿児島県": "#f032e6"}

SPLICE_START_ID = 5     # 久留米あおき — loop entry (on the original line)
SPLICE_END_ID = 241     # 佐賀大和 — rejoin here; the ORIGINAL line continues
                        # 佐賀大和->熊の川->古湯 along 国道263 (the user's own routing)
# loop waypoint onsen ids in visit order (entry -> ... -> rejoin at 佐賀大和).
# 熊の川/古湯 stay on the ORIGINAL line (it already runs 国道263 by the river).
LOOP_IDS = [5, 12, 148, 11, 241]
# per-leg via chains to force the practical highways (len == len(LOOP_IDS)-1).
LEG_VIAS = [
    [(130.366, 33.206),   # 久留米->嬉野 : 国道444 -> 207 -> 県道41
     (130.149, 33.184),   #   大川 -> 白石 -> 鹿島 -> (嬉野)
     (130.099, 33.106)],
    None,                 # 嬉野->波佐見
    None,                 # 波佐見->武雄
    [(130.107, 33.288),   # 武雄->佐賀大和 : 県道25 -> 国道203(44) -> 県道42
     (130.200, 33.274)],  #   多久 -> 小城 (avoids the 笠頭山 mountain cut)
]
LOOP_ONSEN_IDS = {12, 148, 11, 241}  # for ring-highlight on map

# --- out-and-back spurs grafted onto the loop line ----------------------------
# Newly-added onsens that sit off the hand-drawn line. Each spur visits its ids
# out-and-back from the line's nearest vertex, routed on OSRM foot roads (ferry
# rejected). `buffer` spurs are OPTIONAL pickups (tagged, above the core 88) —
# kept for when a planned stop is closed/unreachable on the day, not core route.
SPURS = [
    {"ids": [257], "buffer": False},      # 湯の児温泉 福田共同浴場 — Minamata coast
    {"ids": [261], "buffer": True},       # 赤川温泉 赤川荘 — Kuju crux (optional)
    {"ids": [259, 258], "buffer": True},  # 生石 + 賀来 — Oita-city finish buffer
]
SPUR_ONSEN_IDS = {i for s in SPURS for i in s["ids"]}
# Existing onsens that aren't spur targets but sit ONLY on a buffer detour
# (reachable only if you walk that optional out-and-back) — tag them buffer too.
ASSOC_BUFFER_IDS = {66}  # 高崎山温泉 おさるの湯 — on the Oita-city buffer out-and-back
BUFFER_ONSEN_IDS = {i for s in SPURS if s["buffer"] for i in s["ids"]} | ASSOC_BUFFER_IDS


def graft_spurs(combined, ons):
    """Splice each SPUR as an out-and-back into the (loop) line `combined`
    (list of [lat, lon] / (lat, lon)). Attaches at the nearest line vertex to
    the spur's first onsen; legs routed on OSRM foot roads. Returns the line."""
    for spec in SPURS:
        spur = [ons[i] for i in spec["ids"]]
        clat = np.array([p[0] for p in combined])
        clon = np.array([p[1] for p in combined])
        R = 6371.0
        la1, lo1 = np.radians(spur[0].lat), np.radians(spur[0].lon)
        a = (np.sin((np.radians(clat) - la1) / 2) ** 2
             + np.cos(la1) * np.cos(np.radians(clat)) * np.sin((np.radians(clon) - lo1) / 2) ** 2)
        attach = int(np.argmin(R * 2 * np.arcsin(np.sqrt(a))))
        atlat, atlon = combined[attach][0], combined[attach][1]
        pts = [(atlon, atlat)] + [(o.lon, o.lat) for o in spur] + [(atlon, atlat)]
        geom, spur_km, ferry = [], 0.0, False
        for k in range(len(pts) - 1):
            g, dist = osrm.geometry(pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1])
            if g is None:
                ferry = True
                g = [[pts[k][1], pts[k][0]], [pts[k + 1][1], pts[k + 1][0]]]
                dist = 0.0
            geom.append(g)
            spur_km += dist
        spur_pts = [p for leg in geom for p in leg]
        combined = combined[:attach + 1] + spur_pts + combined[attach + 1:]
        kind = "buffer" if spec["buffer"] else "spur"
        names = ", ".join(f"{o.area}：{o.name}" for o in spur)
        warn = "  ⚠ FERRY/NO-ROUTE (straight fallback!)" if ferry else ""
        print(f"  grafted {kind:6} +{spur_km:5.1f} km @vtx {attach}: {names}{warn}")
    return combined


def main():
    lat, lon, cum = load_track(GPX_IN)
    ons = {o.id: o for o in load_onsens()}

    i_start = nearest_idx(ons[SPLICE_START_ID].lat, ons[SPLICE_START_ID].lon, lat, lon)
    i_end = nearest_idx(ons[SPLICE_END_ID].lat, ons[SPLICE_END_ID].lon, lat, lon)
    print(f"Splice: original[{i_start}] (久留米, along {cum[i_start]:.0f}) -> "
          f"[{i_end}] (古湯, along {cum[i_end]:.0f}); replacing {cum[i_end]-cum[i_start]:.0f} km")

    # build loop legs on OSRM foot roads, forcing highways via LEG_VIAS
    wp = [(ons[i].lon, ons[i].lat) for i in LOOP_IDS]
    loop_geom, loop_km = [], 0.0
    for k in range(len(wp) - 1):
        g, dist = osrm.geometry(wp[k][0], wp[k][1], wp[k + 1][0], wp[k + 1][1], via=LEG_VIAS[k])
        if g is None:
            print(f"  WARN no route {LOOP_IDS[k]}->{LOOP_IDS[k+1]}, straight")
            g = [[wp[k][1], wp[k][0]], [wp[k + 1][1], wp[k + 1][0]]]
            dist = 0.0
        loop_geom.append(g)
        loop_km += dist
        nm_a = ons[LOOP_IDS[k]].area
        nm_b = ons[LOOP_IDS[k + 1]].area
        viatag = f"  (via {len(LEG_VIAS[k])} pt)" if LEG_VIAS[k] else ""
        print(f"  {nm_a:>6} -> {nm_b:<6} {dist:6.1f} km{viatag}")
    print(f"Loop total: {loop_km:.1f} km")

    loop_pts = [p for leg in loop_geom for p in leg]
    pre = list(zip(lat[:i_start + 1].tolist(), lon[:i_start + 1].tolist()))
    post = list(zip(lat[i_end:].tolist(), lon[i_end:].tolist()))
    combined = pre + loop_pts + post

    # graft out-and-back spurs for the off-line new onsens (湯の児, 赤川, Oita pair)
    if SPURS:
        print("Grafting spurs:")
        combined = graft_spurs(combined, ons)

    clat = np.array([p[0] for p in combined])
    clon = np.array([p[1] for p in combined])
    ccum = cumulative(clat, clon)
    print(f"Combined line: {ccum[-1]:.0f} km ({len(combined)} pts)")

    # re-snap all onsens
    rows = []
    for o in ons.values():
        R = 6371.0
        la1, lo1 = np.radians(o.lat), np.radians(o.lon)
        a = (np.sin((np.radians(clat) - la1) / 2) ** 2
             + np.cos(la1) * np.cos(np.radians(clat)) * np.sin((np.radians(clon) - lo1) / 2) ** 2)
        dd = R * 2 * np.arcsin(np.sqrt(a))
        j = int(np.argmin(dd))
        rows.append({"o": o, "dist_km": float(dd[j]), "along_km": float(ccum[j])})
    passed = sorted((r for r in rows if r["dist_km"] <= PASS_KM), key=lambda r: r["along_km"])
    pc = Counter(r["o"].pref_short for r in passed)

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
            "in_loop": o.id in LOOP_ONSEN_IDS,
            "is_spur": o.id in SPUR_ONSEN_IDS,
            "is_buffer": o.id in BUFFER_ONSEN_IDS,
        })
    result = {"source": "Kyuhachi-3 + Nagasaki LOOP (road-corrected)",
              "line_km": round(float(ccum[-1]), 1), "loop_km": round(loop_km, 1),
              "passed": len(passed), "prefecture_coverage": dict(pc),
              "all7": all(p in pc for p in ALL7), "stops": stops}
    (HERE / "handdrawn_loop_analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    write_gpx(combined, stops)
    write_map(combined, stops, loop_geom, result)

    summ, ev = simulate.simulate(HERE / "handdrawn_loop_analysis.json", policy="patient", road_factor=1.0)
    simulate.write_itinerary(summ, ev, HERE / "itinerary_loop.md", warnings=difficulty.CRUX_ZONES)

    print(f"\nNOW: {len(passed)} onsens, coverage {dict(pc)}, all7={result['all7']}")
    print(f"schedule: finish {summ['finish']}, {summ['calendar_days_used']} days, "
          f"{summ['slack_days_to_deadline']} slack, banked {summ['banked']}")
    print("\nNew order through the loop region:")
    for s in stops:
        if 52 <= s["order"] <= 63:
            tag = " ◄loop" if s.get("in_loop") else ""
            print(f"  {s['order']:>3} {s['pref_short']} {s['area']}：{s['name'][:16]}{tag}")
    print("\nWrote kyuhachi_nagasaki_loop.gpx, route_nagasaki_loop_map.html, "
          "handdrawn_loop_analysis.json, itinerary_loop.md")


def _gpx_tag(s):
    if s.get("is_buffer"):
        return " [BUFFER]"
    if s.get("is_spur"):
        return " [SPUR]"
    if s.get("in_loop"):
        return " [LOOP]"
    return ""


def write_gpx(combined, stops):
    geo.write_gpx(HERE / "kyuhachi_nagasaki_loop.gpx", combined, stops,
                  meta_name="Kyuhachi + Nagasaki loop", trk_name="Kyuhachi+Nagasaki loop",
                  tag_fn=_gpx_tag)


def write_map(combined, stops, loop_geom, result):
    pts = [{"o": s["order"], "id": s["id"], "name": f'{s["area"]}：{s["name"]}',
            "pref": s["prefecture"], "lat": s["lat"], "lon": s["lon"],
            "color": PREF_COLORS.get(s["prefecture"], "#888"), "loop": s.get("in_loop", False),
            "spur": s.get("is_spur", False), "buffer": s.get("is_buffer", False)}
           for s in stops]
    loop_line = [p for leg in loop_geom for p in leg]
    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Kyuhachi + Nagasaki loop ({result['passed']}湯)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body{{margin:0;height:100%;font-family:system-ui,sans-serif}}#map{{height:100%}}
.num{{color:#fff;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;
justify-content:center;font-size:11px;font-weight:700;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)}}
.loop{{box-shadow:0 0 0 3px #ff1744,0 1px 3px rgba(0,0,0,.5)}}
.spur{{box-shadow:0 0 0 3px #00bfa5,0 1px 3px rgba(0,0,0,.5)}}
.buffer{{box-shadow:0 0 0 3px #ffab00,0 1px 3px rgba(0,0,0,.5)}}</style>
</head><body><div id="map"></div><script>
const PTS={json.dumps(pts, ensure_ascii=False)};const LINE={json.dumps(combined)};
const LOOP={json.dumps(loop_line)};
const map=L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:18,attribution:'&copy; OpenStreetMap'}}).addTo(map);
L.polyline(LINE,{{color:'#1565c0',weight:3,opacity:.65}}).addTo(map);
L.polyline(LOOP,{{color:'#ff1744',weight:4,opacity:.9}}).addTo(map);
PTS.forEach(p=>{{const ring=p.buffer?'buffer':(p.spur?'spur':(p.loop?'loop':''));const icon=L.divIcon({{className:'',html:`<div class="num ${{ring}}" style="background:${{p.color}}">${{p.o}}</div>`,iconSize:[22,22],iconAnchor:[11,11]}});
const tag=p.buffer?' · BUFFER (optional)':(p.spur?' · SPUR':(p.loop?' · NAGASAKI LOOP':''));
L.marker([p.lat,p.lon],{{icon}}).addTo(map).bindPopup(`<b>${{p.o}}. ${{p.name}}</b><br>${{p.pref}} · #${{p.id}}${{tag}}`);}});
map.fitBounds(LOOP);
</script></body></html>"""
    (HERE / "route_nagasaki_loop_map.html").write_text(html)


if __name__ == "__main__":
    main()
