"""Tests for onsen_scraper.readings — the generated readings (`nameKana` hiragana
yomi, `nameRomaji` Hepburn) the catalog publisher writes for the app: the kana is
the gojūon sort key, the romaji a pronunciation aid for non-Japanese users.

The readings are analyzer-generated with a curated corrections overlay
(data/readings_curated.json): `kana_for`/`romaji_for` prefer a verified per-id
override and fall back to pykakasi. Tested here: the fold contract, the analyzer
fallback, the overlay winning, its staleness guard, and the publisher plans
carrying the overlay.

`to_hiragana` is pure stdlib and always tested. The analyzer-backed `name_kana` /
`name_romaji` and the publisher plans need pykakasi (a declared dependency); those
tests `importorskip` it so a bare environment still runs the fold tests. Offline
throughout — no network, no auth, no writes.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

from onsen_scraper.readings import (
    curated_readings,
    kana_for,
    name_kana,
    name_romaji,
    romaji_for,
    to_hiragana,
)

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


# --- name_romaji: analyzer-backed romaji generation --------------------------

def test_name_romaji_matches_the_contract_examples():
    pytest.importorskip("pykakasi")
    # The example called out in the contract / app PR #183: Title-cased Hepburn.
    assert name_romaji("別府温泉") == "Beppu Onsen"
    assert name_romaji("由布院温泉") == "Yufuin Onsen"


def test_name_romaji_none_for_empty_input():
    assert name_romaji(None) is None
    assert name_romaji("") is None
    assert name_romaji("   　 ") is None


def test_name_romaji_collapses_segmentation_and_trims():
    pytest.importorskip("pykakasi")
    # A full-width space between name parts makes pykakasi emit a stray space token;
    # the output must collapse to single-spaced words with no leading/trailing space.
    romaji = name_romaji("武雄温泉　元湯")
    assert romaji is not None
    assert romaji == romaji.strip()
    assert "  " not in romaji


def test_name_romaji_capitalises_each_word():
    pytest.importorskip("pykakasi")
    # Every space-separated word starts capitalised so the reading reads as a proper
    # noun (the kana, by contrast, is lowercase script with no capitalisation).
    for name in ("別府温泉", "由布院温泉", "黒川温泉", "嬉野温泉"):
        romaji = name_romaji(name)
        assert romaji is not None
        for word in romaji.split(" "):
            assert word[:1] == word[:1].upper(), romaji


def test_name_romaji_unpads_parentheses():
    pytest.importorskip("pykakasi")
    # pykakasi emits （）/「」 as standalone ASCII-paren tokens; the space-join
    # must not pad them ("( Kinkonkan )"). The reading itself is untouched.
    for name in ("おたっしゃん湯（脇浜温泉浴場）", "温泉付貸別荘「きんこんかん」"):
        romaji = name_romaji(name)
        assert romaji is not None
        assert "( " not in romaji and " )" not in romaji, romaji
        assert "(" in romaji and romaji.endswith(")"), romaji


def test_name_romaji_maps_middle_dot_to_word_gap():
    pytest.importorskip("pykakasi")
    # ・ has no Latin form; it must become a plain single space, never leak into
    # the Latin line (the kana keeps it — the sort key is untouched by this).
    romaji = name_romaji("瀬音・湯音の宿　浮羽")
    assert romaji is not None
    assert "・" not in romaji and "  " not in romaji, romaji
    assert romaji.startswith("Seoto Yuoto"), romaji


# --- curated corrections overlay (data/readings_curated.json) ----------------

def _snapshot_name(oid: int) -> str:
    con = sqlite3.connect(f"file:{REPO / 'data' / 'snapshot.db'}?mode=ro", uri=True)
    try:
        row = con.execute("select facility_name from onsens where id=?", (oid,)).fetchone()
    finally:
        con.close()
    assert row, f"onsen {oid} not in snapshot"
    return row[0]


def test_curated_entries_are_wellformed_and_match_snapshot():
    # Every entry: a digit key that is a snapshot onsen, a `name` that still
    # matches the snapshot (the staleness guard the resolver enforces), a `note`
    # recording the evidence, and at least one of kana/romaji. A curated kana
    # must honor the hiragana contract: fold-idempotent, no kanji.
    entries = curated_readings()
    assert entries, "overlay file exists but has no entries"
    for key, entry in entries.items():
        assert key.isdigit(), key
        assert entry.get("note"), f"{key}: every correction records its evidence"
        assert entry.get("kana") or entry.get("romaji"), key
        assert _snapshot_name(int(key)).strip() == entry["name"].strip(), (
            f"{key}: snapshot name drifted from the curated entry — re-verify it")
        kana = entry.get("kana")
        if kana:
            assert kana == to_hiragana(kana), f"{key}: curated kana must be hiragana"
            assert not any(0x4E00 <= ord(ch) <= 0x9FFF for ch in kana), (
                f"{key}: kanji left in curated kana")


def test_overlay_wins_and_analyzer_remains_the_fallback():
    pytest.importorskip("pykakasi")
    # The override wins for every curated entry...
    for key, entry in curated_readings().items():
        if entry.get("kana"):
            assert kana_for(int(key), entry["name"]) == entry["kana"].strip()
        if entry.get("romaji"):
            assert romaji_for(int(key), entry["name"]) == entry["romaji"].strip()
    # ...and an uncorrected onsen still gets the analyzer reading, byte-for-byte.
    assert "1" not in curated_readings()
    assert kana_for(1, "博多湯") == name_kana("博多湯") == "はかたゆ"
    assert romaji_for(1, "博多湯") == name_romaji("博多湯") == "Hakata Yu"


def test_confirmed_misreads_are_corrected():
    pytest.importorskip("pykakasi")
    # The review's seed examples, verified against official/tourism sources.
    assert kana_for(164, _snapshot_name(164)) == "きどうあん"            # 喜道庵
    assert kana_for(12, _snapshot_name(12)) == "きせんかん"              # 嬉泉館
    assert kana_for(7, _snapshot_name(7)) == "きはだびじん　みどりのゆ"  # 貴肌美人　緑の湯
    assert kana_for(32, _snapshot_name(32)) == "かんなわむしゆ"          # 鉄輪むし湯
    # Katakana loanwords romanize back to the original Latin words.
    assert romaji_for(19, _snapshot_name(19)) == "Samson Hotel Nagomi no Yu"
    assert romaji_for(116, _snapshot_name(116)) == "Sakurajima Seaside Hotel"


def test_stale_override_is_ignored_with_warning():
    pytest.importorskip("pykakasi")
    # Upstream hids are unstable: if the snapshot name no longer matches what the
    # entry was curated against, the override must NOT apply.
    with pytest.warns(UserWarning, match="stale"):
        assert kana_for(12, "全く別の施設名") == name_kana("全く別の施設名")


def test_backfill_plans_reflect_the_overlay():
    pytest.importorskip("pykakasi")
    import backfill_name_kana as bk  # noqa: E402  (publisher/ is non-package)
    import backfill_name_romaji as br  # noqa: E402

    kana_plan = {oid: kana for oid, _kid, _name, kana in bk.build_plan()}
    romaji_plan = {oid: romaji for oid, _kid, _name, romaji in br.build_plan()}
    for key, entry in curated_readings().items():
        if entry.get("kana"):
            assert kana_plan[int(key)] == entry["kana"].strip()
        if entry.get("romaji"):
            assert romaji_plan[int(key)] == entry["romaji"].strip()


# --- publisher backfill plans (offline, over the snapshot) -------------------

def test_backfill_plan_over_snapshot():
    pytest.importorskip("pykakasi")
    import backfill_name_kana as bf  # noqa: E402  (publisher/ is non-package)

    plan = bf.build_plan()
    # One row per snapshot onsen — derive the expected set from the baseline rather
    # than hard-coding a count, so a `promote` that grows the snapshot doesn't break
    # this *post*-promote check (the publish job runs it after promote).
    import sqlite3
    con = sqlite3.connect(f"file:{bf.SNAPSHOT_DB}?mode=ro", uri=True)
    snap_ids = {r[0] for r in con.execute("select id from onsens")}
    con.close()
    assert {p[0] for p in plan} == snap_ids
    # Every row is (id, kid, name, kana); the snapshot has a name for every onsen, so
    # every onsen should produce a non-null hiragana reading.
    assert all(kana for _oid, _kid, _name, kana in plan)
    for _oid, _kid, _name, kana in plan:
        assert all(not (0x30A1 <= ord(ch) <= 0x30F6) for ch in kana), kana


def test_backfill_romaji_plan_over_snapshot():
    pytest.importorskip("pykakasi")
    import backfill_name_romaji as bf  # noqa: E402  (publisher/ is non-package)

    plan = bf.build_plan()
    import sqlite3
    con = sqlite3.connect(f"file:{bf.SNAPSHOT_DB}?mode=ro", uri=True)
    snap_ids = {r[0] for r in con.execute("select id from onsens")}
    con.close()
    assert {p[0] for p in plan} == snap_ids
    # Every row is (id, kid, name, romaji); the snapshot has a name for every onsen,
    # so every onsen should produce a non-null, trimmed, single-spaced romaji.
    assert all(romaji for _oid, _kid, _name, romaji in plan)
    for _oid, _kid, _name, romaji in plan:
        assert romaji == romaji.strip() and "  " not in romaji, romaji
