#!/usr/bin/env python3
"""Fetch the user's full Strava Walk/Hike history and summarize walking speed.

Reads OAuth creds from the onsendo repo's .env + token.json, refreshes the
access token (writing the rotated token back so onsendo keeps working), pulls
all activities, and reports a moving-speed distribution for foot activities.

Read-only with respect to onsen data; the only file it writes is the rotated
Strava token (back to its original path) and a JSON summary in this dir.
"""
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ONSENDO = Path(os.path.expanduser("~/code/onsendo"))
OUT = Path(__file__).resolve().parent / "strava_walk_summary.json"


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def http_post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def http_get(url: str, token: str) -> list:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main() -> int:
    env = load_env(ONSENDO / ".env")
    cid = env["STRAVA_CLIENT_ID"]
    secret = env["STRAVA_CLIENT_SECRET"]
    token_path = ONSENDO / env.get("STRAVA_TOKEN_PATH", "local/strava/token.json")
    tok = json.loads(token_path.read_text())

    # Refresh access token (Strava rotates the refresh_token; persist it back).
    refreshed = http_post(
        "https://www.strava.com/oauth/token",
        {
            "client_id": cid,
            "client_secret": secret,
            "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"],
        },
    )
    new_tok = {
        "access_token": refreshed["access_token"],
        "refresh_token": refreshed["refresh_token"],
        "expires_at": refreshed["expires_at"],
        "token_type": refreshed.get("token_type", "Bearer"),
    }
    token_path.write_text(json.dumps(new_tok, indent=2))
    os.chmod(token_path, 0o600)
    access = new_tok["access_token"]
    print(f"Token refreshed; new expiry epoch {new_tok['expires_at']}", file=sys.stderr)

    # Page through all activities.
    acts = []
    page = 1
    while True:
        batch = http_get(
            f"https://www.strava.com/api/v3/athlete/activities?per_page=200&page={page}",
            access,
        )
        if not batch:
            break
        acts.extend(batch)
        page += 1
        if page > 30:  # safety
            break
    print(f"Fetched {len(acts)} total activities", file=sys.stderr)

    # Distinct types present, for transparency.
    from collections import Counter

    types = Counter(a.get("type") for a in acts)

    foot_types = {"Walk", "Hike"}
    rows = []
    for a in acts:
        if a.get("type") not in foot_types:
            continue
        dist_m = a.get("distance") or 0
        moving = a.get("moving_time") or 0  # seconds
        elapsed = a.get("elapsed_time") or 0
        if dist_m <= 0 or moving <= 0:
            continue
        kmh_moving = (dist_m / 1000.0) / (moving / 3600.0)
        kmh_elapsed = (dist_m / 1000.0) / (elapsed / 3600.0) if elapsed else None
        rows.append(
            {
                "name": a.get("name"),
                "type": a.get("type"),
                "date": a.get("start_date_local"),
                "dist_km": round(dist_m / 1000.0, 2),
                "moving_min": round(moving / 60.0, 1),
                "elapsed_min": round(elapsed / 60.0, 1),
                "elev_gain_m": a.get("total_elevation_gain"),
                "kmh_moving": round(kmh_moving, 2),
                "kmh_elapsed": round(kmh_elapsed, 2) if kmh_elapsed else None,
            }
        )

    def pctiles(vals):
        s = sorted(vals)
        n = len(s)
        if n == 0:
            return {}

        def p(q):
            k = (n - 1) * q
            f = int(k)
            c = min(f + 1, n - 1)
            return s[f] + (s[c] - s[f]) * (k - f)

        return {
            "n": n,
            "min": round(s[0], 2),
            "p25": round(p(0.25), 2),
            "median": round(p(0.5), 2),
            "mean": round(statistics.mean(s), 2),
            "p75": round(p(0.75), 2),
            "p90": round(p(0.9), 2),
            "max": round(s[-1], 2),
        }

    # Distance-weighted aggregate moving speed (best single estimate of sustained pace).
    tot_km = sum(r["dist_km"] for r in rows)
    tot_moving_h = sum(r["moving_min"] for r in rows) / 60.0
    agg_moving = tot_km / tot_moving_h if tot_moving_h else None

    summary = {
        "activity_type_counts": dict(types),
        "foot_activity_count": len(rows),
        "total_foot_km": round(tot_km, 1),
        "total_moving_hours": round(tot_moving_h, 1),
        "aggregate_moving_kmh": round(agg_moving, 2) if agg_moving else None,
        "moving_kmh_dist": pctiles([r["kmh_moving"] for r in rows]),
        "elapsed_kmh_dist": pctiles([r["kmh_elapsed"] for r in rows if r["kmh_elapsed"]]),
        "longest_walks": sorted(rows, key=lambda r: -r["dist_km"])[:15],
        "all_rows": sorted(rows, key=lambda r: r["date"] or ""),
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    print(json.dumps({k: v for k, v in summary.items() if k not in ("all_rows", "longest_walks")},
                     ensure_ascii=False, indent=2))
    print("\nLongest walks (km / moving_min / elev_m / kmh_moving / kmh_elapsed):")
    for r in summary["longest_walks"]:
        print(f"  {r['dist_km']:>6.1f}km {r['moving_min']:>6.0f}min "
              f"{(r['elev_gain_m'] or 0):>5.0f}m  {r['kmh_moving']:.2f} / "
              f"{r['kmh_elapsed'] if r['kmh_elapsed'] else '--'}")
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
