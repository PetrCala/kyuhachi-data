#!/usr/bin/env python3
"""
cost-analysis — estimate the admission cost of completing the 88-onsen challenge.

Reads the adult single-visit admission fee out of each onsen's free-text
`admission_fee` (snapshot DB), then reports:

  - pool stats (min / max / mean / median per-onsen adult fee),
  - a Monte Carlo of the total cost of 88 randomly chosen onsens, repeated over
    many trials (the "what would a random run cost" figure),
  - the cheapest- and priciest-possible 88-visit totals (the real bounds).

Read-only: opens the snapshot DB `mode=ro`, writes nothing to it or Firestore.
The fee is heuristically parsed from messy Japanese text — see CAVEATS in
SKILL.md. The durable fix is a numeric `adultFee` published on the catalog;
until that exists, this skill is the source of the parse.

Usage:
  python cost_analysis.py                         # JPY, 88 picks, 30 trials, seed 88
  python cost_analysis.py --rate 0.130899 --currency CZK   # convert every figure
  python cost_analysis.py --show-prices           # dump per-onsen extracted fee + method
  python cost_analysis.py --json                  # machine-readable output
  python cost_analysis.py --svg cost.svg          # also write a dependency-free bar chart
"""
import argparse
import json
import random
import re
import sqlite3
import statistics
import sys
import unicodedata
from pathlib import Path

# This file lives at <repo>/.claude/skills/cost-analysis/cost_analysis.py.
REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_DB = REPO_ROOT / "data" / "snapshot.db"

# Manual corrections: ids where the free-text fee defeats the heuristic or where
# there is no standard individual adult walk-in price. Validated by hand against
# the source. value = adult single-visit price in yen.
CORRECTIONS = {
    151: 700,   # parser grabs the 70才以上 (senior) 500; adult (13才以上) is 700
    192: 1200,  # private-bath-only; "一人湯 ￥1,200" is the solo individual rate
    239: 600,   # parser grabs a 貸切 (private-bath) 1,200; adult walk-in is 中学生以上 600
}

YEN = re.compile(r"([0-9][0-9,]*)\s*円")
ADULT = re.compile(r"大\s*人|おとな")          # 大人 / 大　人 / おとな
JHS = re.compile(r"中学生以上")                # junior-high-and-up == adult when no 大人


def norm(text: str) -> str:
    """NFKC fold so full-width digits/commas/spaces parse (１，０２０ → 1,020)."""
    return unicodedata.normalize("NFKC", text or "")


def _first_yen_after(text: str, idx: int):
    m = YEN.search(text, idx)
    return int(m.group(1).replace(",", "")) if m else None


def extract_adult_fee(raw: str):
    """Best-effort adult single-visit admission in yen, plus the method used.

    Priority: an explicit 大人/おとな price, else a 中学生以上 (adult-equivalent)
    price, else free, else the first yen figure on the page (covers age-gated and
    private-bath-only facilities, where the first figure is the entry price).
    """
    t = norm(raw)
    m = ADULT.search(t)
    if m:
        v = _first_yen_after(t, m.start())
        if v is not None:
            return v, "adult"
    m = JHS.search(t)
    if m:
        v = _first_yen_after(t, m.start())
        if v is not None:
            return v, "jhs+"
    if "無料" in t and not YEN.search(t):
        return 0, "free"
    m = YEN.search(t)
    if m:
        return int(m.group(1).replace(",", "")), "fallback"
    return None, "none"


def load_prices(db_path: Path):
    """[(id, name, fee_yen|None, method)] for every onsen, corrections applied."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select id, facility_name, admission_fee from onsens order by id"
        ).fetchall()
    finally:
        con.close()
    out = []
    for oid, name, fee in rows:
        if oid in CORRECTIONS:
            out.append((oid, name, CORRECTIONS[oid], "corrected"))
        else:
            v, how = extract_adult_fee(fee)
            out.append((oid, name, v, how))
    return out


def monte_carlo(values, pick, trials, seed):
    rng = random.Random(seed)
    totals = [sum(rng.sample(values, pick)) for _ in range(trials)]
    return totals


def analyze(prices, pick, trials, seed):
    values = [v for _, _, v, _ in prices if v is not None]
    n = len(values)
    if pick > n:
        raise SystemExit(f"--pick {pick} exceeds the {n} onsens with a parseable fee")
    totals = monte_carlo(values, pick, trials, seed)
    ordered = sorted(values)
    return {
        "pool_size": n,
        "pool_min": min(values),
        "pool_max": max(values),
        "pool_mean": sum(values) / n,
        "pool_median": statistics.median(values),
        "pick": pick,
        "trials": trials,
        "seed": seed,
        "trial_totals": totals,
        "grand_avg_total": sum(totals) / trials,
        "avg_per_visit": (sum(totals) / trials) / pick,
        "trial_min": min(totals),
        "trial_max": max(totals),
        "trial_stdev": statistics.pstdev(totals),
        "cheapest_possible": sum(ordered[:pick]),
        "priciest_possible": sum(ordered[-pick:]),
    }


# --- output ------------------------------------------------------------------

def make_fmt(rate, currency):
    if rate is None:
        return lambda yen: f"¥{round(yen):,}", "JPY (¥)"
    return lambda yen: f"{yen * rate:,.0f} {currency}", f"{currency} @ {rate} per ¥1"


def print_report(r, fmt, unit):
    money = fmt
    print(f"== Onsen 88-challenge cost analysis ==  ({unit})\n")
    print(f"Pool: {r['pool_size']} onsens with a parseable adult fee")
    print(f"  per-onsen fee   min {money(r['pool_min'])}  median {money(r['pool_median'])}"
          f"  mean {money(r['pool_mean'])}  max {money(r['pool_max'])}\n")
    print(f"Monte Carlo: {r['trials']} trials x {r['pick']} random onsens (seed {r['seed']})")
    print(f"  GRAND AVERAGE total : {money(r['grand_avg_total'])}")
    print(f"  average per visit   : {money(r['avg_per_visit'])}")
    print(f"  trial spread        : {money(r['trial_min'])} – {money(r['trial_max'])}"
          f"  (sd {money(r['trial_stdev'])})\n")
    print("Real bounds (you choose which 88 to visit):")
    print(f"  cheapest possible 88: {money(r['cheapest_possible'])}")
    print(f"  priciest possible 88: {money(r['priciest_possible'])}")


def print_prices(prices, fmt):
    print("id\tfee\tmethod\tname")
    for oid, name, v, how in prices:
        cell = "—" if v is None else fmt(v)
        print(f"{oid}\t{cell}\t{how}\t{name}")
    print()


def write_svg(r, path, fmt):
    """Dependency-free bar chart of the trial totals + average line."""
    totals = r["trial_totals"]
    W, H, pad = 720, 360, 48
    plot_w, plot_h = W - 2 * pad, H - 2 * pad
    top = max(totals) * 1.08
    bar_w = plot_w / len(totals)
    avg_y = pad + plot_h * (1 - r["grand_avg_total"] / top)
    bars = []
    for i, t in enumerate(totals):
        h = plot_h * (t / top)
        x = pad + i * bar_w
        y = pad + plot_h - h
        bars.append(
            f'<rect x="{x + bar_w * 0.12:.1f}" y="{y:.1f}" '
            f'width="{bar_w * 0.76:.1f}" height="{h:.1f}" fill="#378ADD"/>'
        )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="sans-serif">
<text x="{pad}" y="28" font-size="15" fill="#222">88-onsen challenge: total cost across {r['trials']} random trials</text>
{''.join(bars)}
<line x1="{pad}" y1="{avg_y:.1f}" x2="{W - pad}" y2="{avg_y:.1f}" stroke="#D85A30" stroke-width="2" stroke-dasharray="6 4"/>
<text x="{W - pad}" y="{avg_y - 6:.1f}" font-size="12" fill="#D85A30" text-anchor="end">avg {fmt(r['grand_avg_total'])}</text>
<line x1="{pad}" y1="{pad + plot_h}" x2="{W - pad}" y2="{pad + plot_h}" stroke="#999" stroke-width="1"/>
<text x="{pad}" y="{H - 16}" font-size="12" fill="#666">trial 1</text>
<text x="{W - pad}" y="{H - 16}" font-size="12" fill="#666" text-anchor="end">trial {r['trials']}</text>
</svg>"""
    Path(path).write_text(svg, encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Estimate the cost of the 88-onsen challenge.")
    ap.add_argument("--pick", type=int, default=88, help="onsens per trial (default 88)")
    ap.add_argument("--trials", type=int, default=30, help="number of trials (default 30)")
    ap.add_argument("--seed", type=int, default=88, help="RNG seed (default 88, reproducible)")
    ap.add_argument("--rate", type=float, default=None,
                    help="multiply every yen figure by this (e.g. 0.130899 for CZK)")
    ap.add_argument("--currency", default="CZK", help="currency label when --rate is given")
    ap.add_argument("--db", type=Path, default=SNAPSHOT_DB, help="snapshot DB path")
    ap.add_argument("--show-prices", action="store_true", help="dump per-onsen extracted fee")
    ap.add_argument("--svg", type=Path, default=None, help="write a bar chart SVG to this path")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    prices = load_prices(args.db)
    result = analyze(prices, args.pick, args.trials, args.seed)
    fmt, unit = make_fmt(args.rate, args.currency)

    if args.json:
        out = dict(result)
        if args.rate is not None:
            out["rate"] = args.rate
            out["currency"] = args.currency
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print_report(result, fmt, unit)
        if args.show_prices:
            print()
            print_prices(prices, fmt)

    if args.svg:
        write_svg(result, args.svg, fmt)
        if not args.json:
            print(f"\nwrote {args.svg}")


if __name__ == "__main__":
    main()
