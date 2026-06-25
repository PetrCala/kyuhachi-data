#!/usr/bin/env python3
"""Per-section difficulty / remoteness warnings for the Nagasaki-loop foot route.

The crux zones below were derived from two grounded sources:
  - an SRTM-30 m elevation profile sampled ~every 1.3 km along
    kyuhachi_nagasaki_loop.gpx (cache/elev_profile.json) -> per-leg climb,
    steepness (m/km) and peak height;
  - the no-resupply / water gaps in final_route/logistics.json
    (OpenStreetMap conbini/food/lodging/water within 1 km of the line).

Each zone is keyed by an INCLUSIVE stop-order range (matching `order` in
handdrawn_loop_analysis.json and the itinerary). simulate.write_itinerary emits
each zone once, as a blockquote at the top of the FIRST day that enters its
range — i.e. a heads-up before you walk into the hard stretch.

Stop orders are specific to THIS route's ordering; if a re-snap in
remap_nagasaki_loop reorders the stops, revisit these ranges. The whole loop is
~1,160 km with at least ~12,500 m of cumulative ascent (a floor — the 1.3 km
sampling misses short rolls); difficulty is concentrated in the blocks below,
everything else is low rolling coastal/basin walking.
"""
from __future__ import annotations

CRUX_ZONES = [
    {
        "orders": (12, 20),
        "title": "Kirishima volcanic highlands — first big climb",
        "lines": [
            "Terrain: climb onto the massif (霧島新湯 #14 ~920 m, 硫黄谷 #13 ~681 m) "
            "at ~47 m/km, then a ~1,200 m drop off the rim into 皇子原 (#14→15, tops "
            "~1,409 m); re-climb 小林→白鳥 (#18→19) +537 m to 738 m.",
            "Remote: a 55 km no-resupply stretch near 白鳥 (#19), with a 28 km gap "
            "right before it — carry food and water.",
        ],
    },
    {
        "orders": (30, 32),
        "title": "Shibi range — longest no-shop stretch of the route",
        "lines": [
            "Remote: ~61 km with no conbini / shop / lodging through the 紫尾山地 "
            "(紫尾 #31 → 川内高城 #32) — the single longest resupply gap on the loop. "
            "Only moderate hills (~300–350 m). Stock up before you leave.",
        ],
    },
    {
        "orders": (35, 42),
        "title": "Yatsushiro coast → Aso south flank — biggest sustained climb",
        "lines": [
            "Terrain: the route's biggest single climb leg, 日奈久→垂玉 (#37→38) "
            "≈ +786 m hauling from the coast onto Aso's south rim (垂玉/地獄 ~700 m); "
            "the Aso outer-rim crossing 内牧→菊池 (#41→42) tops ~930 m.",
            "Remote: a 40 km no-resupply gap on the Ashikita coast before the climb "
            "(near 湯浦 #36).",
        ],
    },
    {
        "orders": (59, 62),
        "title": "Sefuri foothills — long climb-and-drop",
        "lines": [
            "Terrain: 古湯→久留米 (#61→62) climbs ≈ +1,010 m over 38 km (~27 m/km) "
            "crossing back over the Sefuri edge to the Chikugo plain — mid-altitude "
            "but a big up-and-over.",
        ],
    },
    {
        "orders": (85, 92),
        "title": "Kuju massif — THE crux (alpine, walk-in onsen)",
        "lines": [
            "Terrain: highest and steepest of the whole route. 法華院 (#91, ~1,250 m) "
            "is reachable on FOOT ONLY; 星生 (#90) 1,126 m; the trail crosses a col "
            "near 1,727 m. Steepest legs anywhere: 星生→法華院 ~80 m/km, "
            "小田→筋湯 ~62 m/km.",
            "Remote / conditions: three stacked no-resupply gaps (≈ km 1040–1115) "
            "plus a 35 km gap onward to 湯平. Carry food, expect cold and early dark "
            "in early November, and treat 法華院 as a mountain hut, not a roadside onsen.",
        ],
    },
    {
        "orders": (96, 100),
        "title": "Yufuin → Beppu — a climbing finish, not a coast-down",
        "lines": [
            "Terrain: 長湯→湯平 (#95→96) ≈ +572 m (~35 m/km); 由布院→塚原 (#98→99) "
            "+418 m (~49 m/km) up the Yufu/Tsurumi shoulder to 塚原 (777 m), then a "
            "steep drop into Beppu (明礬/鉄輪) to close the loop.",
            "Remote: a 22 km no-resupply gap near 塚原 (#99).",
        ],
    },
]
