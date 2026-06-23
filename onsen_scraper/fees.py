"""Adult single-visit admission fee parsed from the free-text `admission_fee`.

`admission_fee` on 88onsen.com is free Japanese text, e.g.
`大人 350円（土日祝450円）\\n中人(6～11才) 200円 …`. This module extracts the
**adult weekday walk-in** price (in yen) as a single integer, the number the app
sums for its cost/budget stats.

Single source of truth: the `cost-analysis` skill and the catalog publisher both
import from here, so the heuristic and the per-id corrections live in one place.

The parse is heuristic — see CAVEATS in `.claude/skills/cost-analysis/SKILL.md`.
`adult_fee()` is text-only; per-onsen corrections (keyed by upstream id, not
derivable from text) are applied by `fee_for()`.
"""
import re
import unicodedata

# Per-onsen overrides: ids where the free text defeats the heuristic, or where
# there is no standard individual adult walk-in price. Validated by hand against
# the source. value = adult single-visit price in yen.
CORRECTIONS = {
    151: 700,   # heuristic grabs the 70才以上 (senior) 500; adult (13才以上) is 700
    192: 1200,  # private-bath-only; "一人湯 ￥1,200" is the solo individual rate
    239: 600,   # heuristic grabs a 貸切 (private-bath) 1,200; walk-in is 中学生以上 600
}

_YEN = re.compile(r"([0-9][0-9,]*)\s*円")
_ADULT = re.compile(r"大\s*人|おとな")      # 大人 / 大　人 / おとな
_JHS = re.compile(r"中学生以上")            # junior-high-and-up == adult when no 大人


def norm(text: str) -> str:
    """NFKC fold so full-width digits/commas/spaces parse (１，０２０ → 1,020)."""
    return unicodedata.normalize("NFKC", text or "")


def _first_yen_after(text: str, idx: int):
    m = _YEN.search(text, idx)
    return int(m.group(1).replace(",", "")) if m else None


def adult_fee(raw: str):
    """Best-effort adult single-visit admission in yen + the method used.

    Returns ``(yen, method)`` where method is one of ``adult`` / ``jhs+`` /
    ``free`` / ``fallback`` / ``none``, or ``(None, "none")`` if no figure at all.

    Priority: an explicit 大人/おとな price, else a 中学生以上 (adult-equivalent)
    price, else free, else the first yen figure on the page (covers age-gated and
    private-bath-only facilities, where the first figure is the entry price).
    """
    t = norm(raw)
    m = _ADULT.search(t)
    if m:
        v = _first_yen_after(t, m.start())
        if v is not None:
            return v, "adult"
    m = _JHS.search(t)
    if m:
        v = _first_yen_after(t, m.start())
        if v is not None:
            return v, "jhs+"
    if "無料" in t and not _YEN.search(t):
        return 0, "free"
    m = _YEN.search(t)
    if m:
        return int(m.group(1).replace(",", "")), "fallback"
    return None, "none"


def fee_for(onsen_id, raw: str):
    """Adult fee for an onsen, applying the per-id correction first.

    Returns ``(yen, method)``; method is ``corrected`` when a hand override
    applied, else whatever ``adult_fee()`` returned.
    """
    if onsen_id in CORRECTIONS:
        return CORRECTIONS[onsen_id], "corrected"
    return adult_fee(raw)
