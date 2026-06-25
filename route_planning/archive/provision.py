#!/usr/bin/env python3
"""Deliverable 1: how many onsens to route PAST (provision target N) so we
reliably bank >=88 unique OPEN-on-arrival visits with margin.

Approach: estimate per-onsen P(catchable) = P(not on a closure that day) *
P(not irregular-closed) * P(arrive within window). Model banked ~ Binomial(N, p)
and solve for the N whose 5th percentile >= 88.
"""
from __future__ import annotations

import math
from collections import Counter

from onsen_model import load_onsens

ons = load_onsens()
N_TOTAL = len(ons)

# ---- component 1: fixed weekly closure (定休日) -----------------------------
closed_incidences = sum(len(o.closed_weekdays) for o in ons)
avg_closed_days = closed_incidences / N_TOTAL
p_fixed_hit_uncontrolled = avg_closed_days / 7.0  # random arrival weekday

# ---- component 2: irregular (不定休) ---------------------------------------
n_irreg = sum(o.irregular for o in ons)
frac_irreg = n_irreg / N_TOTAL
# Assume an 不定休 onsen is unpredictably shut ~1 day/week of its own.
IRREG_SHUT_RATE = 0.12
p_irreg_loss = frac_irreg * IRREG_SHUT_RATE

# ---- component 3: early-closing window risk --------------------------------
early_1500 = [o for o in ons if o.effective_last_min is not None and o.effective_last_min <= 15 * 60]
early_1800 = [o for o in ons if o.effective_last_min is not None and o.effective_last_min <= 18 * 60]
frac_early_1500 = len(early_1500) / N_TOTAL
frac_early_1800 = len(early_1800) / N_TOTAL
# Of the very-early closers (<=15:00), assume ~35% can't be fit into the day's
# chain on foot; of the 15-18h closers, ~10%.
mid_early = [o for o in ons if o.effective_last_min and 15 * 60 < o.effective_last_min <= 18 * 60]
p_window_loss = (len(early_1500) * 0.35 + len(mid_early) * 0.10) / N_TOTAL

print("=" * 70)
print("POPULATION CLOSURE / WINDOW STATS  (146 foot-eligible onsens)")
print("=" * 70)
print(f"Fixed weekly closure incidences:     {closed_incidences} across {N_TOTAL} onsens")
print(f"  -> avg closed days/onsen/week:     {avg_closed_days:.2f}")
print(f"  -> P(random arrival hits closure): {p_fixed_hit_uncontrolled*100:.1f}%  (uncontrolled)")
print(f"不定休 irregular onsens:              {n_irreg} ({frac_irreg*100:.0f}%)")
print(f"  -> expected loss @ {IRREG_SHUT_RATE*100:.0f}% shut-rate:    {p_irreg_loss*100:.1f}%")
print(f"Early closers <=15:00 last-entry:    {len(early_1500)} ({frac_early_1500*100:.0f}%)")
print(f"Early closers <=18:00 last-entry:    {len(early_1800)} ({frac_early_1800*100:.0f}%)")
print(f"  -> est. window-miss loss:          {p_window_loss*100:.1f}%")

# ---- combine into p(catchable) under two regimes ---------------------------
# Pessimistic: you cannot avoid fixed closures (skip-only), full window loss.
p_loss_pess = p_fixed_hit_uncontrolled + p_irreg_loss + p_window_loss
# Realistic: flexible foot schedule lets you avoid ~60% of known fixed closures
# by timing arrival a few hours / part of a day; window loss as estimated.
p_loss_real = 0.40 * p_fixed_hit_uncontrolled + p_irreg_loss + p_window_loss

p_pess = 1 - p_loss_pess
p_real = 1 - p_loss_real

print()
print("P(catchable) per onsen:")
print(f"  pessimistic (skip-only, no closure-avoidance): {p_pess:.3f}")
print(f"  realistic   (time around known closures):      {p_real:.3f}")


def binom_p5(N, p):
    """Normal-approx 5th percentile of Binomial(N,p) (banked count)."""
    mean = N * p
    sd = math.sqrt(N * p * (1 - p))
    return mean - 1.645 * sd, mean, sd


def smallest_N(p, target=88, conf_z=1.645):
    N = target
    while N <= N_TOTAL:
        p5, mean, sd = binom_p5(N, p)
        if p5 >= target:
            return N, mean, sd, p5
        N += 1
    return None


print()
print("=" * 70)
print("PROVISIONING: smallest N to route-past so P(banked >= 88) ~ 95%")
print("=" * 70)
for label, p in [("pessimistic", p_pess), ("realistic", p_real), ("p=0.87 (brief)", 0.87)]:
    res = smallest_N(p)
    if res:
        N, mean, sd, p5 = res
        print(f"  {label:18s} p={p:.3f}: N={N:3d}  (E[banked]={mean:.1f}, sd={sd:.1f}, 5th pct={p5:.1f})")
    else:
        print(f"  {label:18s} p={p:.3f}: NOT ACHIEVABLE within {N_TOTAL} onsens")

print()
print("Sensitivity — expected & 5th-pct banked for candidate N (realistic p):")
print(f"  {'N':>4} {'E[banked]':>10} {'5th pct':>9} {'P(>=88)':>9}")
from math import erf, sqrt
def prob_ge(N, p, k=88):
    mean = N * p
    sd = sqrt(N * p * (1 - p))
    # continuity-corrected normal
    z = (k - 0.5 - mean) / sd
    return 1 - 0.5 * (1 + erf(z / sqrt(2)))
for N in (95, 100, 102, 105, 108, 110, 112, 115):
    p5, mean, sd = binom_p5(N, p_real)
    print(f"  {N:>4} {mean:>10.1f} {p5:>9.1f} {prob_ge(N,p_real)*100:>8.1f}%")
