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

# Fixed weekly closures live in a clause that mentions 休 (休 / 定休日 / 休館 / お休み).
# Inside it, weekdays come as a chain (火、金曜 / 火〜木曜 / 水・木曜 / 土日祝休) that
# ends in 曜, or in 休 (optionally via 祝) when it is not the 日 of 曜日, 翌日 or 1日.
# A chain led by 翌 (翌火曜休), a digit (第2・第4木曜), 月末 or 月初 is a conditional or
# monthly closure, not a weekly one, and is left to the curated captions; 元日 and
# 祝日 are holidays, not Sundays. A clause that is nothing but a weekday chain
# (木曜日(祝日の場合は翌金曜)) is a closure too, 休 or not.
_CLAUSE_SPLIT_RE = re.compile(r"[\n。（）()※/｜|]")
_WD_SEP = r"[・･、,，～〜~\-]"
_WD_CHAIN = rf"[月火水木金土日](?:{_WD_SEP}?[月火水木金土日])*"
_CLOSED_CHAIN_RE = re.compile(
    rf"(?P<chain>{_WD_CHAIN})(?:曜|(?:[・･、,，]?祝(?:祭)?日?)?(?=休))")
_BARE_CHAIN_RE = re.compile(rf"^(?:毎週)?(?P<chain>{_WD_CHAIN})曜日?$")
_NOT_WEEKLY_RE = re.compile(r"(?:翌|元|祝|祭|[0-9０-９]|第[0-9０-９・第、,]*|月末の?|月初の?|曜)$")
_WD_RANGE_RE = re.compile(r"([月火水木金土日])[～〜~\-]([月火水木金土日])")
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
    never_closes: bool = False         # 無休 (no closing day; NOT "open 24 h")
    irregular: bool = False            # 不定休 (unplannable)
    # Curated extras (curated_hours.overlay); empty when only the regex parse is known.
    wd_hours: dict = field(default_factory=dict)     # {"0".."6": [open_min, last_min]}
    closed_rules: list = field(default_factory=list)  # nth_weekday / last_weekday / ...
    hours_source: str = "regex"

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

    out["closed_weekdays"] = closed_weekdays_from(raw)

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


def closed_weekdays_from(raw: str) -> set[int]:
    """Fixed weekly closures named in `raw` (Python weekday() indices)."""
    out: set[int] = set()
    for clause in _CLAUSE_SPLIT_RE.split(raw or ""):
        clause = clause.strip()
        bare = _BARE_CHAIN_RE.match(clause)
        if bare is None and ("休" not in clause or "無休" in clause):
            continue
        for m in ([bare] if bare else _CLOSED_CHAIN_RE.finditer(clause)):
            if _NOT_WEEKLY_RE.search(clause[: m.start()]):
                continue
            chain = m.group("chain")
            for a, b in _WD_RANGE_RE.findall(chain):
                i, j = WEEKDAYS.index(a), WEEKDAYS.index(b)
                out.update(range(i, j + 1) if i <= j else list(range(i, 7)) + list(range(0, j + 1)))
            out.update(WEEKDAYS.index(c) for c in chain if c in WEEKDAYS)
    return out


def short_pref(pref: str) -> str:
    return (pref or "").replace("県", "").replace("府", "")


def load_onsens(include_offshore: bool = False, curated: bool = True) -> list[Onsen]:
    """Every onsen in the snapshot DB, with the curated hours overlaid (see curated_hours)."""
    from curated_hours import load_curated, overlay  # local: curated_hours imports config only

    known = load_curated() if curated else {}
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
        if o.id in known:
            d: dict = {}
            overlay(d, known[o.id])
            o.open_min, o.last_entry_min = d["open_min"], d["last_min"]
            o.close_min = d["last_min"] if o.close_min is None else max(o.close_min, d["last_min"])
            o.closed_weekdays = set(d["closed_weekdays"])
            o.never_closes, o.irregular = d["never_closes"], d["irregular"]
            o.wd_hours, o.closed_rules, o.hours_source = d["wd_hours"], d["closed_rules"], "curated"
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
