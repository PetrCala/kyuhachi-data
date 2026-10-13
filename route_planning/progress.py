#!/usr/bin/env python3
"""Where am I on the line, and what is my skip budget? Reads the public journey data.

The app publishes the walk without sign-in (Firestore rules in the kyuhachi repo):

    /journey_days                               one walked day per doc, track as an
                                                encoded polyline
    /users/<JOURNEY_UID>/challenges             the default challenge is the walk
    /users/<JOURNEY_UID>/challenges/<id>/visits one doc per onsen entered (id = kyuhachiId)
    /onsens                                     isActive: a retired onsen never counts

This joins them onto the committed line (`final_route/00_full_route.gpx`) and the
snapped stops (`handdrawn_loop_analysis.json`, hid in `id`; `data/onsen-id-map.json`
turns a kyuhachiId back into a hid) and prints: the position along the line, which
stops are behind (entered or walked past), what is ahead, how many entries are still
needed for the target, the skip budget that leaves and the hit rate it implies, and
any stop ahead the catalog has retired. `--replan` then runs `plan_octnov` from that
position and date and writes `plan_from_<date>.md` (gitignored).

    python route_planning/progress.py                 # where am I
    python route_planning/progress.py --replan        # ...and re-plan the rest from here
    python route_planning/progress.py --entered=19    # the phone has visits not yet synced
    python route_planning/progress.py --offline       # reuse cache/firestore/*.json

Options: --pos-km=KM (override the track), --date=YYYY-MM-DD (re-plan start, default
today JST), --walking-day=N (default: walked days + 1), --wait=MIN (door wait
tolerance), --target=N (default config.TARGET_VISITS), --out=STEM.

Reads only. Never writes Firestore, the snapshot DB, or the carried plan.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import config  # noqa: E402
import plan_octnov  # noqa: E402
from geo import load_track, nearest_on_track  # noqa: E402
from onsen_model import short_pref  # noqa: E402

ANALYSIS = HERE / "handdrawn_loop_analysis.json"
ID_MAP = config.REPO / "data" / "onsen-id-map.json"
CACHE = config.CACHE_DIR / "firestore"
BASE = (f"https://firestore.googleapis.com/v1/projects/{config.FIREBASE_PROJECT}"
        "/databases/(default)/documents")
JST = timezone(timedelta(hours=9))


def fv(v: dict):
    """A Firestore REST value → Python."""
    ((kind, x),) = v.items()
    if kind == "integerValue":
        return int(x)
    if kind == "arrayValue":
        return [fv(i) for i in x.get("values", [])]
    if kind == "mapValue":
        return {k: fv(w) for k, w in x.get("fields", {}).items()}
    if kind == "nullValue":
        return None
    return x


def fetch(path: str, offline: bool = False, mask: tuple[str, ...] = ()) -> list[dict]:
    """Every document of a collection as {id, **fields}; cached under cache/firestore/."""
    cache = CACHE / (path.strip("/").replace("/", "_") + ".json")
    if offline:
        return json.loads(cache.read_text(encoding="utf-8"))
    docs: list[dict] = []
    token = None
    while True:
        q = {"pageSize": "300"}
        if token:
            q["pageToken"] = token
        qs = urllib.parse.urlencode(q) + "".join(f"&mask.fieldPaths={m}" for m in mask)
        with urllib.request.urlopen(f"{BASE}/{path}?{qs}", timeout=60) as r:
            page = json.loads(r.read())
        for d in page.get("documents", []):
            docs.append({"id": d["name"].rsplit("/", 1)[1],
                         **{k: fv(v) for k, v in d.get("fields", {}).items()}})
        token = page.get("nextPageToken")
        if not token:
            break
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    return docs


def decode_polyline(s: str) -> list[tuple[float, float]]:
    """Google encoded polyline (5 decimals) → [(lat, lon), ...]."""
    out: list[tuple[float, float]] = []
    idx = lat = lng = 0
    while idx < len(s):
        vals = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(s[idx]) - 63
                idx += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            vals.append(~(result >> 1) if result & 1 else result >> 1)
        lat += vals[0]
        lng += vals[1]
        out.append((lat / 1e5, lng / 1e5))
    return out


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    opts = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in args if "=" in a}
    offline = "--offline" in args
    target = int(opts.get("--target", config.TARGET_VISITS))

    stops = json.loads(ANALYSIS.read_text(encoding="utf-8"))["stops"]
    by_hid = {s["id"]: s for s in stops}
    hid_of = {v: int(k) for k, v in json.loads(ID_MAP.read_text(encoding="utf-8")).items()}
    kid_of = {v: k for k, v in hid_of.items()}

    days = sorted(fetch("journey_days", offline), key=lambda d: d["date"])
    challenges = fetch(f"users/{config.JOURNEY_UID}/challenges", offline)
    challenge = next((c for c in challenges if c.get("isDefault")), None)
    visits = (fetch(f"users/{config.JOURNEY_UID}/challenges/{challenge['id']}/visits", offline)
              if challenge else [])
    live = {o["id"]: o for o in fetch("onsens", offline,
                                      mask=("isActive", "name", "areaName", "prefecture"))}

    # --- position: the end of the latest walked track, snapped to the line ----------
    lat, lon, cum = load_track(config.FULL_ROUTE_GPX)
    if "--pos-km" in opts:
        pos_km, pos_src = float(opts["--pos-km"]), "--pos-km"
    elif days:
        last = days[-1]
        end = decode_polyline(last["polyline"])[-1]
        off, pos_km = nearest_on_track(end[0], end[1], lat, lon, cum)
        pos_src = f"end of the {last['date']} track, {off:.2f} km off the line"
    else:
        pos_km, pos_src = 0.0, "no walked day published yet"

    # --- visits → stops ------------------------------------------------------------
    visited: dict[int, str] = {}      # order -> visitedAt
    off_route: list[dict] = []
    for v in visits:
        s = by_hid.get(hid_of.get(v["id"]))
        if s:
            visited[s["order"]] = v.get("visitedAt") or ""
        else:
            off_route.append(v)
    entered = int(opts.get("--entered", len(visits)))
    last_visited = max(visited) if visited else 0
    passed_by_km = sum(1 for s in stops if s["along_km"] <= pos_km + 0.3)
    behind = max(last_visited, passed_by_km)
    skipped_behind = [s for s in stops if s["order"] <= behind and s["order"] not in visited]
    skipped = int(opts.get("--skipped", len(skipped_behind)))
    ahead = [s for s in stops if s["order"] > behind]
    buffer = [s for s in ahead if s.get("is_buffer")]
    need = max(0, target - entered)
    prefs = {stops[o - 1]["pref_short"] for o in visited}
    prefs |= {short_pref(live[v["id"]]["prefecture"]) for v in off_route if v["id"] in live}
    retired = [s for s in ahead if live.get(kid_of.get(s["id"]), {}).get("isActive") is False]
    pref_left: dict[str, int] = {}
    for s in ahead:
        pref_left[s["pref_short"]] = pref_left.get(s["pref_short"], 0) + 1

    today = datetime.now(JST).date()
    print(f"as of {today} JST · {len(days)} walked days published, "
          f"{sum(d['distanceMeters'] for d in days) / 1000:.0f} km recorded")
    print(f"position: km {pos_km:.1f} of {cum[-1]:.0f} ({pos_src})")
    print(f"behind: {behind} stops · entered {len(visited)} on the line"
          + (f" + {len(off_route)} off it" if off_route else "")
          + f" · walked past {len(skipped_behind)}: "
          + (", ".join(f"#{s['order']} {s['area']}" for s in skipped_behind) or "none"))
    if last_visited != passed_by_km:
        print(f"  (last entered stop #{last_visited}, {passed_by_km} stops lie before the track end; "
              f"using {behind})")
    if entered != len(visits):
        print(f"  entered overridden: {entered} (the app has {len(visits)} synced)")
    print(f"ahead: {len(ahead)} stops ({len(ahead) - len(buffer)} core + {len(buffer)} optional buffer), "
          f"{sum(1 for s in ahead if s.get('irregular'))} of them 不定休")
    print(f"target {target}: entered {entered}, skipped {skipped}, still needed {need}")
    print(f"skip budget: {len(ahead) - need} of the {len(ahead)} ahead "
          f"({len(ahead) - len(buffer) - need} without the buffer detours) · "
          f"required hit rate {need / len(ahead):.1%}" if ahead else "nothing ahead")
    print(f"prefectures collected: {' '.join(sorted(prefs)) or 'none'} · stops ahead per prefecture: "
          + " ".join(f"{p}×{n}" for p, n in sorted(pref_left.items(), key=lambda x: x[1])))
    print("retired in the catalog, ahead: "
          + (", ".join(f"#{s['order']} {s['area']}：{s['name']}" for s in retired) or "none"))

    if "--replan" not in args:
        return
    start = plan_octnov.Start(
        date=date.fromisoformat(opts["--date"]) if "--date" in opts else today,
        km=max(pos_km, stops[behind - 1]["along_km"] if behind else 0.0),
        next_order=behind + 1,
        walking_day=int(opts.get("--walking-day", len(days) + 1)),
        prefs_done=tuple(sorted(prefs)),
    )
    stem = opts.get("--out", f"plan_from_{start.date}")
    p = plan_octnov.run_plan(
        tol=int(opts.get("--wait", plan_octnov.WAIT_TOLERANCE_MIN)), start=start,
        out_md=HERE / f"{stem}.md", out_json=HERE / f"{stem}.json")
    t = p["totals"]
    reached = None
    n = entered
    for d in p["days"]:
        n += sum(1 for e in d["events"] if e["status"] == "VISIT")
        if n >= target and reached is None:
            reached = d["date"]
    print(f"\nre-plan from km {start.km:.1f}, #{start.next_order}, {start.date} (walking day "
          f"{start.walking_day}): {t['visited']} planned visits of {len(ahead)} → "
          f"{entered + t['visited']} total if every planned door is open · target reached "
          f"{reached or 'never'} · finish {t['finish']} · {t['slack_days']} days of slack to "
          f"{t['deadline']}")
    print(f"the plan itself skips {t['skipped_closed']} closed + {t['skipped_late']} late + "
          f"{t['skipped_early']} early, leaving {entered + t['visited'] - target} for surprises")
    print(f"wrote {stem}.md + {stem}.json")


if __name__ == "__main__":
    main()
