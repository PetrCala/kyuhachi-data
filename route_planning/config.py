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
VISIT_MIN = 20           # minutes per onsen visit (onsendo.db real stays: median 13, p75 18)
ROAD_FACTOR = 1.3        # great-circle -> real foot distance (haversine fallback only)
WAKE_MIN = 6 * 60        # 06:00 — awake window start
SLEEP_MIN = 22 * 60      # 22:00 — sleep (8 h)

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
