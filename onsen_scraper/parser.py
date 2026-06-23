"""HTML parser for onsen detail pages.

Extracts structured fields from raw HTML using BeautifulSoup. All values are
returned as raw strings; normalization for comparison is the caller's job (see
the catalog-diff skill). Selectors are documented field-by-field in the app
repo's docs/onsen-source-field-audit.md.
"""

import logging
import re

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


# Maps Japanese <dt> labels to our field names.
_FIELD_MAP: dict[str, str] = {
    "住所": "address",
    "電話番号": "phone",
    "営業時間": "business_hours",
    "料金": "admission_fee",
    "泉質": "spring_quality",
    "泉人優待": "senjin_benefits",
    "アクセス": "access_info",
    "効能": "efficacy",
    "施設サイト": "website_url",
}


def parse_detail_page(html: str, onsen_id: int) -> dict[str, str | None]:
    """Parse an onsen detail page and extract all available fields.

    Args:
        html: Raw HTML string of the detail page.
        onsen_id: The onsen ID, used for logging.

    Returns:
        Dictionary of field_name -> value (strings, or None if not found).
    """
    soup = BeautifulSoup(html, "html.parser")

    result: dict[str, str | None] = {}

    result["prefecture"] = _extract_prefecture(soup)
    result["recommendation"] = _extract_recommendation(soup)
    result["image_url"] = _extract_image_url(soup)
    result["covid_measures"] = _extract_covid_measures(soup)

    # Extract table fields (the main <dl> block).
    result.update(_extract_table_fields(soup))

    # website_url: extract the href, not the link text.
    result["website_url"] = _extract_website_url(soup)

    # efficacy lives in an HTML comment on most pages.
    if result.get("efficacy") is None:
        result["efficacy"] = _extract_commented_efficacy(html)

    # Treat &nbsp; / empty strings as None.
    for key, value in result.items():
        if isinstance(value, str):
            cleaned = value.strip()
            result[key] = None if cleaned in ("", "\xa0", "&nbsp;") else cleaned

    fields_found = sum(1 for v in result.values() if v is not None)
    logger.debug("Onsen %d: extracted %d fields", onsen_id, fields_found)

    return result


def _extract_prefecture(soup: BeautifulSoup) -> str | None:
    """Prefecture from the breadcrumb: #contents_title li (last li, no link)."""
    title_div = soup.find("div", id="contents_title")
    if not title_div:
        return None

    items = title_div.find_all("li")  # type: ignore[union-attr]
    for item in reversed(items):
        if not item.find("a") and not item.get("class"):
            text = item.get_text(strip=True)
            if text:
                return text

    return None


def _extract_recommendation(soup: BeautifulSoup) -> str | None:
    """Recommendation one-liner: #spot_recommend p."""
    section = soup.find("div", id="spot_recommend")
    if not section:
        return None

    p_tag = section.find("p")  # type: ignore[union-attr]
    return p_tag.get_text(strip=True) if p_tag else None


def _extract_image_url(soup: BeautifulSoup) -> str | None:
    """Representative photo: #spot_detail p.figure img[src]."""
    detail = soup.find("div", id="spot_detail")
    if not detail:
        return None

    figure = detail.find("p", class_="figure")  # type: ignore[union-attr]
    if not figure:
        return None

    img = figure.find("img")  # type: ignore[union-attr]
    if img and isinstance(img, Tag) and img.get("src"):
        src = str(img["src"]).strip()
        return src or None

    return None


def _extract_table_fields(soup: BeautifulSoup) -> dict[str, str | None]:
    """Fields from the main detail table: #spot_detail dl.tableview dt/dd pairs."""
    result: dict[str, str | None] = {}

    detail = soup.find("div", id="spot_detail")
    if not detail:
        return result

    dl = detail.find("dl", class_="tableview")  # type: ignore[union-attr]
    if not dl:
        return result

    for dt in dl.find_all("dt"):  # type: ignore[union-attr]
        label = dt.get_text(strip=True)
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue

        field_name = _FIELD_MAP.get(label)
        if field_name is None:
            logger.debug("Unknown table field: %s", label)
            continue

        # website_url handled separately to capture the href.
        if field_name == "website_url":
            continue

        result[field_name] = _get_text_with_linebreaks(dd)

    return result


def _extract_website_url(soup: BeautifulSoup) -> str | None:
    """Facility site href from the <dd> after <dt>施設サイト</dt> (not link text)."""
    detail = soup.find("div", id="spot_detail")
    if not detail:
        return None

    dl = detail.find("dl", class_="tableview")  # type: ignore[union-attr]
    if not dl:
        return None

    for dt in dl.find_all("dt"):  # type: ignore[union-attr]
        if dt.get_text(strip=True) == "施設サイト":
            dd = dt.find_next_sibling("dd")
            if dd:
                link = dd.find("a")  # type: ignore[union-attr]
                if link and isinstance(link, Tag) and link.get("href"):
                    return str(link["href"]).strip()
            return None

    return None


def _extract_covid_measures(soup: BeautifulSoup) -> str | None:
    """Facility / COVID notes: first #spot_near section, first non-figure <p>."""
    near_sections = soup.find_all("div", id="spot_near")
    if not near_sections:
        return None

    for p in near_sections[0].find_all("p"):
        if p.get("class") and "figure" in p.get("class", []):
            continue
        text = p.get_text(strip=True)
        if text:
            return text

    return None


def _extract_commented_efficacy(html: str) -> str | None:
    """Efficacy is often inside an HTML comment: <!--<dt>効能</dt><dd>…</dd>-->."""
    match = re.search(r"<!--\s*<dt>効能</dt>\s*<dd>(.*?)</dd>\s*-->", html, re.DOTALL)
    if match:
        inner_soup = BeautifulSoup(match.group(1), "html.parser")
        text = inner_soup.get_text(strip=True)
        if text and text not in ("\xa0", "&nbsp;", ""):
            return text

    return None


def _get_text_with_linebreaks(element: Tag) -> str:
    """Get text content, converting <br> to newlines and trimming blank lines."""
    for br in element.find_all("br"):
        br.replace_with("\n")

    lines = [line.strip() for line in element.get_text().split("\n")]
    return "\n".join(line for line in lines if line)
