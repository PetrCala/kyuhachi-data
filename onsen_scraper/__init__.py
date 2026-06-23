"""Onsen detail-page scraper for 88onsen.com.

Ported from the original prototype (kyuhachi/_archive/src/scraper). The
selectors are the canonical reference documented in the app repo's
docs/onsen-source-field-audit.md. Reuse the fetcher + parser here; do NOT
import from the app repo's _archive/.

`fees` is pure stdlib and eager-imported. The fetcher/parser pull in
`requests`/`beautifulsoup4`, so they are imported lazily (PEP 562) — importing
`onsen_scraper.fees` (used by the cost-analysis skill and the publisher backfill)
never requires the network stack to be installed.
"""

from onsen_scraper.fees import CORRECTIONS, adult_fee, fee_for

_LAZY = {
    "FetchError": "onsen_scraper.fetcher",
    "fetch_detail_page": "onsen_scraper.fetcher",
    "get_detail_url": "onsen_scraper.fetcher",
    "parse_detail_page": "onsen_scraper.parser",
}

__all__ = [
    "adult_fee",
    "fee_for",
    "CORRECTIONS",
    "FetchError",
    "fetch_detail_page",
    "get_detail_url",
    "parse_detail_page",
]


def __getattr__(name):
    if name in _LAZY:
        import importlib

        return getattr(importlib.import_module(_LAZY[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
