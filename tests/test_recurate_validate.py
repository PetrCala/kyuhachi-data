"""Tests for the recurate-hours curated-entry validator (the `set` write gate).

The validator mirrors the publish-side invariants (tests/test_publish_schedule.py)
and is the only thing standing between a malformed model-refreshed entry and
data/hours_curated.json — so the extended shapes (window lists, rule twins,
lastEntry) get their own coverage. The script lives in a non-package dir; same
sys.path trick as test_catalog_sync."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / ".claude/skills/recurate-hours"))

import recurate_hours as rh  # noqa: E402


def _entry(**kw):
    base = {"publish": True, "status": "structured", "window": ["10:00", "22:00"],
            "closed": [], "overrides": {}, "confidence": "high", "note": "",
            "exceptions": []}
    base.update(kw)
    return base


def test_current_curated_file_validates():
    # The Phase-0 contract: extending the schema must not invalidate a single
    # existing entry — the data is untouched until the per-phase flips.
    onsens = json.loads((REPO / "data" / "hours_curated.json").read_text())["onsens"]
    errs = [m for hid, e in onsens.items() for m in rh.validate_entry(hid, e)]
    assert errs == []


def test_valid_single_window_entry_passes():
    assert rh.validate_entry("1", _entry()) == []


def test_valid_multi_window_entry_passes():
    e = _entry(status="multi-window",
               window=[["07:00", "10:30"], ["14:30", "22:00"]],
               overrides={"mon": [["08:30", "11:00"], ["13:00", "20:00"]]})
    assert rh.validate_entry("38", e) == []


def test_windows_must_be_wellformed():
    # not chronological
    assert rh.validate_entry("1", _entry(window=[["14:00", "22:00"], ["07:00", "10:00"]]))
    # overlapping
    assert rh.validate_entry("1", _entry(window=[["07:00", "12:00"], ["11:00", "22:00"]]))
    # opens after closes
    assert rh.validate_entry("1", _entry(window=["22:00", "10:00"]))
    # past-midnight closes are legal (25:00 = 1 AM)
    assert rh.validate_entry("1", _entry(window=["10:00", "25:00"])) == []


def test_rule_shapes():
    ok = _entry(status="monthly", exceptions=[
        {"en": "Closed the 4th Thursday each month", "ja": "毎月第4木曜休",
         "rule": {"kind": "monthlyWeekday", "weeks": [4], "weekday": "thursday",
                  "holidayPolicy": "nextDay"}}])
    assert rh.validate_entry("32", ok) == []
    ok_day = _entry(status="monthly", exceptions=[
        {"en": "Closed the 5th, 15th & 25th each month", "ja": "毎月5・15・25日休",
         "rule": {"kind": "monthlyDay", "days": [5, 15, 25]}}])
    assert rh.validate_entry("38", ok_day) == []
    # unknown kind / bad week / exceptMonths+onlyMonths together all refuse
    assert rh.validate_entry("1", _entry(exceptions=[
        {"en": "x", "ja": "y", "rule": {"kind": "weekly"}}]))
    assert rh.validate_entry("1", _entry(exceptions=[
        {"en": "x", "ja": "y",
         "rule": {"kind": "monthlyWeekday", "weeks": [0], "weekday": "monday"}}]))
    assert rh.validate_entry("1", _entry(exceptions=[
        {"en": "x", "ja": "y",
         "rule": {"kind": "monthlyWeekday", "weeks": [1], "weekday": "monday",
                  "exceptMonths": [1], "onlyMonths": [2]}}]))


def test_published_monthly_and_irregular_require_their_rule():
    # A published grid whose status implies a caveat must carry the machine-
    # readable twin — a caption alone is invisible to computing consumers.
    no_rule = _entry(status="monthly", exceptions=[
        {"en": "Closed the 4th Thursday each month", "ja": "毎月第4木曜休"}])
    assert any("monthly" in m for m in rh.validate_entry("32", no_rule))
    irr = _entry(status="irregular", exceptions=[
        {"en": "Irregular closing days — confirm before visiting",
         "ja": "不定休 — 事前にご確認ください"}])
    assert any("irregular" in m for m in rh.validate_entry("10", irr))
    irr["exceptions"][0]["rule"] = {"kind": "irregular"}
    assert rh.validate_entry("10", irr) == []


def test_unpublished_entries_need_no_rule():
    # Pre-flip reality: a publish:false monthly entry (caption only) stays valid —
    # the status↔rule invariant bites only once the grid publishes.
    e = _entry(publish=False, status="monthly", exceptions=[
        {"en": "Closed the 4th Thursday each month", "ja": "毎月第4木曜休"}])
    assert rh.validate_entry("32", e) == []


def test_last_entry_shape():
    assert rh.validate_entry("1", _entry(lastEntry="21:00")) == []
    assert rh.validate_entry("1", _entry(lastEntry="9pm"))
    assert rh.validate_entry("1", _entry(lastEntry=2100))
