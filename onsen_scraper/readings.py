"""Generated hiragana reading (yomi) of an onsen name.

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

Locked decisions (do not re-litigate — see CLAUDE.md):
  * **Auto-generated, no hand-correction.** Some proper-noun / place-name
    readings will be imperfect (e.g. 嬉泉館 → きいずみだて); that is the agreed
    tradeoff for keeping readings in the automated pipeline.
  * **Onsens only** — area names are never given readings.

`name_kana()` imports pykakasi lazily, so importing this module (and
`onsen_scraper`) stays dependency-free until a reading is actually generated —
the same lazy discipline the fetcher/parser use for requests/bs4.
"""
from __future__ import annotations

# Katakana syllable block → hiragana is a fixed −0x60 offset (U+30A1‥U+30F6 →
# U+3041‥U+3096). The prolonged sound mark ー (U+30FC), middle dot ・ (U+30FB)
# and iteration marks (U+30FD/E) sit OUTSIDE this range and are left untouched —
# they have no distinct hiragana form and read the same either way.
_KATAKANA_START = 0x30A1
_KATAKANA_END = 0x30F6
_FOLD_OFFSET = 0x60

_analyzer_cache = None


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
