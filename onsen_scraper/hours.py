"""Structured weekly schedule parsed from the free-text `business_hours`.

`business_hours` on 88onsen.com is free Japanese text crammed with the operating
window, the regular closed day(s), last-entry notes, and parking/locker lines,
e.g. `10:00～22:00\n火曜休（祝日の場合は営業）\n・駐車場：普通車50台`. This module
extracts the **single daily window** + the **regular weekly closed days** and
projects them onto the app's published shape:

    ParsedHours = {"raw": <verbatim text>, "schedule": WeeklySchedule | None}

where `WeeklySchedule` is the seven keys monday..sunday, each `{"opens","closes"}`
("HH:MM") or `null`, and **a null day means closed** (the app renders it as
"Closed"; see app repo shared/src/types/onsen.ts + app/app/onsens/[id].tsx). The
`raw` text is always published alongside, so any nuance the structured shape
can't hold (holiday exceptions, last entry, seasonal hours) survives for display.

Deliberately conservative — it only emits a structured `schedule` when the source
is unambiguous, and **never fabricates "open every day" from silence**: hours
with no stated closed day return `schedule=None`, because absence of a 定休日 on
88onsen does NOT mean the operator is open daily (the exact gap that motivated
this — an onsen 88onsen lists as open daily that is in fact closed Tuesdays per
its own site). Catching *wrong* 88onsen data is the separate official-site
cross-check; this module only structures what the source actually states.

A `schedule` is produced only when ALL hold (else `raw` fallback):
  - exactly one operating time window (multi-window / seasonal → raw),
  - the closure is explicit `無休`/`定休日なし` (open all week) or a plain weekly
    weekday list/range (`火曜休`, `火・金曜休`, `月～木曜休`),
  - no irregular closure (`不定休`, `第3水曜休`, `毎月…`, `5,15,25日休`, `月末…`),
  - no conditional/partial weekday closure (`火曜休（但し16:00以降入浴可）`).

Pure stdlib (no network stack) so it is eager-imported from `onsen_scraper`,
same as `fees`.
"""
import re
import unicodedata
from dataclasses import dataclass, field

# app WeeklySchedule key order (Mon-first), matches shared/src/types/onsen.ts.
DAYS: tuple[str, ...] = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)
_JP_DAY = {"月": "monday", "火": "tuesday", "水": "wednesday", "木": "thursday",
           "金": "friday", "土": "saturday", "日": "sunday"}
_DAY_IDX = {d: i for i, d in enumerate(DAYS)}

# A clock time and an open→close range. NFKC has already folded full-width digits
# and `：`→`:`; `～`(U+FF5E)→`~`, but the wave dash `〜`(U+301C) is left as-is.
_TIME = r"(\d{1,2}:\d{2})"
_RANGE = re.compile(_TIME + r"\s*[~〜]\s*" + _TIME)

# Closures we cannot place on a fixed weekly grid → always fall back to raw.
_IRREGULAR = re.compile(r"不定休|第\s*\d|毎月|\d\s*日休|月末")

# A weekday closure: one or more 月火水木金土日 joined by ・/、, then 曜?日?休.
_WEEKDAY_LIST = re.compile(r"([月火水木金土日](?:[・、][月火水木金土日])*)(?:曜日|曜|日)?休")
# A weekday *range*, e.g. 月～木曜休 (Mon..Thu closed).
_WEEKDAY_RANGE = re.compile(r"([月火水木金土日])[~〜]([月火水木金土日])(?:曜日|曜|日)?休")
# The parenthetical right after a 休 token, e.g. 火曜休（但し16:00以降入浴可）.
_CLOSURE_NOTE = re.compile(r"休[（(]([^）)]*)[）)]")
# A conditional/partial closure marker inside that note (the closure isn't total).
_PARTIAL = re.compile(r"但し|ただし|以降|以前|\d{1,2}:\d{2}")

_OPEN_ALL = ("無休", "定休日なし")


@dataclass(frozen=True)
class HoursParse:
    """Result of parsing a `business_hours` string.

    `schedule` is the app-shaped WeeklySchedule (or None when we fall back to
    raw). The rest is diagnostic — `reason` explains the outcome, `notes` keeps
    any captured closure caveat (e.g. 祝日の場合は営業) that the app shape can't
    hold but which lives on in the published `raw`.
    """
    raw: str | None
    schedule: dict | None
    window: tuple[str, str] | None
    closed_days: tuple[str, ...]
    confidence: str  # "high" when schedule produced, else "none"
    reason: str
    notes: str | None = None


def norm(text: str | None) -> str:
    """NFKC fold so full-width digits/colons/tildes parse (１０：００ → 10:00)."""
    return unicodedata.normalize("NFKC", text or "")


def _hhmm(t: str) -> str:
    """Zero-pad the hour: '9:00' → '09:00', '24:00' → '24:00'."""
    h, m = t.split(":")
    return f"{int(h):02d}:{m}"


def _windows(t: str) -> list[tuple[str, str]]:
    """Distinct operating windows, ignoring single-time last-entry notes."""
    return list(dict.fromkeys(_RANGE.findall(t)))


def _closed_days(t: str) -> tuple[list[str] | None, str | None, bool]:
    """(closed_day_keys, note, partial).

    closed_day_keys is [] for explicitly open-all-week, a weekday list when one
    is stated, or None when the text states no regular closure at all. `partial`
    flags a conditional weekday closure that isn't a true full-day closure.
    """
    note_m = _CLOSURE_NOTE.search(t)
    note = note_m.group(1).strip() if note_m else None

    rng = _WEEKDAY_RANGE.search(t)
    if rng:
        a, b = _DAY_IDX[_JP_DAY[rng.group(1)]], _DAY_IDX[_JP_DAY[rng.group(2)]]
        span = range(a, b + 1) if a <= b else list(range(a, 7)) + list(range(0, b + 1))
        return [DAYS[i] for i in span], note, _is_partial(note)

    days: list[str] = []
    for tok in _WEEKDAY_LIST.findall(t):
        for ch in tok:
            if ch in _JP_DAY and _JP_DAY[ch] not in days:
                days.append(_JP_DAY[ch])
    if days:
        days.sort(key=_DAY_IDX.get)
        return days, note, _is_partial(note)

    if any(k in t for k in _OPEN_ALL):
        return [], note, False

    return None, None, False


def _is_partial(note: str | None) -> bool:
    return bool(note and _PARTIAL.search(note))


def _build_schedule(opens: str, closes: str, closed: list[str]) -> dict:
    win = {"opens": opens, "closes": closes}
    return {d: (None if d in closed else dict(win)) for d in DAYS}


def parse_hours(raw: str | None) -> HoursParse:
    """Parse `business_hours` text into a structured weekly schedule.

    Returns a `HoursParse`; `.schedule` is the app-shaped WeeklySchedule when the
    source is unambiguous, else None (caller shows `.raw`). See module docstring
    for the exact conditions and the reason codes in `.reason`:
    ``ok-open-all`` / ``ok-weekday-closed`` (schedule produced) or ``empty`` /
    ``no-window`` / ``multiple-windows`` / ``irregular-closure`` /
    ``partial-closure`` / ``no-closure-info`` (raw fallback).
    """
    if not raw or not raw.strip():
        return HoursParse(raw, None, None, (), "none", "empty")

    t = norm(raw)

    wins = _windows(t)
    if not wins:
        return HoursParse(raw, None, None, (), "none", "no-window")
    if len(wins) > 1:
        return HoursParse(raw, None, None, (), "none", "multiple-windows")
    opens, closes = _hhmm(wins[0][0]), _hhmm(wins[0][1])
    window = (opens, closes)

    if _IRREGULAR.search(t):
        return HoursParse(raw, None, window, (), "none", "irregular-closure")

    closed, note, partial = _closed_days(t)
    if partial:
        return HoursParse(raw, None, window, (), "none", "partial-closure", note)
    if closed is None:
        return HoursParse(raw, None, window, (), "none", "no-closure-info")

    schedule = _build_schedule(opens, closes, closed)
    reason = "ok-open-all" if not closed else "ok-weekday-closed"
    return HoursParse(raw, schedule, window, tuple(closed), "high", reason, note)


# Publish policy (NOT a parse fact): an onsen with no business-hours text at all
# is treated as open 24/7. `parse_hours` stays honest — it reports `empty`/None;
# this default is applied only in the published projection below.
_ALL_DAY = {"opens": "00:00", "closes": "24:00"}


def parsed_hours_doc(raw: str | None) -> dict:
    """Project to the app's published `ParsedHours`: {"raw", "schedule"}.

    `raw` is the verbatim source text (the app shows it under the grid). The
    schedule is:
      - the parsed app-shaped WeeklySchedule (null day = closed), when the text
        is unambiguous (single window + 無休/explicit weekday closure);
      - a **24/7** schedule (every day 00:00–24:00) when there is NO hours text
        at all — per the catalog policy that an onsen with no posted hours is
        always open;
      - None otherwise (hours present but irregular/multi-window/partial) — the
        app falls back to showing `raw`.

    This is what the catalog publisher writes to `businessHours` on
    /onsens/{kyuhachiId} (see publisher/apply.py + backfill_schedule.py).
    """
    if raw is None or not raw.strip():
        return {"raw": "", "schedule": {d: dict(_ALL_DAY) for d in DAYS}}
    return {"raw": raw, "schedule": parse_hours(raw).schedule}


# --- last entry (最終受付) ---------------------------------------------------- #
# 88onsen states a last-entry cutoff inline in `business_hours`, e.g.
# `…（最終受付21:00）` — a bath can stop accepting entries well before it closes.
# It is otherwise invisible to the app (folded into `raw` / "show original text"),
# so the catalog surfaces it as a published exception caption (docs/hours-schema.md).
# These helpers DETECT that cutoff and format the one standard bilingual caption;
# like the rest of this module they never author the published *schedule*. They
# back a validation guard (recurate-hours / pytest) that the curated exceptions
# actually carry the cutoff, so a future re-curation can't silently re-bury it.
# Per-bath / per-day cutoffs (multiple times, 大風呂/家族風呂, 土日祝…) return None
# and are curated by hand.
_LAST_ENTRY = "最終受付"
_LE_TIME = re.compile(r"(\d{1,2}):(\d{2})")
_LE_COMPLEX = re.compile(r"[、，,]|大風呂|家族風呂|内湯|露天|土日祝|平日|但し|ただし|以降|[~〜]\s*\d")


def single_last_entry(raw: str | None) -> str | None:
    """The one clean last-entry time (`HH:MM`, zero-padded) stated in `raw`, else None.

    Returns a time only when the text states exactly one `最終受付` cutoff with no
    per-bath/per-day complication; None when there is no cutoff or it varies (those
    are hand-curated). Detection only — never authors the published schedule.
    """
    n = norm(raw)
    if _LAST_ENTRY not in n:
        return None
    m = re.search(_LAST_ENTRY + r"[^\n]*", n)
    seg = re.split(r"[）)]", m.group(0), 1)[0]
    if _LE_COMPLEX.search(seg):
        return None
    times = _LE_TIME.findall(seg)
    if len(times) != 1:
        return None
    h, mm = times[0]
    return f"{int(h):02d}:{mm}"


def last_entry_caption(raw: str | None) -> dict | None:
    """The standard bilingual `{en, ja}` last-entry caption for `raw`, or None.

    The single source of the `最終受付` → caption wording (docs/hours-schema.md):
    used to validate that a curated entry surfaces the cutoff, and available for a
    future recurate-hours pass to propose it. None when the cutoff isn't a clean
    single time — curate those by hand (e.g. a per-bath split like hid 57).
    """
    t = single_last_entry(raw)
    if t is None:
        return None
    return {"en": f"Last entry by {t}", "ja": f"{_LAST_ENTRY} {t}"}
