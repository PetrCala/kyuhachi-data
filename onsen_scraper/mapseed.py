"""Onsen *map seed* — the catalog's name + coordinates source.

The 88onsen detail page carries the descriptive fields (hours, fee, address, …)
but NOT the facility name, the area name, or the coordinates. Those live in the
site's map view: `https://www.88onsen.com/map` embeds the whole catalog as a
single `var markerData = [...]` JSON array, one object per onsen:

    {"id":"1","onsenti":"二日市温泉","shisetsu":"博多湯",
     "address":"筑紫野市湯町1-14-5","lat":33.4914372,"lng":130.5149407}

One fetch yields every currently-listed onsen's `hid → {name, areaName, address,
lat, lng}` — exactly the fields the published catalog doc needs for
`name`/`areaName`/`lat`/`lng` that a detail-page scrape can't supply, and the
cheapest authoritative *membership* signal there is (the full set of live hids in
a single request, vs crawling the paginated index).

`parse_map_seed` is pure stdlib; `fetch_map_seed` pulls the network stack lazily
(same pattern as `fees`/`hours`) so importing this module never requires requests.
"""
import json
import re

MAP_URL = "https://www.88onsen.com/map"

# The map page assigns the catalog to `var markerData = [ {...}, … ];`. No value
# in the array contains a literal ']', so a non-greedy match to the first '];' is
# exact (verified against the live page: 160/160 entries, 0 with ']' in a value).
_MARKER = re.compile(r"var\s+markerData\s*=\s*(\[.*?\]);", re.S)

# 88onsen JSON key → our field name.
_KEYS = {"shisetsu": "name", "onsenti": "areaName", "address": "address"}


def parse_map_seed(html: str) -> dict:
    """Parse the embedded `markerData` array → {hid(int): {name, areaName, address, lat, lng}}.

    Raises ValueError if the array is absent (the map DOM drifted) — the caller
    should treat that like a failed scrape, not an empty catalog."""
    m = _MARKER.search(html or "")
    if not m:
        raise ValueError("markerData array not found on the map page (DOM drift?)")
    out = {}
    for e in json.loads(m.group(1)):
        entry = {our: (e.get(src) or "").strip() or None for src, our in _KEYS.items()}
        entry["lat"] = float(e["lat"])
        entry["lng"] = float(e["lng"])
        out[int(e["id"])] = entry
    return out


def fetch_map_seed(**kwargs) -> dict:
    """Politely fetch /map and parse the seed. kwargs forwarded to `fetch_url`."""
    from onsen_scraper.fetcher import fetch_url
    return parse_map_seed(fetch_url(MAP_URL, **kwargs))
