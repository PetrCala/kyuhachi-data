#!/usr/bin/env python3
"""Build a ROUTE-ONLY overlay catalog = frozen baseline + staged new onsens.

The canonical ``data/snapshot.db`` is the diff *baseline* and must stay frozen
until a real catalog publish advances it (see CLAUDE.md). For route planning we
only need the new onsens' coords + hours, so this script makes a throwaway copy
under ``cache/`` and injects the staged delta there. Point the planner at it via

    KYUHACHI_SNAPSHOT_DB=route_planning/cache/snapshot_overlay.db python route_planning/analyze_handdrawn.py

Inputs : data/snapshot.db (read-only) + route_planning/new_onsens_staged.json
Output : route_planning/cache/snapshot_overlay.db  (regenerable)

Never writes data/snapshot.db, the id-map, or Firestore.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BASELINE = REPO / "data" / "snapshot.db"
STAGED = HERE / "new_onsens_staged.json"
OUT = HERE / "cache" / "snapshot_overlay.db"

# columns we can populate on the onsens table from the staged record
COLS = [
    "id", "onsen_area_name", "facility_name", "latitude", "longitude",
    "prefecture", "address", "phone", "business_hours", "admission_fee",
    "spring_quality", "access_info", "efficacy", "website_url", "image_url",
    "scraped_at",
]


def main() -> None:
    staged = json.loads(STAGED.read_text(encoding="utf-8"))
    added = staged["added"]
    removed = staged.get("removed", [])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BASELINE, OUT)  # start from the frozen baseline, untouched at source

    con = sqlite3.connect(OUT)
    before = con.execute("SELECT count(*) FROM onsens").fetchone()[0]

    # drop delisted-upstream onsens (already isActive:false in Firestore)
    for hid in removed:
        con.execute("DELETE FROM onsens WHERE id = ?", (hid,))

    # upsert the staged new onsens
    placeholders = ", ".join("?" for _ in COLS)
    collist = ", ".join(COLS)
    for rec in added:
        con.execute(
            f"INSERT OR REPLACE INTO onsens ({collist}) VALUES ({placeholders})",
            [rec.get(c) for c in COLS],
        )

    con.commit()
    after = con.execute("SELECT count(*) FROM onsens").fetchone()[0]
    con.close()

    print(f"overlay built: {OUT}")
    print(f"  baseline {before}  ->  overlay {after}   (+{len(added)} added, -{len(removed)} removed)")
    print(f"  removed (delisted upstream): {removed}")
    print(f"  point the planner at it:  KYUHACHI_SNAPSHOT_DB={OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
