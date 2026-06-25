"""Tests for onsen_scraper.readings — the generated hiragana reading (`nameKana`)
the catalog publisher writes for reading-based (gojūon) sorting in the app.

`to_hiragana` is pure stdlib and always tested. The analyzer-backed `name_kana`
and the publisher plan need pykakasi (a declared dependency); those tests
`importorskip` it so a bare environment still runs the fold tests. Offline
throughout — no network, no auth, no writes.
"""
import sys
from pathlib import Path

import pytest

from onsen_scraper.readings import name_kana, to_hiragana

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "publisher"))


# --- to_hiragana: the pure-stdlib hiragana fold (the contract guarantee) ------

def test_to_hiragana_folds_katakana():
    assert to_hiragana("カタカナ") == "かたかな"
    assert to_hiragana("スパ") == "すぱ"


def test_to_hiragana_leaves_hiragana_and_ascii_untouched():
    assert to_hiragana("べっぷおんせん") == "べっぷおんせん"
    assert to_hiragana("resort ABC") == "resort ABC"


def test_to_hiragana_keeps_prolonged_mark_and_spaces():
    # ー (U+30FC) has no hiragana form and must survive the fold; the gojūon sort
    # treats it consistently either way. Full-width spaces are preserved too.
    assert to_hiragana("サウナー") == "さうなー"
    assert to_hiragana("うみ　の　ゆ") == "うみ　の　ゆ"


def test_to_hiragana_folds_vu():
    # ヴ (U+30F4) → ゔ (U+3094); a valid hiragana, must fold like the rest.
    assert to_hiragana("ヴ") == "ゔ"


# --- name_kana: analyzer-backed reading generation ---------------------------

def test_name_kana_matches_the_contract_examples():
    pytest.importorskip("pykakasi")
    # The two examples called out in the contract / PR description for spot-checks.
    assert name_kana("別府温泉") == "べっぷおんせん"
    assert name_kana("由布院温泉") == "ゆふいんおんせん"


def test_name_kana_output_is_pure_hiragana_for_kanji_names():
    pytest.importorskip("pykakasi")
    # The hard contract: the published reading must be hiragana so the app's
    # code-point localeCompare yields gojūon order. No katakana may leak through.
    for name in ("博多湯", "由布院温泉", "天然の湯あおき温泉", "鶴霊泉"):
        kana = name_kana(name)
        assert kana is not None
        assert all(not (0x30A1 <= ord(ch) <= 0x30F6) for ch in kana), kana


def test_name_kana_none_for_empty_input():
    assert name_kana(None) is None
    assert name_kana("") is None
    assert name_kana("   　 ") is None


def test_name_kana_strips_surrounding_whitespace():
    pytest.importorskip("pykakasi")
    # Snapshot names carry trailing full-width spaces (e.g. "元祖　元湯　"); the
    # reading is trimmed at the ends but keeps internal structure.
    kana = name_kana("元祖　元湯　")
    assert kana is not None
    assert kana == kana.strip()
    assert not kana.endswith("　")


# --- publisher backfill plan (offline, over the snapshot) --------------------

def test_backfill_plan_over_snapshot():
    pytest.importorskip("pykakasi")
    import backfill_name_kana as bf  # noqa: E402  (publisher/ is non-package)

    plan = bf.build_plan()
    assert len(plan) == 148
    # Every row is (id, kid, name, kana); the snapshot has a name for all 148, so
    # every onsen should produce a non-null hiragana reading.
    assert all(kana for _oid, _kid, _name, kana in plan)
    for _oid, _kid, _name, kana in plan:
        assert all(not (0x30A1 <= ord(ch) <= 0x30F6) for ch in kana), kana
