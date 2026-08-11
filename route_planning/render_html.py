#!/usr/bin/env python3
"""Render the route reports to standalone, offline HTML.

    python route_planning/render_html.py            # render both reports
    python route_planning/render_html.py --open      # ...and open in your browser
    python route_planning/render_html.py --app Safari --open
    python route_planning/render_html.py <any .md>   # render something else

Why this exists rather than a pandoc one-liner: the plan is a thing you open on a
phone in the Kuju massif with no signal, and it should regenerate on any machine
with nothing but Python. So there are no dependencies, no external requests, and
no JavaScript. Styling lives in `report_head.html`; edit that, not the output.

The Markdown subset handled here is exactly what `plan_octnov.py` and the analysis
docs emit: ATX headings, paragraphs, `**bold**` / `*em*` / `` `code` `` / links,
blockquotes, GFM pipe tables, bullet and numbered lists, and `---` rules. It is
deliberately not a general Markdown implementation. If a generator starts emitting
something new (nested lists, images, fenced code), teach it here.

Output goes to `route_planning/html/` (gitignored: it is a pure rendering of the
committed Markdown and adds no information of its own).

`build_site.py` reuses `render()` to build the published GitHub Pages site. The
extra hooks it needs (a different output directory, a back link, a service-worker
registration) are parameters here; the plain `--open` path stays JS-free.
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HEAD = HERE / "report_head.html"
OUT_DIR = HERE / "html"
DEFAULT_DOCS = [HERE / "plan_octnov.md", HERE / "hike_2022_analysis.md"]

# A per-day heading, e.g. "Day 12 · Tue 13 Oct · 39 km ...". Anchors become
# #day-12 rather than a slugified sentence, so links stay stable when the
# distances change.
DAY_RE = re.compile(r"^Day (\d+)\b")
# The simulation report dates its days instead of numbering them
# ("2026-10-02  (5 stops, 5 visited)"); same treatment, chip reads "10-02".
DATE_RE = re.compile(r"^(\d{4})-(\d{2}-\d{2})\b")


# --- inline -----------------------------------------------------------------
def inline(text: str) -> str:
    """Escape, then apply inline Markdown. Order matters: code first, so that
    `**` inside a code span is not mistaken for emphasis."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![*\w])\*([^*]+)\*(?!\*)", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)
    return out


def slug(text: str) -> str:
    s = re.sub(r"<[^>]+>", "", text).lower()
    s = re.sub(r"[^a-z0-9぀-ヿ一-鿿]+", "-", s)
    return s.strip("-") or "section"


# --- table ------------------------------------------------------------------
def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def verdict_class(cell: str) -> str:
    """Colour the verdict column so a day's shape reads at a glance."""
    if cell.startswith("VISIT"):
        return " class=\"visit\""
    if cell.startswith("SKIP"):
        return " class=\"skip\""
    return ""


def render_table(rows: list[str]) -> str:
    head, body = split_row(rows[0]), [split_row(r) for r in rows[2:]]
    out = ['<div class="tbl"><table>', "<thead><tr>"]
    out += [f"<th>{inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>")
        out += [f"<td{verdict_class(c)}>{inline(c)}</td>" for c in r]
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


# --- document ---------------------------------------------------------------
def convert(md: str) -> tuple[str, list[tuple[str, str]], list[tuple[str, str]]]:
    """Markdown -> (body html, [(h2 anchor, text)], [(day anchor, number)])."""
    lines = md.splitlines()
    body: list[str] = []
    sections: list[tuple[str, str]] = []
    days: list[tuple[str, str]] = []
    para: list[str] = []
    quote: list[str] = []
    table: list[str] = []
    listbuf: list[str] = []
    list_tag = ""
    i = 0

    def flush_para() -> None:
        if para:
            body.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    def flush_quote() -> None:
        if quote:
            text = " ".join(quote)
            cls = ""
            if text.startswith("CRUX "):
                cls = ' class="crux"'
                text = text[len("CRUX ") :]
            body.append(f"<blockquote{cls}><p>{inline(text)}</p></blockquote>")
            quote.clear()

    def flush_table() -> None:
        if table:
            body.append(render_table(table))
            table.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if listbuf:
            items = "".join(f"<li>{inline(x)}</li>" for x in listbuf)
            body.append(f"<{list_tag}>{items}</{list_tag}>")
            listbuf.clear()
            list_tag = ""

    def flush_all() -> None:
        flush_para(); flush_quote(); flush_table(); flush_list()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # a table is a run of lines starting with '|'
        if stripped.startswith("|"):
            flush_para(); flush_quote(); flush_list()
            table.append(stripped)
            i += 1
            continue
        flush_table()

        if stripped.startswith("> "):
            flush_para(); flush_list()
            quote.append(stripped[2:])
            i += 1
            continue

        if not stripped:
            # A blank line ends a paragraph or quote, but NOT a list: the risk
            # section separates its numbered items with blank lines and still
            # means one list.
            flush_para(); flush_quote()
            i += 1
            continue
        flush_quote()

        if stripped.startswith("### "):
            flush_all()
            text = stripped[4:]
            m = DAY_RE.match(text)
            d = DATE_RE.match(text)
            if m:
                anchor = f"day-{m.group(1)}"
                cls = "day rest" if "REST" in text else "day"
                days.append((anchor, m.group(1)))
            elif d:
                anchor = f"day-{d.group(1)}-{d.group(2)}"
                cls = "day"
                days.append((anchor, d.group(2)))
            else:
                anchor, cls = slug(text), ""
            attr = f' class="{cls}"' if cls else ""
            body.append(f'<h3 id="{anchor}"{attr}>{inline(text)}</h3>')
            i += 1
            continue

        if stripped.startswith("## "):
            flush_all()
            text = stripped[3:]
            anchor = slug(text)
            sections.append((anchor, text))
            body.append(f'<h2 id="{anchor}">{inline(text)}</h2>')
            i += 1
            continue

        if stripped.startswith("# "):
            flush_all()
            body.append(f"<h1>{inline(stripped[2:])}</h1>")
            i += 1
            continue

        if stripped == "---":
            flush_all()
            body.append("<hr>")
            i += 1
            continue

        m = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if m:
            flush_para()
            if list_tag != "ol":
                flush_list()
                list_tag = "ol"
            listbuf.append(m.group(2))
            i += 1
            continue

        if stripped.startswith("- "):
            flush_para()
            if list_tag != "ul":
                flush_list()
                list_tag = "ul"
            listbuf.append(stripped[2:])
            i += 1
            continue

        flush_list()
        para.append(stripped)
        i += 1

    flush_all()
    return "\n".join(body), sections, days


def build_toc(sections, days) -> str:
    if not sections and not days:
        return ""
    items = "".join(f'<li><a href="#{a}">{html.escape(t)}</a></li>' for a, t in sections)
    out = ['<nav class="toc">']
    if items:
        out.append(f"<ol>{items}</ol>")
    if days:
        chips = "".join(f'<li><a href="#{a}">{n}</a></li>' for a, n in days)
        out.append(f'<ul class="days">{chips}</ul>')
    out.append("</nav>")
    return "".join(out)


def doc_title(md: str, fallback: str) -> str:
    """The `# ` heading, stripped of Markdown emphasis, for <title>."""
    raw = next((ln[2:].strip() for ln in md.splitlines() if ln.startswith("# ")), fallback)
    return re.sub(r"[*`]", "", raw)


def page(title: str, body: str, head_extra: str = "", body_extra: str = "") -> str:
    """Wrap rendered body HTML in the standalone document shell."""
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"{HEAD.read_text(encoding='utf-8')}"
        f"{head_extra}"
        "</head>\n<body>\n"
        f"{body}\n"
        f"{body_extra}"
        "</body>\n</html>\n"
    )


def render_body(md: str) -> str:
    """Markdown -> body HTML with the table of contents under the <h1>."""
    body, sections, days = convert(md)
    head, rest = (body.split("\n", 1) + [""])[:2]  # the <h1> stays above the TOC
    return f"{head}\n{build_toc(sections, days)}\n{rest}"


def render(
    src: Path,
    out_dir: Path | None = None,
    lead: str = "",
    head_extra: str = "",
    body_extra: str = "",
    footer: str | None = None,
) -> Path:
    md = src.read_text(encoding="utf-8")
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / (src.stem + ".html")
    if footer is None:
        footer = (
            f"<footer>Generated from <code>{src.name}</code> by "
            "<code>render_html.py</code>. Regenerate with "
            "<code>python route_planning/render_html.py</code>.</footer>"
        )
    dest.write_text(
        page(
            doc_title(md, src.stem),
            f"{lead}{render_body(md)}\n{footer}",
            head_extra,
            body_extra,
        ),
        encoding="utf-8",
    )
    return dest


def main(argv: list[str] | None = None) -> None:
    # Explicit argv so pipeline.py can call this without its own flags leaking in.
    args = list(sys.argv[1:] if argv is None else argv)
    do_open = "--open" in args
    app = None
    if "--app" in args:
        app = args[args.index("--app") + 1]
        args = [a for a in args if a != app]
    docs = [Path(a) for a in args if not a.startswith("--")] or DEFAULT_DOCS

    made: list[Path] = []
    for src in docs:
        if not src.exists():
            sys.exit(f"no such file: {src}")
        dest = render(src)
        made.append(dest)
        print(f"{src.name} -> {dest.relative_to(HERE.parent)}")

    if do_open and sys.platform == "darwin":
        # Open in reverse so the first document ends up the front tab.
        for dest in reversed(made):
            cmd = ["open"] + (["-a", app] if app else []) + [str(dest)]
            subprocess.run(cmd, check=True)
        print(f"opened in {app or 'your default browser'}")
    elif do_open:
        print(f"open manually: {made[0].as_uri()}")


if __name__ == "__main__":
    main()
