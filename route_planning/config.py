#!/usr/bin/env python3
"""Single source of truth for foot-route planning constants.

Every script in route_planning/ imports its anchors, walk model, dates,
exclusions, and paths from here — so changing the deadline, walk speed, or an
exclusion is a one-line edit, not a hunt across files.

Edit-SPECIFIC constants (e.g. the Nagasaki loop's via-points) stay in their own
edit script, NOT here — this file is only for globally-shared values.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

# --- paths -----------------------------------------------------------------
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
# Onsen catalog (source of truth). Route planning is READ-ONLY against it.
# Override with KYUHACHI_SNAPSHOT_DB to point at a route-only overlay copy
# (baseline + staged new onsens) without ever mutating the frozen diff baseline.
SNAPSHOT_DB = Path(os.environ.get("KYUHACHI_SNAPSHOT_DB", REPO / "data" / "snapshot.db"))
# The hand-drawn line is the source of truth for the PATH (drawn on plotaroute):
HANDDRAWN_GPX = Path("/Users/petr/code/kyuhachi/local/route_26_02_14/Kyuhachi-3.gpx")
FINAL_DIR = HERE / "final_route"                     # canonical output (regenerable)
CACHE_DIR = HERE / "cache"                            # OSRM + Overpass caches (regenerable)

# --- fixed route anchors (GIVEN, do not change) ----------------------------
START = ("長崎鼻 (Cape Nagasakibana)", 31.1556, 130.5944)  # (name, lat, lon); not a counted onsen
END_ID = 41                                           # 浜脇温泉 茶房たかさきの湯, Beppu — fixed terminus

# --- walk model (empirically grounded; see README) -------------------------
SPEED_KMH = 4.0          # loaded moving pace (Strava: moving 5.05 / elapsed 3.97 -> ~4.0)
VISIT_MIN = 50           # blended per-onsen visit: short hops in clusters, long stays at
                         # the good ones (~45-60 min avg; raw onsendo stays median 13).
ROAD_FACTOR = 1.3        # great-circle -> real foot distance (haversine fallback only)
WAKE_MIN = 6 * 60        # 06:00 — start of the walking day
SLEEP_MIN = 18 * 60      # 18:00 — end of the walking day (realistic 12 h day, ~30-40 km;
                         # rest/onsen/sleep after). NOT literally sleep — just the walk cutoff.

# --- grade penalty (Naismith) ----------------------------------------------
# The flat SPEED_KMH ignores climbs; on Kyushu-88's real ascents (Kirishima, Aso
# south rim, the Kuju massif) a day's distance costs more time than the flat model
# implies. simulate adds CLIMB_MIN_PER_M of walking time per metre of ASCENT, from
# the SRTM per-leg ascent in route_elevation.json (built by elevation.py).
# Naismith's rule = +1 h per 600 m climbed -> 0.10 min/m. Ascent-only (Tobler /
# Langmuir would also slow steep descents) — the standard, conservative choice.
CLIMB_MIN_PER_M = 60.0 / 600.0   # 0.10 min per metre of ascent
ELEVATION_JSON = HERE / "route_elevation.json"   # SRTM per-leg record written by
                                                 # elevation.py (which also bakes
                                                 # ascent_m into the analysis stops)

# --- trip dates ------------------------------------------------------------
START_DT = datetime(2026, 10, 2, 6, 0)      # Fri Oct 2 2026, early morning
DEADLINE = datetime(2026, 12, 2, 23, 59)    # finish by Wed Dec 2 2026 (flight Dec 3)

# --- snapping --------------------------------------------------------------
PASS_KM = 2.0            # an onsen within this of the line counts as "on route"

# --- exclusion policy ------------------------------------------------------
# OFFSHORE is enforced LIVE by load_onsens(); the rest are policy used by the
# OSRM auto-router (archived) and documented here as the "don't visit" decision.
OFFSHORE_IDS = {130, 219, 176, 237}            # 壱岐 Iki, 屋久島 Yakushima, 種子島 Tanegashima (ferry-only)
AMAKUSA = {90}                                  # OSRM foot can't route the 天草五橋
SAKURAJIMA_EASTBAY = {116, 140, 217}           # 古里(桜島), 海潟, テイエム牧場 — east of Kagoshima bay
EAST_MIYAZAKI = {95, 96, 100, 189, 205, 224, 231, 246}  # east of 都城 / Miyazaki-city coast
SHIMABARA_IDS = {21, 24, 165, 175}             # Shimabara/Unzen peninsula (land spur via Isahaya)

ALL7 = ["福岡", "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島"]

# --- opening hours -----------------------------------------------------------
# The hand-reviewed schedule the app publishes (data/hours_curated.json), keyed by
# upstream hid. curated_hours.py overlays it onto every stop; the regex parse in
# onsen_model.py is only the fallback for an onsen the file does not know.
CURATED_HOURS = REPO / "data" / "hours_curated.json"
# Japanese national holidays inside the trip window (START_DT..DEADLINE): 祝日は営業 /
# 定休日が祝日の場合は翌日休 rules key off these. Extend if the window moves.
HOLIDAYS = frozenset({
    datetime(2026, 10, 12).date(),   # スポーツの日
    datetime(2026, 11, 3).date(),    # 文化の日
    datetime(2026, 11, 23).date(),   # 勤労感謝の日
})

# --- the walk as it happens (progress.py) -------------------------------------
# The app publishes the journey without sign-in (Firestore rules in the kyuhachi
# repo): walked-day tracks under /journey_days, and this uid's challenges, visits
# and routes. JOURNEY_UID mirrors kyuhachi/shared/src/types/journey.ts.
FIREBASE_PROJECT = "kyuhachi-fddcc"
JOURNEY_UID = "juEfBPJSspS9E2dqMzRac07C1Gs1"
FULL_ROUTE_GPX = FINAL_DIR / "00_full_route.gpx"   # the committed line, for position
TARGET_VISITS = 88

# --- decisions made on the trail (progress.py applies them) -------------------
# Changes to the drawn line the walker has committed to. Each one names the stops it
# drops (by hid, so a regenerated analysis keeps them) and how much line it adds or
# saves; `from_km` is where on the drawn line the change starts, so it stops counting
# once you are past it. The story behind each lives in route_planning/walk_decisions.md.
ROUTE_CHANGES = [
    {"name": "skip the Fukuoka loop (鳥栖 → 朝倉 direct)", "from_km": 869.2,
     "drop_hids": [1, 9, 8], "line_km": -35.0},
    {"name": "skip the Oita loop (別府 加賀屋 → 竹瓦 direct)", "from_km": 1175.1,
     "drop_hids": [259, 258, 66], "line_km": -28.0},
    {"name": "Aso crater out-and-back from the 垂玉 side (aso_crater_spur.gpx)", "from_km": 533.8,
     "drop_hids": [], "line_km": +31.0},
]
# Zero-km days still intended, as (near line km, label). Kumamoto city is on the line.
REST_DAYS = [
    (495.0, "Kumamoto city (Montbell, resupply)"),
    (812.0, "typhoon, Mon 10-26: north Saga plain (佐賀大和 / 熊の川 / 古湯)"),
]
REST_DAYS_MAYBE = [
    (945.0, "Chikugo river cluster: 吉井 原鶴 とよとみ 筑後川×2 林田"),
]
# Overhead of feet over line progress (door detours, town wandering), measured on the
# walk: ~8% once corner cuts are taken out.
FEET_OVER_LINE = 1.08
