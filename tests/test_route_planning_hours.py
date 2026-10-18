"""Tests for the route planners' opening hours.

Two layers: `onsen_model.parse_hours`, the regex over the scraped text (the fallback),
and `curated_hours`, the overlay of data/hours_curated.json that the schedulers now
take their closures from. The regex cases are the strings that were misread on the
trail (水曜日休 as Sunday, 火、金曜休 as Friday only, 第2・第4木曜 as every Thursday).
"""
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "route_planning"))

import curated_hours as ch  # noqa: E402
import plan_octnov  # noqa: E402
from onsen_model import closed_weekdays_from, parse_hours  # noqa: E402

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)


# --- the regex fallback ---------------------------------------------------- #

@pytest.mark.parametrize("raw, expected", [
    ("8:00～19:00（火曜日は8：00～16：00）\n水曜日休", {WED}),            # 曜日's 日 is not Sunday
    ("11:00～14:00\n火、金曜休", {TUE, FRI}),                              # comma list
    ("10：00～18：00（最終受付 17：00）\n火～木曜休", {TUE, WED, THU}),      # range
    ("10：00～20：00 / 水・木曜休", {WED, THU}),
    ("10：00～22：00\n月曜休（祝日の場合は営業。翌火曜休）", {MON}),          # 翌X曜 is conditional
    ("10：00～19：00\n水曜休、第2・第4木曜休", {WED}),                      # monthly is not weekly
    ("11：00～22：00\n木曜及び月末の金曜休", {THU}),
    ("10:00～21:00\n火曜休（祝祭日が火曜の場合は翌日休）", {TUE}),          # 翌日 is not Sunday
    ("6：30～23：45（最終受付 23：00）\n12月中旬に1日休館予定", set()),     # 1日 is not Sunday
    ("10：00～21：00\n7月～10月は水曜休", {WED}),
    ("10:00～20:00\n日・祝休", {SUN}),
    ("10:00～20:00\n土日祝休", {SAT, SUN}),
    ("10:00～20:00\n毎週火曜休", {TUE}),
    ("10:00～20:00\n年中無休", set()),
    ("10:00～20:00\n定休日：木曜", {THU}),
    ("10:00～20:00\n火･水曜休", {TUE, WED}),                                # half-width dot
    ("13：00～18:00\n木曜日(祝日の場合は翌金曜)", {THU}),                  # a bare weekday clause
    ("7：00～20：00\n金曜・元日休", {FRI}),                                 # 元日 is a holiday
    ("10:00～20:00\n祝日休", set()),
])
def test_closed_weekdays_from(raw, expected):
    assert closed_weekdays_from(raw) == expected


def test_parse_hours_keeps_window_and_flags():
    p = parse_hours("10：00～18：00（最終受付 17：00）\n火～木曜休\n不定休あり")
    assert (p["open_min"], p["close_min"], p["last_entry_min"]) == (600, 1080, 1020)
    assert p["closed_weekdays"] == {TUE, WED, THU}
    assert p["irregular"] and not p["never_closes"]


# --- the curated overlay ----------------------------------------------------- #

def _stop(entry: dict) -> dict:
    s = {"id": 0, "open_min": 0, "last_min": 0, "closed_weekdays": [], "irregular": False}
    ch.overlay(s, entry)
    return s


def test_overlay_window_closed_days_and_last_entry_caption():
    s = _stop({"window": ["10:00", "19:00"], "closed": ["wed"], "overrides": {},
               "exceptions": [{"ja": "最終受付 18:00"}, {"ja": "第2・第4木曜も休"}]})
    assert s["closed_weekdays"] == [WED]
    assert (s["open_min"], s["last_min"]) == (600, 1080)
    assert s["wd_hours"]["0"] == [600, 1080] and "2" not in s["wd_hours"]
    assert s["closed_rules"] == [{"kind": "nth_weekday", "nths": [2, 4], "weekdays": [THU]}]
    assert s["hours_source"] == "curated" and not s["never_closes"]


def test_overlay_per_weekday_override():
    s = _stop({"window": ["10:00", "22:00"], "closed": [],
               "overrides": {"tue": ["16:00", "22:00"]}, "exceptions": []})
    assert ch.hours_on(s, date(2026, 10, 13)) == (960, 1320)   # a Tuesday
    assert ch.hours_on(s, date(2026, 10, 14)) == (600, 1320)
    assert s["never_closes"]


def test_nth_weekday_rule():
    s = _stop({"window": ["10:00", "19:00"], "closed": ["wed"], "overrides": {},
               "exceptions": [{"ja": "第2・第4木曜も休"}]})
    assert ch.closed_on(s, date(2026, 10, 22))        # 4th Thursday
    assert not ch.closed_on(s, date(2026, 10, 15))    # 3rd Thursday
    assert ch.closure_reason(s, date(2026, 10, 21)) == "定休日 水曜"


def test_last_weekday_rule():
    s = _stop({"window": ["11:00", "22:00"], "closed": ["thu"], "overrides": {},
               "exceptions": [{"ja": "月末の金曜も休"}]})
    assert ch.closed_on(s, date(2026, 10, 30)) and not ch.closed_on(s, date(2026, 10, 23))


def test_seasonal_weekday_rule():
    s = _stop({"window": ["10:00", "21:00"], "closed": [], "overrides": {},
               "exceptions": [{"ja": "7〜10月は水曜休"}]})
    assert ch.closed_on(s, date(2026, 10, 14)) and not ch.closed_on(s, date(2026, 11, 4))


def test_holiday_rules():
    hol = frozenset({date(2026, 11, 3)})  # a Tuesday
    shift = _stop({"window": ["10:00", "21:00"], "closed": ["tue"], "overrides": {},
                   "exceptions": [{"ja": "定休日が祝日の場合は翌日休"}]})
    assert not ch.closed_on(shift, date(2026, 11, 3), hol)
    assert ch.closed_on(shift, date(2026, 11, 4), hol)
    assert ch.closed_on(shift, date(2026, 11, 10), hol)
    open_hol = _stop({"window": ["10:00", "21:00"], "closed": ["tue"], "overrides": {},
                      "exceptions": [{"ja": "祝日は営業"}]})
    assert not ch.closed_on(open_hol, date(2026, 11, 3), hol)
    assert not ch.closed_on(open_hol, date(2026, 11, 4), hol)


def test_irregular_from_status_or_caption():
    assert _stop({"window": ["15:00", "20:00"], "closed": [], "status": "irregular",
                  "exceptions": []})["irregular"]
    assert _stop({"window": ["15:00", "20:00"], "closed": [],
                  "exceptions": [{"ja": "不定休あり"}]})["irregular"]


def test_curated_file_covers_every_route_stop():
    import json
    stops = json.loads((ROOT / "route_planning" / "handdrawn_loop_analysis.json").read_text())["stops"]
    assert ch.apply_curated(stops) == len(stops)
    assert all(s["hours_source"] == "curated" for s in stops)


# --- the planner ------------------------------------------------------------ #

def test_default_plan_still_makes_the_challenge():
    t = plan_octnov.plan()["totals"]
    assert t["visited_ge_88"] and t["all7"] and t["start_km"] == 0


def test_plan_from_a_position_on_the_line():
    start = plan_octnov.Start(date=date(2026, 10, 13), km=195.1, next_order=23,
                              walking_day=9, prefs_done=("鹿児島", "宮崎"))
    p = plan_octnov.plan(start=start)
    orders = [e["order"] for d in p["days"] for e in d["events"]]
    assert orders[0] == 23 and min(orders) == 23 and orders[-1] == 119
    assert p["days"][0]["date"] == date(2026, 10, 13)
    assert p["days"][0]["start_km"] == 195.1 and p["totals"]["route_km"] == pytest.approx(1205.0 - 195.1, abs=0.2)
    assert p["totals"]["all7"]  # 長崎 is still a linchpin; 鹿児島/宮崎 were handed in
