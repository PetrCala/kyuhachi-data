#!/usr/bin/env python3
"""Shared model: load onsens, parse Japanese business_hours, great-circle distance.

Source of truth: /Users/petr/code/kyuhachi-data/data/snapshot.db (table `onsens`).
This module is READ-ONLY against that DB.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from config import OFFSHORE_IDS, SNAPSHOT_DB as DB
from geo import haversine_km  # re-exported for archived importers (solve_route, km_per_onsen)

WEEKDAYS = "月火水木金土日"  # Mon..Sun -> index 0..6 (Python weekday())

# Fixed weekly closure, e.g. 火曜休 / 木・日曜休 / 毎週火曜休
_CLOSED_RE = re.compile(r"([月火水木金土日](?:・[月火水木金土日])*)曜?[休定]")
# A time like 10:00 or 10：00 or 9時
_TIME_RE = re.compile(r"(\d{1,2})\s*[:：時]\s*(\d{0,2})")
_LAST_ENTRY_RE = re.compile(r"最終受付[^\d]*(\d{1,2})\s*[:：時]\s*(\d{0,2})")


@dataclass
class Onsen:
    id: int
    area: str
    name: str
    lat: float
    lon: float
    prefecture: str  # e.g. 福岡県
    pref_short: str  # e.g. 福岡
    address: str
    hours_raw: str
    fee_raw: str
    # parsed hours
    open_min: int | None = None       # minutes from midnight
    close_min: int | None = None
    last_entry_min: int | None = None  # last admission; overrides close for arrival check
    closed_weekdays: set[int] = field(default_factory=set)  # Python weekday() 0=Mon..6=Sun
    never_closes: bool = False         # 無休
    irregular: bool = False            # 不定休 (unplannable)

    @property
    def effective_last_min(self) -> int | None:
        """Latest minute you can ARRIVE and still get in."""
        if self.last_entry_min is not None:
            return self.last_entry_min
        return self.close_min


def _to_min(h: str, m: str) -> int:
    return int(h) * 60 + (int(m) if m else 0)


def parse_hours(raw: str) -> dict:
    raw = raw or ""
    out: dict = {
        "open_min": None,
        "close_min": None,
        "last_entry_min": None,
        "closed_weekdays": set(),
        "never_closes": False,
        "irregular": False,
    }
    if not raw.strip():
        return out

    out["never_closes"] = "無休" in raw
    out["irregular"] = "不定休" in raw

    # Fixed weekly closures (collect every matched group).
    for m in _CLOSED_RE.finditer(raw):
        # Skip 不定休 / 無休 false hits (handled above; regex won't match 無 anyway)
        token = m.group(1)
        for ch in token.split("・"):
            idx = WEEKDAYS.find(ch)
            if idx >= 0:
                out["closed_weekdays"].add(idx)

    # First time-range on the first line is the opening window.
    first_line = raw.strip().splitlines()[0]
    times = _TIME_RE.findall(first_line)
    if times:
        out["open_min"] = _to_min(*times[0])
        if len(times) >= 2:
            out["close_min"] = _to_min(*times[1])

    le = _LAST_ENTRY_RE.search(raw)
    if le:
        out["last_entry_min"] = _to_min(*le.groups())

    return out


def short_pref(pref: str) -> str:
    return (pref or "").replace("県", "").replace("府", "")


def load_onsens(include_offshore: bool = False) -> list[Onsen]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, onsen_area_name, facility_name, latitude, longitude, "
        "prefecture, address, business_hours, admission_fee FROM onsens"
    ).fetchall()
    con.close()
    out = []
    for r in rows:
        if not include_offshore and r["id"] in OFFSHORE_IDS:
            continue
        h = parse_hours(r["business_hours"] or "")
        o = Onsen(
            id=r["id"],
            area=r["onsen_area_name"] or "",
            name=r["facility_name"] or "",
            lat=r["latitude"],
            lon=r["longitude"],
            prefecture=r["prefecture"] or "",
            pref_short=short_pref(r["prefecture"] or ""),
            address=r["address"] or "",
            hours_raw=r["business_hours"] or "",
            fee_raw=r["admission_fee"] or "",
            **h,
        )
        out.append(o)
    return out


if __name__ == "__main__":
    ons = load_onsens()
    print(f"Loaded {len(ons)} onsens (offshore {sorted(OFFSHORE_IDS)} excluded)")
    never = sum(o.never_closes for o in ons)
    irreg = sum(o.irregular for o in ons)
    fixed = sum(bool(o.closed_weekdays) for o in ons)
    print(f"無休 never-closes: {never}")
    print(f"不定休 irregular:  {irreg}")
    print(f"fixed weekday closure: {fixed}")
    from collections import Counter
    cw = Counter()
    for o in ons:
        for d in o.closed_weekdays:
            cw[d] += 1
    print("closed-weekday counts (Mon..Sun):", [cw.get(i, 0) for i in range(7)])
    have_open = sum(o.open_min is not None for o in ons)
    have_last = sum(o.effective_last_min is not None for o in ons)
    print(f"have open time: {have_open}/{len(ons)}; have last-entry/close: {have_last}/{len(ons)}")
    opens = sorted(o.open_min for o in ons if o.open_min is not None)
    closes = sorted(o.effective_last_min for o in ons if o.effective_last_min is not None)
    mid = lambda x: x[len(x) // 2]
    print(f"median open {mid(opens)//60}:{mid(opens)%60:02d}; median last-entry {mid(closes)//60}:{mid(closes)%60:02d}")
