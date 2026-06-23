"""HTTP fetcher with delay, retry logic, and respectful scraping.

Polite by design: a 1s pre-request delay, a browser User-Agent, and
exponential backoff on failure. Keep these manners — sample, don't hammer.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

# Base URL template for onsen detail pages. {id} is the upstream `hid` — the
# same id used as a key in data/onsen-id-map.json.
DETAIL_URL_TEMPLATE = "https://www.88onsen.com/spot/detail/hid/{id}"

DEFAULT_DELAY_SECONDS = 1.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT_SECONDS = 15

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class FetchError(Exception):
    """Raised when a page cannot be fetched after all retries."""


def fetch_detail_page(
    onsen_id: int,
    *,
    delay: float = DEFAULT_DELAY_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Fetch the HTML of an onsen detail page.

    Args:
        onsen_id: The onsen ID (hid parameter on the website).
        delay: Seconds to wait before making the request (respectful scraping).
        max_retries: Maximum number of retry attempts on failure.
        timeout: Request timeout in seconds.

    Returns:
        Raw HTML string of the page.

    Raises:
        FetchError: If the page cannot be fetched after all retries.
    """
    url = DETAIL_URL_TEMPLATE.format(id=onsen_id)
    headers = {"User-Agent": _USER_AGENT}

    if delay > 0:
        time.sleep(delay)

    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()

            # Decode with error handling (some pages have non-UTF-8 bytes).
            html = response.content.decode("utf-8", errors="ignore")

            if not html.strip():
                raise FetchError(f"Empty response for onsen {onsen_id}")

            return html

        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < max_retries:
                wait = 2**attempt  # Exponential backoff: 2, 4, 8 seconds.
                logger.warning(
                    "Attempt %d/%d failed for onsen %d: %s. Retrying in %ds...",
                    attempt, max_retries, onsen_id, e, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "All %d attempts failed for onsen %d: %s",
                    max_retries, onsen_id, e,
                )

    raise FetchError(
        f"Failed to fetch onsen {onsen_id} after {max_retries} attempts: {last_error}"
    )


def get_detail_url(onsen_id: int) -> str:
    """Get the full URL for an onsen detail page."""
    return DETAIL_URL_TEMPLATE.format(id=onsen_id)
