#!/usr/bin/env python3
"""Direction A: analyze the user's hand-drawn Kyuhachi-3.gpx as the source line.

Snaps every foot-eligible onsen onto the hand-drawn track, orders the ones the
line passes by along-track position, checks challenge coverage (>=88, all 7
prefectures), cross-references our OSRM-selected 108, and runs the hours-aware
simulator using the line's OWN distances. Read-only.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from config import ALL7, HANDDRAWN_GPX, PASS_KM
from geo import load_track, nearest_on_track
from onsen_model import load_onsens  # excludes the 4 ferry islands -> 144 onsens
import simulate

HERE = Path(__file__).resolve().parent
GPX = HANDDRAWN_GPX
NEAR_KM = 5.0


def main():
    lat, lon, cum = load_track(GPX)
    total_line_km = float(cum[-1])
    ons = load_onsens()
    osrm_ids = set()
    osrm_path = HERE / "route_osrm.json"
    if osrm_path.exists():
        osrm_ids = {s["id"] for s in json.loads(osrm_path.read_text())["stops"]}

    rows = []
    for o in ons:
        dkm, along = nearest_on_track(o.lat, o.lon, lat, lon, cum)
        rows.append({"o": o, "dist_km": dkm, "along_km": along})

    passed = sorted((r for r in rows if r["dist_km"] <= PASS_KM), key=lambda r: r["along_km"])
    near = [r for r in rows if PASS_KM < r["dist_km"] <= NEAR_KM]
    off = [r for r in rows if r["dist_km"] > NEAR_KM]

    pc = Counter(r["o"].pref_short for r in passed)
    print("=" * 66)
    print(f"HAND-DRAWN LINE: {total_line_km:.0f} km, {len(lat)} pts")
    print("=" * 66)
    for thr in (1, 2, 3, 5):
        c = sum(1 for r in rows if r["dist_km"] <= thr)
        print(f"  onsens within {thr} km of the line: {c}")
    print(f"\nPASSED (<= {PASS_KM} km): {len(passed)} onsens")
    print(f"  prefecture coverage: {dict(pc)}")
    print(f"  all 7 prefectures: {all(p in pc for p in ALL7)}"
          + ("" if all(p in pc for p in ALL7) else f"  MISSING: {[p for p in ALL7 if p not in pc]}"))
    print(f"  >= 88 unique: {len(passed) >= 88}")
    overlap = sum(1 for r in passed if r["o"].id in osrm_ids)
    print(f"  overlap with our OSRM-108: {overlap} of {len(osrm_ids)} also passed by your line")

    # onsens our solver wanted but your line misses
    missed_osrm = [r for r in rows if r["o"].id in osrm_ids and r["dist_km"] > PASS_KM]
    print(f"\nOur OSRM picks your line does NOT pass (<= {PASS_KM} km): {len(missed_osrm)}")
    for r in sorted(missed_osrm, key=lambda r: -r["dist_km"])[:15]:
        print(f"  {r['dist_km']:5.1f} km off  #{r['o'].id:>3} {r['o'].pref_short} "
              f"{r['o'].area}：{r['o'].name[:16]}")

    # build a route json in along-track order using the line's own distances
    stops = []
    prev_along = 0.0
    for i, r in enumerate(passed):
        o = r["o"]
        leg = max(0.0, r["along_km"] - prev_along)
        prev_along = r["along_km"]
        stops.append({
            "order": i + 1, "id": o.id, "area": o.area, "name": o.name,
            "prefecture": o.prefecture, "pref_short": o.pref_short,
            "lat": o.lat, "lon": o.lon,
            "dist_to_line_km": round(r["dist_km"], 2),
            "along_km": round(r["along_km"], 1),
            "leg_km_gc": round(leg, 2), "cum_km_gc": round(r["along_km"], 1),
            "open_min": o.open_min, "last_min": o.effective_last_min,
            "closed_weekdays": sorted(o.closed_weekdays),
            "never_closes": o.never_closes, "irregular": o.irregular,
            "in_osrm_108": o.id in osrm_ids,
        })
    result = {
        "source": "Kyuhachi-3.gpx (hand-drawn)", "line_km": round(total_line_km, 1),
        "pass_km": PASS_KM, "passed": len(passed),
        "prefecture_coverage": dict(pc),
        "all7": all(p in pc for p in ALL7), "ge_88": len(passed) >= 88,
        "stops": stops,
    }
    (HERE / "handdrawn_analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))

    # simulate along YOUR line (leg_km already real, road_factor=1.0)
    summ, ev = simulate.simulate(HERE / "handdrawn_analysis.json", policy="patient", road_factor=1.0)
    simulate.write_itinerary(summ, ev, HERE / "itinerary_handdrawn.md")
    print("\n" + "=" * 66)
    print("HOURS-AWARE SIM ALONG YOUR LINE (patient policy)")
    print("=" * 66)
    for k in ("finish", "calendar_days_used", "slack_days_to_deadline", "banked",
              "banked_ge_88", "waits", "idle_days_from_waits", "max_onsens_one_day",
              "irregular_不定休_visited(risk)"):
        print(f"  {k}: {summ[k]}")
    print("\nWrote handdrawn_analysis.json, itinerary_handdrawn.md")
    return result


if __name__ == "__main__":
    main()
