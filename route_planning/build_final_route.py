#!/usr/bin/env python3
"""Package the final corrected route (hand-drawn line + Nagasaki loop) into a
single self-contained folder: full GPX + full map + itinerary + per-stage
GPX/maps + a README index.

Inputs:  kyuhachi_nagasaki_loop.gpx (combined track), handdrawn_loop_analysis.json
Output:  final_route/
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import numpy as np

import difficulty
import geo
import simulate
from geo import load_track

HERE = Path(__file__).resolve().parent
TRACK_GPX = HERE / "kyuhachi_nagasaki_loop.gpx"
ANALYSIS = HERE / "handdrawn_loop_analysis.json"
FULL_MAP = HERE / "route_nagasaki_loop_map.html"
OUT = HERE / "final_route"
N_STAGES = 8
PREF_COLORS = {"福岡県": "#e6194B", "佐賀県": "#f58231", "長崎県": "#ffe119",
               "熊本県": "#3cb44b", "大分県": "#4363d8", "宮崎県": "#911eb4", "鹿児島県": "#f032e6"}


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    analysis = json.loads(ANALYSIS.read_text())
    stops = analysis["stops"]
    lat, lon, cum = load_track(TRACK_GPX)
    total = float(cum[-1])

    summ, events = simulate.simulate(ANALYSIS, policy="patient", road_factor=1.0)
    ev_by_id = {e["id"]: e for e in events}

    # copy full-route artifacts
    shutil.copy(TRACK_GPX, OUT / "00_full_route.gpx")
    shutil.copy(FULL_MAP, OUT / "00_full_route_map.html")
    simulate.write_itinerary(summ, events, OUT / "00_itinerary.md", warnings=difficulty.CRUX_ZONES)

    # chunk by ~equal distance, cut between onsens
    target = total / N_STAGES
    stage_of, k = [], 0
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
        lo_km, hi_km = max(0, a_km - 1), min(total, b_km + 1)
        mask = (cum >= lo_km) & (cum <= hi_km)
        track = [[float(la), float(lo)] for la, lo in zip(lat[mask], lon[mask])]
        prefs = Counter(m["pref_short"] for m in members)
        dates = sorted({ev_by_id[m["id"]]["date"] for m in members if m["id"] in ev_by_id})
        stage = {"n": sidx + 1, "onsens": members, "km": round(b_km - a_km, 1),
                 "prefs": dict(prefs), "n_onsens": len(members),
                 "date_from": dates[0] if dates else "?", "date_to": dates[-1] if dates else "?",
                 "track": track}
        stages.append(stage)
        write_stage_gpx(stage)
        write_stage_map(stage)

    write_readme(stages, total, summ, analysis)
    print(f"Final route packaged in {OUT}/")
    for st in stages:
        pf = "・".join(f"{p}{n}" for p, n in st["prefs"].items())
        print(f"  Stage {st['n']}: {st['km']:>5.0f} km, {st['n_onsens']:>2} onsens, "
              f"{st['date_from']}→{st['date_to']}  [{pf}]")
    print(f"\nFiles: {sorted(p.name for p in OUT.iterdir())}")


def _stop_tag(m):
    if m.get("is_buffer"):
        return " [BUFFER]"
    if m.get("is_spur"):
        return " [SPUR]"
    if m.get("in_loop"):
        return " [LOOP]"
    return ""


def write_stage_gpx(stage):
    geo.write_gpx(OUT / f"stage_{stage['n']:02d}.gpx", stage["track"], stage["onsens"],
                  meta_name=f'Kyuhachi Stage {stage["n"]}', trk_name=f'Stage {stage["n"]}',
                  tag_fn=_stop_tag)


def write_stage_map(stage):
    pts = [{"o": m["order"], "id": m["id"], "name": f'{m["area"]}：{m["name"]}',
            "pref": m["prefecture"], "lat": m["lat"], "lon": m["lon"],
            "color": PREF_COLORS.get(m["prefecture"], "#888"),
            "off": m["dist_to_line_km"], "loop": m.get("in_loop", False),
            "spur": m.get("is_spur", False), "buffer": m.get("is_buffer", False)} for m in stage["onsens"]]
    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Stage {stage['n']} ({stage['n_onsens']}湯, {stage['km']:.0f}km)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body{{margin:0;height:100%;font-family:system-ui,sans-serif}}#map{{height:100%}}
.num{{color:#fff;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;
justify-content:center;font-size:11px;font-weight:700;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)}}
.loop{{box-shadow:0 0 0 3px #ff1744,0 1px 3px rgba(0,0,0,.5)}}
.spur{{box-shadow:0 0 0 3px #00bfa5,0 1px 3px rgba(0,0,0,.5)}}
.buffer{{box-shadow:0 0 0 3px #ffab00,0 1px 3px rgba(0,0,0,.5)}}</style>
</head><body><div id="map"></div><script>
const PTS={json.dumps(pts, ensure_ascii=False)};const LINE={json.dumps(stage['track'])};
const map=L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:18,attribution:'&copy; OpenStreetMap'}}).addTo(map);
L.polyline(LINE,{{color:'#1565c0',weight:3,opacity:.8}}).addTo(map);
PTS.forEach(p=>{{const ring=p.buffer?'buffer':(p.spur?'spur':(p.loop?'loop':''));const icon=L.divIcon({{className:'',html:`<div class="num ${{ring}}" style="background:${{p.color}}">${{p.o}}</div>`,iconSize:[22,22],iconAnchor:[11,11]}});
const tg=p.buffer?' · BUFFER(optional)':(p.spur?' · SPUR':'');
L.marker([p.lat,p.lon],{{icon}}).addTo(map).bindPopup(`<b>${{p.o}}. ${{p.name}}</b><br>${{p.pref}} · #${{p.id}} · ${{p.off}}km off line${{tg}}`);}});
map.fitBounds(LINE.length?LINE:PTS.map(p=>[p.lat,p.lon]));
</script></body></html>"""
    (OUT / f"stage_{stage['n']:02d}_map.html").write_text(html)


def write_readme(stages, total, summ, analysis):
    pc = analysis["prefecture_coverage"]
    lines = [
        "# 九州八十八湯 — final foot route",
        "",
        f"Hand-drawn line + Nagasaki loop. **{total:.0f} km**, "
        f"**{analysis['passed']} onsens**, all 7 prefectures "
        f"({'・'.join(f'{k}{v}' for k, v in pc.items())}).",
        "",
        f"Schedule (hours-aware, patient policy): start **{summ['start']}**, "
        f"finish **{summ['finish']}**, **{summ['calendar_days_used']} days** "
        f"({summ['slack_days_to_deadline']} days slack to the Dec 2 deadline), "
        f"banks all {summ['banked']}.",
        "",
        (f"Includes **{sum(1 for s in analysis['stops'] if s.get('is_spur'))} grafted spur** "
         f"onsen(s) and **{sum(1 for s in analysis['stops'] if s.get('is_buffer'))} optional "
         f"buffer** pickups (🅑 = only on an out-and-back detour; skip them and you finish "
         f"earlier). Spurs ring teal, buffers ring amber on the maps."),
        "",
        "## Whole route",
        "- [`00_full_route_map.html`](00_full_route_map.html) — full map (red = Nagasaki loop)",
        "- [`00_full_route.gpx`](00_full_route.gpx) — full GPX (load into plotaroute/gpx.studio/Garmin)",
        "- [`00_itinerary.md`](00_itinerary.md) — day-by-day hours-aware schedule",
        "",
        "## Stages",
        "| Stage | km | onsens | dates | prefectures | files |",
        "|---|---|---|---|---|---|",
    ]
    for s in stages:
        pf = "・".join(f"{p}×{n}" for p, n in s["prefs"].items())
        lines.append(f"| **{s['n']}** | {s['km']:.0f} | {s['n_onsens']} | "
                     f"{s['date_from']}→{s['date_to']} | {pf} | "
                     f"[gpx](stage_{s['n']:02d}.gpx) · [map](stage_{s['n']:02d}_map.html) |")
    lines += ["", "## Stage detail", ""]
    for s in stages:
        lines.append(f"### Stage {s['n']} — {s['km']:.0f} km, {s['date_from']}→{s['date_to']}")
        for m in s["onsens"]:
            tag = (" ◄BUFFER (optional)" if m.get("is_buffer")
                   else " ◄spur" if m.get("is_spur")
                   else " ◄Nagasaki loop" if m.get("in_loop") else "")
            lines.append(f"- {m['order']}. {m['pref_short']} {m['area']}：{m['name']} "
                         f"({m['dist_to_line_km']}km off line){tag}")
        lines.append("")
    (OUT / "README.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
