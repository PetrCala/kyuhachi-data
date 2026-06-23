"""Onsen detail-page scraper for 88onsen.com.

Ported from the original prototype (kyuhachi/_archive/src/scraper). The
selectors are the canonical reference documented in the app repo's
docs/onsen-source-field-audit.md. Reuse the fetcher + parser here; do NOT
import from the app repo's _archive/.
"""

from onsen_scraper.fetcher import FetchError, fetch_detail_page, get_detail_url
from onsen_scraper.parser import parse_detail_page

__all__ = ["FetchError", "fetch_detail_page", "get_detail_url", "parse_detail_page"]
