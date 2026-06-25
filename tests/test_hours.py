"""Tests for onsen_scraper.hours — the business-hours → WeeklySchedule parser.

Strings are verbatim from the snapshot (full-width digits/colons and the
parking/locker tail included) so the tests exercise the real, messy source. The
parser is deliberately conservative: it only emits a structured schedule for a
single window with an explicit `無休`/weekday closure, and never invents
"open every day" from a string that simply omits the closed day.
"""
from onsen_scraper.hours import DAYS, parse_hours, parsed_hours_doc


def _sched(opens, closes, closed=()):
    """Expected WeeklySchedule: every day the same window except `closed` days."""
    win = {"opens": opens, "closes": closes}
    return {d: (None if d in closed else dict(win)) for d in DAYS}


# --- structured: open all week (無休) ---------------------------------------- #

def test_muyasumi_single_window_opens_all_days():
    raw = "10：00～21：30（最終受付21：00）\n無休\n・駐車場：なし（近隣駐車場をご利用ください）"
    p = parse_hours(raw)
    assert p.reason == "ok-open-all"
    assert p.closed_days == ()
    assert p.schedule == _sched("10:00", "21:30")


def test_muyasumi_with_irrelevant_parenthetical_still_opens():
    # "臨時休業有" is an occasional temp closure, not a regular weekly one.
    p = parse_hours("9:00～25:00（大浴場～24：00）\n無休（4月,7月,12月臨時休業有）")
    assert p.reason == "ok-open-all"
    assert p.schedule == _sched("09:00", "25:00")


# --- structured: weekday closure -------------------------------------------- #

def test_single_weekday_closed():
    raw = "10：00～22：00\n・水曜休（祝日の場合は営業）\n・駐車場：普通車80台、大型5台"
    p = parse_hours(raw)
    assert p.reason == "ok-weekday-closed"
    assert p.closed_days == ("wednesday",)
    assert p.schedule["wednesday"] is None
    assert p.schedule["tuesday"] == {"opens": "10:00", "closes": "22:00"}
    assert p.notes == "祝日の場合は営業"  # caveat kept for diagnostics; lives on in raw


def test_two_weekdays_closed():
    raw = "9:00～20:30（最終受付20：00）\n火・金曜休\n・駐車場：普通車16台"
    p = parse_hours(raw)
    assert p.closed_days == ("tuesday", "friday")
    assert p.schedule == _sched("09:00", "20:30", closed=("tuesday", "friday"))


def test_mainichi_weekly_prefix_is_handled():
    # "毎週火曜休" — the 毎週 prefix must not be mistaken for an irregular 毎月.
    p = parse_hours("10:00～22:00\n毎週火曜休\n・駐車場：普通車50台")
    assert p.reason == "ok-weekday-closed"
    assert p.closed_days == ("tuesday",)


def test_weekday_range_expands():
    p = parse_hours("10:00～18:00\n月～木曜休")
    assert p.reason == "ok-weekday-closed"
    assert p.closed_days == ("monday", "tuesday", "wednesday", "thursday")
    assert p.schedule["friday"] == {"opens": "10:00", "closes": "18:00"}


# --- raw fallback: cannot place on a fixed weekly grid ---------------------- #

def test_irregular_closure_falls_back():
    p = parse_hours("11:00～15:00（最終受付14:00）\n不定休\n・駐車場：普通車15台")
    assert p.reason == "irregular-closure"
    assert p.schedule is None


def test_nth_weekday_is_not_a_weekly_closure():
    # 第3水曜休 closes only one Wednesday a month — must NOT mark every Wed closed.
    p = parse_hours("10:00～22:00\n第3水曜休（祝日の場合は翌日）")
    assert p.reason == "irregular-closure"
    assert p.schedule is None


def test_day_of_month_closure_falls_back():
    p = parse_hours("7：00～10：30、14：30～22：00\n毎月5,15,25日休")
    # multiple windows is detected first, but either way → no schedule.
    assert p.schedule is None


def test_multiple_windows_falls_back():
    raw = "普通浴　6：30～22：30\n砂湯　8：00～22:30（最終受付 21:30）\n第3水曜休"
    p = parse_hours(raw)
    assert p.reason == "multiple-windows"
    assert p.schedule is None


def test_partial_weekday_closure_falls_back():
    # closed Tue "但し16:00以降入浴可" — not a full-day closure, stay on raw.
    p = parse_hours("10:00～22:00\n火曜休（但し16:00以降入浴可）")
    assert p.reason == "partial-closure"
    assert p.schedule is None


def test_no_closure_info_is_not_assumed_open():
    # The motivating gap: hours present, no stated closed day. We must NOT
    # fabricate open-every-day — 88onsen silence != operator open daily.
    p = parse_hours("10:00～20:00")
    assert p.reason == "no-closure-info"
    assert p.schedule is None


def test_date_only_closure_is_not_a_weekly_pattern():
    # "1/1休" is a single calendar day, not a weekday; no 無休/曜休 → raw fallback.
    p = parse_hours("5：00～21：00\n1/1休\n・駐車場：普通車9台")
    assert p.schedule is None


def test_empty_and_none():
    assert parse_hours(None).reason == "empty"
    assert parse_hours("").reason == "empty"
    assert parse_hours("   ").reason == "empty"
    assert parse_hours(None).schedule is None


# --- projection to the published ParsedHours shape -------------------------- #

def test_parsed_hours_doc_shape():
    raw = "10：00～22：00\n水曜休"
    doc = parsed_hours_doc(raw)
    assert set(doc) == {"raw", "schedule"}
    assert doc["raw"] == raw  # verbatim, app shows it under the grid
    assert doc["schedule"]["wednesday"] is None
    assert set(doc["schedule"]) == set(DAYS)


def test_parsed_hours_doc_none_schedule_keeps_raw():
    # hours present but unparseable (no closure info) → schedule None, raw kept.
    doc = parsed_hours_doc("10:00～20:00")
    assert doc["schedule"] is None
    assert doc["raw"] == "10:00～20:00"


def test_parsed_hours_doc_no_hours_is_24_7():
    # Publish policy: no hours text at all → open 24/7 (every day 00:00–24:00).
    for empty in (None, "", "   "):
        doc = parsed_hours_doc(empty)
        assert doc["raw"] == ""
        assert set(doc["schedule"]) == set(DAYS)
        assert all(s == {"opens": "00:00", "closes": "24:00"}
                   for s in doc["schedule"].values())
    # parse_hours itself stays honest — it does not invent 24/7.
    from onsen_scraper.hours import parse_hours
    assert parse_hours(None).schedule is None
