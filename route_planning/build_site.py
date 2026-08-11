#!/usr/bin/env python3
"""Build the trail site published to GitHub Pages.

    python route_planning/build_site.py            # build into route_planning/site/
    python route_planning/build_site.py --open     # ...and open the index

The site is the plan in the form you actually use it: a phone, in Kyushu, often
with no signal. So three layers of offline, weakest to strongest:

  1. a service worker precaches every page on the first load, so the site opens
     from the home screen with the radio off;
  2. `offline.html` is every document concatenated into one self-contained file,
     the thing you save to Files and that survives a cache eviction;
  3. every page still prints, because paper survives a dead battery.

Only the Leaflet maps need signal (unpkg + OpenStreetMap tiles), and they are
labelled as such rather than pretended to work.

`render_html.py` owns the Markdown; this file owns the site around it. Output goes
to `route_planning/site/` (gitignored: CI rebuilds it from the committed Markdown
on every push to master).
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

from render_html import HERE, page, render, render_body

OUT = HERE / "site"
FINAL = HERE / "final_route"

# The published documents, in the order you would read them. `key` is the URL stem
# and the anchor namespace inside offline.html, so it must stay stable.
DOCS = [
    {
        "key": "plan_octnov",
        "src": HERE / "plan_octnov.md",
        "label": "The Oct/Nov 2026 day plan",
        "blurb": "Day by day: distance, ascent, which onsens open in time, where you sleep. "
        "The one to read on the trail.",
    },
    {
        "key": "decision_card",
        "src": HERE / "decision_card.md",
        "label": "Trail decision card",
        "blurb": "One page. Visit or walk on, the Nagasaki linchpin, the stretches to carry "
        "food and water into. Print this one.",
    },
    {
        "key": "00_itinerary",
        "src": FINAL / "00_itinerary.md",
        "label": "Hours-aware schedule simulation",
        "blurb": "The dated simulation the plan is checked against: every stop, every wait, "
        "every door that opens too late.",
    },
    {
        "key": "README",
        "src": FINAL / "README.md",
        "label": "Route stages",
        "blurb": "The eight stages of the foot line, with the terrain and resupply notes for "
        "each.",
    },
    {
        "key": "hike_2022_analysis",
        "src": HERE / "hike_2022_analysis.md",
        "label": "What the 2022 walk says about the pace",
        "blurb": "The walk across Japan, measured. Every pace number in the plan comes from "
        "here.",
    },
]

# Copied through as-is. Leaflet pulls its library and tiles over the network, so
# these are the one part of the site that needs signal.
MAPS = [
    {"src": FINAL / "00_full_route_map.html", "label": "Whole route"},
    *[
        {"src": FINAL / f"stage_{n:02d}_map.html", "label": f"Stage {n}"}
        for n in range(1, 9)
    ],
    {"src": HERE / "aso_crater_map.html", "label": "Aso crater spur"},
]

BACK = '<p class="back"><a href="./">&larr; all plans</a></p>'
SW_REGISTER = (
    "<script>\n"
    "  // Precaches the whole site on first load: the trail is where the signal is not.\n"
    "  if ('serviceWorker' in navigator) {\n"
    "    addEventListener('load', () => navigator.serviceWorker.register('sw.js'));\n"
    "  }\n"
    "</script>\n"
)
HEAD_EXTRA = (
    '<link rel="manifest" href="manifest.webmanifest">\n'
    '<link rel="icon" href="icon.png">\n'
    '<link rel="apple-touch-icon" href="icon.png">\n'
    '<meta name="apple-mobile-web-app-capable" content="yes">\n'
    '<meta name="theme-color" content="#8a5a2b">\n'
    "<style>\n"
    "  .back { margin: 0 0 1.5rem; font-size: .9rem; }\n"
    "  .back a { text-decoration: none; }\n"
    "  .cards { list-style: none; margin: 0 0 2rem; padding: 0; }\n"
    "  .cards li { margin: 0 0 .75rem; }\n"
    "  .cards a {\n"
    "    display: block; padding: 1rem 1.15rem; text-decoration: none; color: inherit;\n"
    "    background: var(--card); border: 1px solid var(--rule);\n"
    "    border-left: 4px solid var(--accent); border-radius: 6px;\n"
    "  }\n"
    "  .cards b { display: block; color: var(--accent); font-size: 1.05rem; }\n"
    "  .cards span { display: block; margin-top: .25rem; color: var(--muted);\n"
    "    font-size: .9rem; line-height: 1.5; }\n"
    "  .maps { list-style: none; margin: 0; padding: 0;\n"
    "    display: flex; flex-wrap: wrap; gap: .4rem; }\n"
    "  .maps li { margin: 0; }\n"
    "  .maps a { display: inline-block; padding: .3rem .6rem; text-decoration: none;\n"
    "    background: var(--card); border: 1px solid var(--rule); border-radius: 4px;\n"
    "    font-size: .9rem; }\n"
    "  .status { font-size: .85rem; color: var(--muted); }\n"
    "</style>\n"
)


# --- offline.html -----------------------------------------------------------
def namespace(body: str, key: str) -> str:
    """Prefix every anchor in a document so the concatenated file has no id
    collisions (two documents both heading a section "Files")."""
    body = re.sub(r'id="([^"]+)"', lambda m: f'id="{key}--{m.group(1)}"', body)
    return re.sub(r'href="#([^"]+)"', lambda m: f'href="#{key}--{m.group(1)}"', body)


def build_offline(docs: list[dict]) -> str:
    """Every document in one self-contained file: no JS, no network, no sibling
    files. This is the copy that survives the browser cache being evicted."""
    toc = "".join(
        f'<li><a href="#{d["key"]}">{html.escape(d["label"])}</a></li>' for d in docs
    )
    parts = [
        "<h1>九州八十八湯 · the whole plan, offline</h1>",
        "<p>Every document in one file. Save it to Files and it opens with the radio off. "
        "The route maps are not in here: they need the network to draw.</p>",
        f'<nav class="toc"><ol>{toc}</ol></nav>',
    ]
    for d in docs:
        parts.append(f'<hr><section id="{d["key"]}">')
        parts.append(namespace(render_body(d["src"].read_text(encoding="utf-8")), d["key"]))
        parts.append("</section>")
    parts.append(
        "<footer>Built by <code>route_planning/build_site.py</code> from the Markdown in "
        "<code>route_planning/</code>.</footer>"
    )
    return page("九州八十八湯 · the whole plan, offline", "\n".join(parts))


# --- index ------------------------------------------------------------------
def build_index(docs: list[dict], maps: list[dict]) -> str:
    cards = "".join(
        f'<li><a href="{d["key"]}.html"><b>{html.escape(d["label"])}</b>'
        f'<span>{html.escape(d["blurb"])}</span></a></li>'
        for d in docs
    )
    maplinks = "".join(
        f'<li><a href="maps/{m["src"].name}">{html.escape(m["label"])}</a></li>'
        for m in maps
    )
    body = f"""<h1>九州八十八湯</h1>
<p>1,205 km on foot across all seven Kyushu prefectures, starting 2 October 2026.
These are the working plans, rebuilt from the repository every time the Markdown
changes.</p>
<ul class="cards">{cards}</ul>

<h2 id="offline">Reading this with no signal</h2>
<p>You are going to want these somewhere between Kirishima and the Kuju massif, which
is exactly where the bars run out. Three ways, use all three:</p>
<ol>
<li><b>Open every page once on wifi.</b> The site caches itself in the browser and
then loads without a connection. <span class="status" id="cache-status"></span></li>
<li><b>Add to Home Screen</b> in Safari (share sheet &rarr; Add to Home Screen). It
opens full-screen, straight to this page, and uses the cache above.</li>
<li><b>Download <a href="offline.html" download>offline.html</a></b> &mdash; every
document in a single file, no network of any kind. Save it into Files (or mail it to
yourself) so a cleared cache cannot take the plan with it.</li>
</ol>
<p>Everything here also prints. The decision card is one page on purpose: paper is the
only copy that outlives the battery.</p>

<h2 id="maps">Route maps</h2>
<p class="status">These draw from OpenStreetMap, so unlike everything else on this
site they need a connection.</p>
<ul class="maps">{maplinks}</ul>

<footer>Built from the Markdown in <code>route_planning/</code> by
<code>build_site.py</code>. Source:
<a href="https://github.com/PetrCala/kyuhachi-data">github.com/PetrCala/kyuhachi-data</a>.</footer>
"""
    status = (
        "<script>\n"
        "  // Says plainly whether this phone is ready for the trail.\n"
        "  const el = document.getElementById('cache-status');\n"
        "  if (el && 'serviceWorker' in navigator) {\n"
        "    navigator.serviceWorker.ready.then(() => {\n"
        "      el.textContent = 'Cached: this site now opens offline.';\n"
        "    });\n"
        "  }\n"
        "</script>\n"
    )
    return page("九州八十八湯 · route plans", body, HEAD_EXTRA, SW_REGISTER + status)


def build_no_signal() -> str:
    """What the service worker serves for something it never cached, i.e. a map.
    Saying so beats quietly handing back the index page."""
    body = """<h1>No signal, and this one needs it</h1>
<p>The route maps draw their tiles from OpenStreetMap, so they only work with a
connection. Nothing is broken; you are just out of range.</p>
<p>The plans themselves are cached on this phone and open fine:</p>
<p><a href="./">&larr; back to all plans</a></p>
<p>If you saved <a href="offline.html">offline.html</a> to Files, that copy needs no
network at all.</p>
"""
    return page("No signal", body, HEAD_EXTRA)


# --- service worker ---------------------------------------------------------
def build_sw(assets: list[str], version: str) -> str:
    """Cache-first over a versioned cache: a page you have already loaded never
    waits on the network, and a new deploy replaces the lot in one go."""
    return f"""// Generated by route_planning/build_site.py. Do not edit.
const CACHE = 'kyuhachi-{version}';
const ASSETS = {json.dumps(assets, indent=2)};

self.addEventListener('install', (e) => {{
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
}});

self.addEventListener('activate', (e) => {{
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
}});

self.addEventListener('fetch', (e) => {{
  const url = new URL(e.request.url);
  // Map tiles and the Leaflet CDN are someone else's origin: let them fail honestly
  // rather than pretending a cached map exists.
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  e.respondWith(
    caches.match(e.request).then(
      (hit) =>
        hit ||
        fetch(e.request)
          .then((res) => {{
            if (res.ok) {{
              const copy = res.clone();
              caches.open(CACHE).then((c) => c.put(e.request, copy));
            }}
            return res;
          }})
          .catch(() => caches.match('no-signal.html'))
    )
  );
}});
"""


# --- icon -------------------------------------------------------------------
def write_png(dest: Path, size: int = 512) -> None:
    """An onsen mark drawn straight into a PNG: three steam curves over water.

    Hand-rolled because the whole toolchain here is stdlib-only, and pulling in
    Pillow to draw ten sine waves would be the only dependency in the repo.
    """
    bg, ink = (138, 90, 43), (251, 250, 247)
    px = [[bg] * size for _ in range(size)]

    def disc(cx: float, cy: float, r: float) -> None:
        for y in range(max(0, int(cy - r)), min(size, int(cy + r) + 1)):
            dx = math.sqrt(max(0.0, r * r - (y - cy) ** 2))
            for x in range(max(0, int(cx - dx)), min(size, int(cx + dx) + 1)):
                px[y][x] = ink

    stroke = size * 0.052
    for i, cx in enumerate((0.30, 0.50, 0.70)):
        # The middle plume rises higher, as it does on the map symbol.
        top = 0.20 if i == 1 else 0.28
        for step in range(400):
            t = step / 399
            y = (top + (0.62 - top) * t) * size
            x = (cx + 0.045 * math.sin(2 * math.pi * (t * 1.5 + 0.25))) * size
            disc(x, y, stroke / 2)
    for step in range(400):  # the water line
        t = step / 399
        disc((0.16 + 0.68 * t) * size, 0.78 * size, size * 0.062 / 2)

    raw = b"".join(
        b"\x00" + b"".join(struct.pack("3B", *px[y][x]) for x in range(size))
        for y in range(size)
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    dest.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


# --- build ------------------------------------------------------------------
def build() -> Path:
    docs = [d for d in DOCS if d["src"].exists()]
    missing = [d["src"].name for d in DOCS if not d["src"].exists()]
    if not docs:
        sys.exit("no documents to publish: is route_planning/ intact?")
    for name in missing:
        print(f"  skipped (not generated yet): {name}")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    for d in docs:
        dest = render(
            d["src"],
            out_dir=OUT,
            lead=BACK,
            head_extra=HEAD_EXTRA,
            body_extra=SW_REGISTER,
            footer=(
                f'<footer>Generated from <code>{d["src"].name}</code>. '
                '<a href="./">All plans</a> &middot; '
                '<a href="offline.html">the whole thing in one offline file</a>.</footer>'
            ),
        )
        if dest.stem != d["key"]:  # two READMEs cannot share a URL
            dest = dest.replace(OUT / f"{d['key']}.html")
        print(f'  {d["src"].name} -> site/{d["key"]}.html')

    (OUT / "offline.html").write_text(build_offline(docs), encoding="utf-8")

    maps = [m for m in MAPS if m["src"].exists()]
    (OUT / "maps").mkdir()
    for m in maps:
        shutil.copy2(m["src"], OUT / "maps" / m["src"].name)
    print(f"  {len(maps)} maps -> site/maps/")

    (OUT / "index.html").write_text(build_index(docs, maps), encoding="utf-8")
    (OUT / "no-signal.html").write_text(build_no_signal(), encoding="utf-8")
    write_png(OUT / "icon.png")
    (OUT / "manifest.webmanifest").write_text(
        json.dumps(
            {
                "name": "九州八十八湯 route plans",
                "short_name": "Kyuhachi",
                "start_url": "./",
                "scope": "./",
                "display": "standalone",
                "background_color": "#fbfaf7",
                "theme_color": "#8a5a2b",
                # Not declared maskable: the water line runs to the edge and a
                # circular mask would crop it off.
                "icons": [{"src": "icon.png", "sizes": "512x512", "type": "image/png"}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # Pages runs Jekyll otherwise, which would eat any future underscore-prefixed file.
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    # Precache the text, not the maps: the maps are 6 MB of tiles-that-will-not-load.
    assets = [
        "./",
        "index.html",
        "offline.html",
        "no-signal.html",
        "manifest.webmanifest",
        "icon.png",
    ]
    assets += [f'{d["key"]}.html' for d in docs]
    version = hashlib.sha256(
        b"".join((OUT / a).read_bytes() for a in assets if (OUT / a).is_file())
    ).hexdigest()[:12]
    (OUT / "sw.js").write_text(build_sw(assets, version), encoding="utf-8")
    print(f"  service worker cache kyuhachi-{version}")
    return OUT / "index.html"


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    index = build()
    print(f"site -> {OUT.relative_to(HERE.parent)}/")
    if "--open" in args:
        if sys.platform == "darwin":
            subprocess.run(["open", str(index)], check=True)
        else:
            print(f"open manually: {index.as_uri()}")
        # file:// has no service worker; for that, serve it:
        print("note: offline caching only kicks in over http, e.g.")
        print(f"      python -m http.server -d {OUT.relative_to(HERE.parent)} 8000")


if __name__ == "__main__":
    main()
