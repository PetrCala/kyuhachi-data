#!/usr/bin/env python3
"""Direction B: chunk the hand-drawn route into editable multi-day STAGES.

Splits the line (and the onsens it passes, from analyze_handdrawn.py) into ~N
contiguous stages of roughly equal walking distance. Each stage gets:
  stages/stage_NN.gpx       track slice + onsen waypoints (plot/edit/walk alone)
  stages/stage_NN_map.html  self-contained Leaflet mini-map
  stages/index.md           overview table with per-stage stats + schedule dates
Read-only w.r.t. the catalog.
"""
from __future__ import annotations

import json
import xml.dom.minidom as minidom
from collections import Counter
from pathlib import Path

import numpy as np

import simulate

HERE = Path(__file__).resolve().parent
GPX = "/Users/petr/code/kyuhachi/local/route_26_02_14/Kyuhachi-3.gpx"
STAGES_DIR = HERE / "stages"
N_STAGES = 8
PREF_COLORS = {
    "福岡県": "#e6194B", "佐賀県": "#f58231", "長崎県": "#ffe119",
    "熊本県": "#3cb44b", "大分県": "#4363d8", "宮崎県": "#911eb4", "鹿児島県": "#f032e6",
}


def load_track(path):
    d = minidom.parse(path)
    tp = d.getElementsByTagName("trkpt")
    lat = np.array([float(t.getAttribute("lat")) for t in tp])
    lon = np.array([float(t.getAttribute("lon")) for t in tp])
    R = 6371.0
    la, lo = np.radians(lat), np.radians(lon)
    a = (np.sin(np.diff(la) / 2) ** 2
         + np.cos(la[:-1]) * np.cos(la[1:]) * np.sin(np.diff(lo) / 2) ** 2)
    cum = np.concatenate([[0.0], np.cumsum(R * 2 * np.arcsin(np.sqrt(a)))])
    return lat, lon, cum


def main():
    STAGES_DIR.mkdir(exist_ok=True)
    analysis = json.loads((HERE / "handdrawn_analysis.json").read_text())
    stops = analysis["stops"]
    lat, lon, cum = load_track(GPX)
    total = float(cum[-1])

    # schedule dates per onsen id (from the patient sim along the line)
    summ, events = simulate.simulate(HERE / "handdrawn_analysis.json",
                                     policy="patient", road_factor=1.0)
    ev_by_id = {e["id"]: e for e in events}

    # stage boundaries by ~equal distance; cut between onsens
    target = total / N_STAGES
    stage_of = []
    k = 0
    for s in stops:
        while k < N_STAGES - 1 and s["along_km"] > (k + 1) * target:
            k += 1
        stage_of.append(k)

    stages = []
    for sidx in range(N_STAGES):
        members = [s for s, st in zip(stops, stage_of) if st == sidx]
        if not members:
            continue
        a_km = 0.0 if sidx == 0 else members[0]["along_km"]
        b_km = total if sidx == N_STAGES - 1 else members[-1]["along_km"]
        # pad a touch so the slice reaches the onsens
        lo_km, hi_km = max(0, a_km - 1), min(total, b_km + 1)
        mask = (cum >= lo_km) & (cum <= hi_km)
        slat, slon = lat[mask], lon[mask]
        prefs = Counter(m["pref_short"] for m in members)
        dates = sorted({ev_by_id[m["id"]]["date"] for m in members if m["id"] in ev_by_id})
        stage = {
            "n": sidx + 1, "onsens": members,
            "km": round(b_km - a_km, 1), "along_from": round(a_km, 1), "along_to": round(b_km, 1),
            "prefs": dict(prefs), "n_onsens": len(members),
            "date_from": dates[0] if dates else "?", "date_to": dates[-1] if dates else "?",
            "track": [[float(la), float(lo)] for la, lo in zip(slat, slon)],
        }
        stages.append(stage)
        write_stage_gpx(stage)
        write_stage_map(stage)

    write_index(stages, total, summ)
    print(f"Wrote {len(stages)} stages to {STAGES_DIR}/ (gpx + map each) + index.md")
    for st in stages:
        pf = "・".join(f"{p}{n}" for p, n in st["prefs"].items())
        print(f"  Stage {st['n']}: {st['km']:>5.0f} km, {st['n_onsens']:>2} onsens, "
              f"{st['date_from']}→{st['date_to']}  [{pf}]")


def write_stage_gpx(stage):
    seg = "".join(f'<trkpt lat="{la:.6f}" lon="{lo:.6f}"></trkpt>' for la, lo in stage["track"])
    wpts = []
    for m in stage["onsens"]:
        nm = f'{m["order"]}. {m["area"]}：{m["name"]}'.replace("&", "&amp;").replace("<", "＜")
        wpts.append(f'<wpt lat="{m["lat"]:.6f}" lon="{m["lon"]:.6f}"><name>{nm}</name>'
                    f'<desc>{m["prefecture"]} #{m["id"]}</desc></wpt>')
    gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" '
           'creator="kyuhachi-data/route_planning" xmlns="http://www.topografix.com/GPX/1/1">\n'
           f'<metadata><name>Kyuhachi Stage {stage["n"]}</name></metadata>\n'
           + "\n".join(wpts) + "\n<trk><name>Stage "
           f'{stage["n"]}</name><trkseg>{seg}</trkseg></trk>\n</gpx>\n')
    (STAGES_DIR / f"stage_{stage['n']:02d}.gpx").write_text(gpx)


def write_stage_map(stage):
    pts = [{"o": m["order"], "id": m["id"], "name": f'{m["area"]}：{m["name"]}',
            "pref": m["prefecture"], "lat": m["lat"], "lon": m["lon"],
            "color": PREF_COLORS.get(m["prefecture"], "#888"),
            "off": m["dist_to_line_km"]} for m in stage["onsens"]]
    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Stage {stage['n']} ({stage['n_onsens']}湯, {stage['km']:.0f}km)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body{{margin:0;height:100%;font-family:system-ui,sans-serif}}#map{{height:100%}}
.num{{color:#fff;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;
justify-content:center;font-size:11px;font-weight:700;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)}}</style>
</head><body><div id="map"></div><script>
const PTS={json.dumps(pts, ensure_ascii=False)};const LINE={json.dumps(stage['track'])};
const map=L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:18,attribution:'&copy; OpenStreetMap'}}).addTo(map);
L.polyline(LINE,{{color:'#1565c0',weight:3,opacity:.8}}).addTo(map);
PTS.forEach(p=>{{const icon=L.divIcon({{className:'',html:`<div class="num" style="background:${{p.color}}">${{p.o}}</div>`,iconSize:[22,22],iconAnchor:[11,11]}});
L.marker([p.lat,p.lon],{{icon}}).addTo(map).bindPopup(`<b>${{p.o}}. ${{p.name}}</b><br>${{p.pref}} · #${{p.id}} · ${{p.off}}km off line`);}});
map.fitBounds(LINE.length?LINE:PTS.map(p=>[p.lat,p.lon]));
</script></body></html>"""
    (STAGES_DIR / f"stage_{stage['n']:02d}_map.html").write_text(html)


def write_index(stages, total, summ):
    lines = ["# Hand-drawn route — stages", "",
             f"Line: **{total:.0f} km**, {sum(s['n_onsens'] for s in stages)} onsens passed, "
             f"split into {len(stages)} stages. Schedule from the patient sim "
             f"(finish {summ['finish']}, {summ['calendar_days_used']} days).",
             "",
             "> ⚠️ The hand-drawn line covers **6/7 prefectures — no 長崎 Nagasaki**. "
             "A Saga→Hasami spur needs adding (slots into the NW stage near Fukuoka/Kumamoto).",
             "",
             "| Stage | km | onsens | dates | prefectures | files |",
             "|---|---|---|---|---|---|"]
    for s in stages:
        pf = "・".join(f"{p}×{n}" for p, n in s["prefs"].items())
        lines.append(f"| **{s['n']}** | {s['km']:.0f} | {s['n_onsens']} | "
                     f"{s['date_from']}→{s['date_to']} | {pf} | "
                     f"[gpx](stage_{s['n']:02d}.gpx) · [map](stage_{s['n']:02d}_map.html) |")
    lines += ["", "## Stage detail", ""]
    for s in stages:
        lines.append(f"### Stage {s['n']} — {s['km']:.0f} km, {s['date_from']}→{s['date_to']}")
        for m in s["onsens"]:
            tag = "" if m["in_osrm_108"] else "  ·(not in OSRM-108)"
            lines.append(f"- {m['order']}. {m['pref_short']} {m['area']}：{m['name']} "
                         f"({m['dist_to_line_km']}km off line){tag}")
        lines.append("")
    (STAGES_DIR / "index.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
