"""Tests for publishing structured businessHours.schedule.

Covers the Firestore typed-value encoder (`sched_val`) and the offline backfill
plan built from the snapshot DB. Fully offline — no network, no auth, no writes.
`apply.py` / `backfill_schedule.py` live in non-package dirs, so we add them to
sys.path (same trick as test_catalog_diff_soft_removal)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "publisher"))

import apply  # noqa: E402  (publisher/apply.py — the surgical publisher)
import backfill_schedule as bf  # noqa: E402
from onsen_scraper.hours import DAYS, parsed_hours_doc  # noqa: E402


def test_sched_val_null_for_unstructured():
    assert apply.sched_val(None) == {"nullValue": None}


def test_sched_val_open_all_week():
    sched = parsed_hours_doc("10:00～22:00\n無休")["schedule"]
    val = apply.sched_val(sched)
    fields = val["mapValue"]["fields"]
    assert set(fields) == set(DAYS)
    assert fields["monday"] == {"mapValue": {"fields": {
        "opens": {"stringValue": "10:00"}, "closes": {"stringValue": "22:00"}}}}


def test_sched_val_weekday_closed_encodes_null_day():
    sched = parsed_hours_doc("10:00～22:00\n火曜休")["schedule"]
    fields = apply.sched_val(sched)["mapValue"]["fields"]
    assert fields["tuesday"] == {"nullValue": None}          # closed → null
    assert fields["monday"]["mapValue"]["fields"]["opens"]["stringValue"] == "10:00"


def test_apply_and_backfill_encoders_agree():
    # The encoder is duplicated across the two publisher scripts (DRY later — see
    # roadmap D); guard that they stay byte-identical in output.
    sched = parsed_hours_doc("9:00～20:30\n火・金曜休")["schedule"]
    assert apply.sched_val(sched) == bf.sched_val(sched)


def test_backfill_plan_over_snapshot():
    plan = bf.build_plan()
    assert len(plan) == 148
    structured = [p for p in plan if p[3] is not None]
    # The snapshot yields a structured schedule for the open-all + weekday-closed
    # onsens (see hours_report); the rest stay raw-only. Sanity-bound it.
    assert 40 <= len(structured) <= 80
    # Every structured schedule encodes cleanly to a 7-day Firestore map.
    for _oid, _kid, _name, sched, _reason in structured:
        fields = bf.sched_val(sched)["mapValue"]["fields"]
        assert set(fields) == set(DAYS)
