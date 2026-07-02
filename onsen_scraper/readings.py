"""Generated readings of an onsen name — hiragana yomi (`nameKana`) and Hepburn romaji (`nameRomaji`).

88onsen.com has no furigana/ruby markup and the scraper captures none (verified
by grepping the snapshot's raw_html — zero reading fields anywhere), so the
reading the app sorts by must be **generated** from the kanji `name` by a
morphological analyzer rather than extracted from the source.

`pykakasi` is the analyzer (kanji→kana directly, pure-Python, bundled dict — no
separate dict install, unlike fugashi+UniDic). Its output is then folded to
hiragana: the app sorts onsen lists within a prefecture by `nameKana` with a
plain code-point `localeCompare` and NO `Intl`/locale collation, relying on
hiragana being laid out in gojūon (あいうえお) order in Unicode. Katakana,
romaji, or leftover kanji would break that sort, so the hiragana fold is the
critical part of the contract — see app PR PetrCala/kyuhachi#143.

`name_romaji()` is the Latin-script counterpart: the same pykakasi conversion,
read off the analyzer's `hepburn` field instead of `hira`, joined on word
boundaries and capitalised as a proper noun (別府温泉 → "Beppu Onsen"). The app
shows it beneath the kanji name for non-Japanese users so they can pronounce and
search an onsen — a pronunciation aid, never a translation. Unlike the kana it is
display-only (not a sort key), so it carries no script-normalisation contract; it
is modified Hepburn, macron-free (pykakasi's default — long vowels stay doubled,
e.g. ou/oo). See app PR PetrCala/kyuhachi#183.

Locked decisions (do not re-litigate — see CLAUDE.md):
  * **Auto-generated + curated corrections overlay.** pykakasi authors every
    reading by default; where it misreads a proper noun (e.g. 嬉泉館 →
    きいずみだて instead of きせんかん) the verified reading lives in
    `data/readings_curated.json` and wins via `kana_for()`/`romaji_for()` — the
    same per-id override pattern as `fees.CORRECTIONS`. Every entry records its
    evidence in a `note`. Corrections are curated against sources (official
    sites, tourism pages), never invented.
  * **Onsens only** — area names are never given readings.

`kana_for()`/`romaji_for()` are the id-aware entry points the publisher uses
(backfills and `apply.py` add); `name_kana()`/`name_romaji()` stay analyzer-only.
Both import pykakasi lazily, so importing this module (and `onsen_scraper`)
stays dependency-free until a reading is actually generated — the same lazy
discipline the fetcher/parser use for requests/bs4.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

# Katakana syllable block → hiragana is a fixed −0x60 offset (U+30A1‥U+30F6 →
# U+3041‥U+3096). The prolonged sound mark ー (U+30FC), middle dot ・ (U+30FB)
# and iteration marks (U+30FD/E) sit OUTSIDE this range and are left untouched —
# they have no distinct hiragana form and read the same either way.
_KATAKANA_START = 0x30A1
_KATAKANA_END = 0x30F6
_FOLD_OFFSET = 0x60

_CURATED_PATH = Path(__file__).resolve().parents[1] / "data" / "readings_curated.json"

_analyzer_cache = None
_curated_cache = None


def to_hiragana(text: str) -> str:
    """Fold every katakana syllable in *text* to its hiragana equivalent.

    Pure stdlib (no pykakasi). pykakasi's hiragana mode already returns
    hiragana, but this is applied unconditionally as the contract's hard
    guarantee: anything that reaches the published `nameKana` is hiragana so the
    app's code-point sort stays gojūon-ordered. Non-katakana characters
    (hiragana, the ー mark, ASCII, spaces) pass through unchanged.
    """
    return "".join(
        chr(ord(ch) - _FOLD_OFFSET) if _KATAKANA_START <= ord(ch) <= _KATAKANA_END else ch
        for ch in text
    )


def _analyzer():
    """Return a cached pykakasi converter, imported lazily.

    pykakasi is a real runtime dependency of the reading pipeline (declared in
    pyproject), but importing it eagerly would force the dict load on every
    `import onsen_scraper`. Build it once, on first use."""
    global _analyzer_cache
    if _analyzer_cache is None:
        try:
            import pykakasi
        except ModuleNotFoundError as e:  # pragma: no cover - environment guard
            raise ModuleNotFoundError(
                "pykakasi is required to generate name readings. Install the repo "
                "(`pip install -e .`) or run via `uv run` so the dependency resolves."
            ) from e
        _analyzer_cache = pykakasi.kakasi()
    return _analyzer_cache


def name_kana(name: str | None) -> str | None:
    """Hiragana reading (yomi) of an onsen `name`, or None when none is produced.

    Returns the generated reading normalized to hiragana with surrounding
    whitespace trimmed. Returns ``None`` for an empty/whitespace-only name or
    when the analyzer yields nothing — the app falls back to `name` on null.

    The reading mirrors the source name's internal structure (full-width spaces
    between name parts are kept); only leading/trailing whitespace is stripped.
    """
    if not name or not name.strip():
        return None
    reading = "".join(token["hira"] for token in _analyzer().convert(name))
    reading = to_hiragana(reading).strip()
    return reading or None


def name_romaji(name: str | None) -> str | None:
    """Hepburn romaji of an onsen `name`, capitalised as a proper noun, or None.

    A pronunciation aid the app shows beneath the kanji name for non-Japanese
    users (別府温泉 → "Beppu Onsen"). Built from the same pykakasi conversion as
    `name_kana()`, read off each token's `hepburn` field; the per-token output is
    re-split on whitespace to collapse the analyzer's segmentation (including the
    single space pykakasi emits for a full-width space between name parts) into
    clean word boundaries, and each word is capitalised.

    Returns ``None`` for an empty/whitespace-only name or when the analyzer yields
    nothing — the app shows the kanji alone on null. Display-only, so (unlike
    `name_kana`) there is no script-normalisation contract: it stays modified
    Hepburn (macron-free) as pykakasi produces it.
    """
    if not name or not name.strip():
        return None
    hepburn = " ".join(token["hepburn"] for token in _analyzer().convert(name))
    romaji = " ".join(word[:1].upper() + word[1:] for word in hepburn.split())
    return romaji or None


# --- curated corrections overlay ----------------------------------------------

def curated_readings() -> dict:
    """The `onsens` map of data/readings_curated.json, loaded once.

    Keyed by upstream 88onsen id (string); each entry carries the facility
    `name` it was curated against, the verified `kana` and/or `romaji`, and a
    `note` recording the evidence so future reviews can re-verify."""
    global _curated_cache
    if _curated_cache is None:
        _curated_cache = json.loads(_CURATED_PATH.read_text())["onsens"]
    return _curated_cache


def _curated_entry(onsen_id, name: str | None):
    """The overlay entry for *onsen_id*, or None when absent or stale.

    An entry only applies while the snapshot still carries the exact name it
    was curated against (upstream hids are unstable and names drift); on a
    mismatch it is ignored with a warning so the analyzer fallback — never a
    stale correction — is what gets published."""
    entry = curated_readings().get(str(onsen_id))
    if not entry:
        return None
    if name is None or entry.get("name", "").strip() != name.strip():
        warnings.warn(
            f"readings_curated.json entry {onsen_id} was curated for "
            f"{entry.get('name')!r} but the snapshot name is {name!r} — "
            "ignoring the stale override (analyzer fallback applies); re-verify the entry.",
            stacklevel=3,
        )
        return None
    return entry


def kana_for(onsen_id, name: str | None) -> str | None:
    """Hiragana reading for an onsen, curated override first, else `name_kana`.

    The id-aware entry point the publisher uses (`backfill_name_kana.py` and
    `apply.py` add). The override is folded through `to_hiragana` so a curated
    value can never break the app's gojūon sort contract."""
    entry = _curated_entry(onsen_id, name)
    if entry and entry.get("kana"):
        return to_hiragana(entry["kana"]).strip()
    return name_kana(name)


def romaji_for(onsen_id, name: str | None) -> str | None:
    """Romaji reading for an onsen, curated override first, else `name_romaji`.

    Curated romaji restores the original Latin word for katakana loanwords
    (サムソンホテル → "Samson Hotel", never "Samusonhoteru") and fixes
    mis-segmented proper nouns; otherwise the analyzer's modified Hepburn."""
    entry = _curated_entry(onsen_id, name)
    if entry and entry.get("romaji"):
        return entry["romaji"].strip()
    return name_romaji(name)
