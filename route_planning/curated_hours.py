#!/usr/bin/env python3
"""Curated opening hours for the planners: data/hours_curated.json → stop fields.

Why this exists. The planners took opening hours from `onsen_model.parse_hours`, a
regex over the scraped `business_hours` text, and that regex read 水曜日休 as "closed
Sunday" (the 日 of 曜日), did the same with 祝日 and 翌日休, dropped the first day of
火、金曜休 and 火〜木曜休, and turned the monthly 第2・第4木曜 into a weekly closure.
Checked on the trail on 2026-10-13: 15 of the 119 route stops carried a wrong closed
day. The regex is fixed, but it will never know what the text does not say.

`data/hours_curated.json` is the hand-reviewed schedule the app publishes, keyed by
the upstream hid (what a route stop carries as `id`). It says more than one window
plus closed days: per-weekday overrides (火曜は16:00以降), the 最終受付 cutoff, and the
rule behind each caption (第2・第4木曜, 月末の金曜, 7〜10月は水曜休, 祝日は翌日休). This
module overlays all of that onto a planner stop and answers the two questions every
scheduler here asks: is this stop closed on this date, and what are its hours that
day. Read-only against the curated file; the regex parse stays as the fallback for
an onsen the file does not know.

Stop fields written (planner dicts and `onsen_model.Onsen` alike):
  closed_weekdays  [int]            Python weekday(), 0 = Monday
  wd_hours         {"0".."6": [open_min, last_min]}   only the days it opens
  closed_rules     [{"kind": ...}]  nth_weekday / last_weekday / seasonal_weekday /
                                    holiday_shift / open_on_holidays
  open_min, last_min                the base window (what the old fields meant)
  irregular, never_closes, hours_source ("curated"), confidence
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import config

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS_JP = "月火水木金土日"
_FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")


def _to_min(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)


def _wds(token: str) -> list[int]:
    return [WEEKDAYS_JP.index(c) for c in token if c in WEEKDAYS_JP]


def load_curated(path: Path = config.CURATED_HOURS) -> dict[int, dict]:
    """hid -> curated entry (window, closed, overrides, exceptions, status, ...)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {int(k): v for k, v in data["onsens"].items()}


def rules_from_captions(entry: dict) -> list[dict]:
    """The closure rules behind the Japanese captions, as data the schedulers can apply.

    Parenthesised qualifiers are dropped first: 第4火曜休（隔月）, 毎月第3水曜休（3・8月は
    除く）. Treating those as plain monthly closures is the conservative reading.
    """
    rules: list[dict] = []
    for e in entry.get("exceptions") or []:
        ja = re.sub(r"[（(][^）)]*[）)]", "", (e.get("ja") or "")).translate(_FULLWIDTH)
        # 毎月第2・第4火・水曜休 / 第2・第4木曜も休 / 第4火曜休
        for m in re.finditer(r"第([0-9・第、,]*[0-9])([月火水木金土日](?:・[月火水木金土日])*)曜", ja):
            nths = sorted({int(d) for d in re.findall(r"[0-9]", m.group(1))})
            rules.append({"kind": "nth_weekday", "nths": nths, "weekdays": _wds(m.group(2))})
        # 月末の金曜も休 / 最終金曜休
        for m in re.finditer(r"(?:月末|最終)の?([月火水木金土日])曜", ja):
            rules.append({"kind": "last_weekday", "weekdays": _wds(m.group(1))})
        # 7〜10月は水曜休
        for m in re.finditer(r"([0-9]{1,2})[〜～~\-]([0-9]{1,2})月は([月火水木金土日](?:・[月火水木金土日])*)曜休", ja):
            a, b = int(m.group(1)), int(m.group(2))
            months = list(range(a, b + 1)) if a <= b else list(range(a, 13)) + list(range(1, b + 1))
            rules.append({"kind": "seasonal_weekday", "months": months, "weekdays": _wds(m.group(3))})
        # 定休日が祝日の場合は翌日休 / 月曜が祝日の場合は営業し翌火曜休
        if "祝" in ja and "翌" in ja and "休" in ja:
            rules.append({"kind": "holiday_shift"})
        # 祝日は営業 / 祝日も営業 / 祝日・毎月26日は営業
        elif re.search(r"祝日(?:・[^はも]*)?[はも]営業", ja):
            rules.append({"kind": "open_on_holidays"})
    return rules


def last_entry_min(entry: dict) -> int | None:
    """The 最終受付 cutoff: the structured field when published, else its caption."""
    if entry.get("lastEntry"):
        return _to_min(entry["lastEntry"])
    for e in entry.get("exceptions") or []:
        m = re.search(r"最終受付\s*([0-9０-９]{1,2}[:：][0-9０-９]{2})", e.get("ja") or "")
        if m:
            return _to_min(m.group(1).translate(_FULLWIDTH).replace("：", ":"))
    return None


def overlay(stop: dict, entry: dict) -> None:
    """Write the curated hours onto a planner stop dict, in place."""
    closed = sorted({DAY_KEYS.index(d) for d in entry.get("closed") or [] if d in DAY_KEYS})
    window = entry.get("window") or None
    overrides = entry.get("overrides") or {}
    le = last_entry_min(entry)
    wd_hours: dict[str, list[int]] = {}
    for i, key in enumerate(DAY_KEYS):
        if i in closed:
            continue
        win = overrides.get(key) or window
        if not win:
            continue
        if isinstance(win[0], list):  # split sessions: the first window is the one you reach first
            win = win[0]
        o, c = _to_min(win[0]), _to_min(win[1])
        wd_hours[str(i)] = [o, min(le, c) if le is not None else c]
    rules = rules_from_captions(entry)
    irregular = entry.get("status") == "irregular" or any(
        "不定休" in (e.get("ja") or "") for e in entry.get("exceptions") or [])
    stop["closed_weekdays"] = closed
    stop["wd_hours"] = wd_hours
    stop["closed_rules"] = rules
    stop["irregular"] = bool(irregular)
    stop["never_closes"] = not closed and not rules and not irregular
    if window:
        base = window[0] if isinstance(window[0], list) else window
        o, c = _to_min(base[0]), _to_min(base[1])
        stop["open_min"] = o
        stop["last_min"] = min(le, c) if le is not None else c
    stop["hours_source"] = "curated"
    stop["confidence"] = entry.get("confidence")


def apply_curated(stops: list[dict], curated: dict[int, dict] | None = None) -> int:
    """Overlay every stop the curated file knows (keyed by `id` = hid). Returns the count."""
    curated = load_curated() if curated is None else curated
    n = 0
    for s in stops:
        e = curated.get(int(s["id"]))
        if e:
            overlay(s, e)
            n += 1
    return n


def _nth_of_month(d: date) -> int:
    return (d.day - 1) // 7 + 1


def _is_last_of_month(d: date) -> bool:
    return (d + timedelta(days=7)).month != d.month


def closure_reason(stop: dict, d: date, holidays: frozenset[date] = config.HOLIDAYS) -> str | None:
    """Why this stop is closed on `d`, in the plan's own words; None when it is open."""
    wd = d.weekday()
    closed_wd = set(stop.get("closed_weekdays") or [])
    rules = stop.get("closed_rules") or []
    kinds = {r["kind"] for r in rules}
    weekday_closed = wd in closed_wd
    if d in holidays and ("open_on_holidays" in kinds or "holiday_shift" in kinds):
        weekday_closed = False
    if "holiday_shift" in kinds:
        prev = d - timedelta(days=1)
        if prev in holidays and prev.weekday() in closed_wd:
            return f"祝日の翌日休 ({WEEKDAYS_JP[prev.weekday()]}曜が祝日)"
    if weekday_closed:
        return "定休日 " + "".join(WEEKDAYS_JP[i] for i in sorted(closed_wd)) + "曜"
    for r in rules:
        if wd not in r.get("weekdays", ()):
            continue
        if r["kind"] == "nth_weekday" and _nth_of_month(d) in r["nths"]:
            return "第" + "・".join(str(n) for n in r["nths"]) + WEEKDAYS_JP[wd] + "曜休"
        if r["kind"] == "last_weekday" and _is_last_of_month(d):
            return f"月末の{WEEKDAYS_JP[wd]}曜休"
        if r["kind"] == "seasonal_weekday" and d.month in r["months"]:
            return f"{r['months'][0]}〜{r['months'][-1]}月は{WEEKDAYS_JP[wd]}曜休"
    return None


def closed_on(stop: dict, d: date, holidays: frozenset[date] = config.HOLIDAYS) -> bool:
    return closure_reason(stop, d, holidays) is not None


def hours_on(stop: dict, d: date) -> tuple[int | None, int | None]:
    """(open_min, last_min) for this date: the weekday's own window when curated, else the base."""
    w = (stop.get("wd_hours") or {}).get(str(d.weekday()))
    if w:
        return w[0], w[1]
    return stop.get("open_min"), stop.get("last_min")
