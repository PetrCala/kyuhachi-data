"""Onsen detail-page scraper for 88onsen.com.

Ported from the original prototype (kyuhachi/_archive/src/scraper). The
selectors are the canonical reference documented in the app repo's
docs/onsen-source-field-audit.md. Reuse the fetcher + parser here; do NOT
import from the app repo's _archive/.

`fees` and `hours` are pure stdlib and eager-imported. The fetcher/parser pull in
`requests`/`beautifulsoup4`, so they are imported lazily (PEP 562) — importing
`onsen_scraper.fees` / `onsen_scraper.hours` (used by the cost-analysis skill,
the publisher backfill, and the hours adapter) never requires the network stack
to be installed. `readings` is eager too: it imports its analyzer (pykakasi)
lazily inside `name_kana` / `name_romaji`, so the module import alone stays
dependency-free.
"""

from onsen_scraper.fees import CORRECTIONS, adult_fee, fee_for
from onsen_scraper.hours import HoursParse, parse_hours, parsed_hours_doc
from onsen_scraper.mapseed import MAP_URL, fetch_map_seed, parse_map_seed
from onsen_scraper.readings import (
    curated_readings,
    kana_for,
    name_kana,
    name_romaji,
    romaji_for,
    to_hiragana,
)

_LAZY = {
    "FetchError": "onsen_scraper.fetcher",
    "fetch_detail_page": "onsen_scraper.fetcher",
    "fetch_url": "onsen_scraper.fetcher",
    "get_detail_url": "onsen_scraper.fetcher",
    "parse_detail_page": "onsen_scraper.parser",
}

__all__ = [
    "adult_fee",
    "fee_for",
    "CORRECTIONS",
    "parse_hours",
    "parsed_hours_doc",
    "HoursParse",
    "MAP_URL",
    "fetch_map_seed",
    "parse_map_seed",
    "curated_readings",
    "kana_for",
    "name_kana",
    "name_romaji",
    "romaji_for",
    "to_hiragana",
    "FetchError",
    "fetch_detail_page",
    "fetch_url",
    "get_detail_url",
    "parse_detail_page",
]


def __getattr__(name):
    if name in _LAZY:
        import importlib

        return getattr(importlib.import_module(_LAZY[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
