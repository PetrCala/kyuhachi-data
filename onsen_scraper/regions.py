"""Coarse tourism-region model for the app's "area guides" feature.

Rolls the ~100 fine-grained 88onsen `onsen_area_name` districts up into a small
set of tourism-meaningful **regions**, and assigns every region a stable
`areaId` (UUID) this repo owns, exactly like `kyuhachiId` for onsens. The app
never sees upstream 88onsen ids; it reads only the published `areaId`.

Two layers of taxonomy live here:

  * `REGIONS`: the ordered region catalog, `key → {label, prefecture}`. `key`
    (e.g. ``"oita-beppu"``) is the human-readable join key used across the three
    data files (`area-id-map.json`, `area-regions.json`, `area_guides_curated.json`).
    `label` is an English review aid; the *published* bilingual name/tagline live
    in the curated content file, never here.
  * The assignment rule (`region_for`):
      - **Single-region prefectures** (`PREFECTURE_REGION`): Fukuoka, Saga,
        Nagasaki, Miyazaki, Kagoshima each roll up to one region. Any onsen in the
        prefecture maps deterministically, including onsens added later.
      - **Split prefectures** (`AREA_REGION`): Oita (42 onsens) and Kumamoto (30)
        are large and contain famous, unambiguous sub-regions (Beppu, Yufuin, Aso,
        Hitoyoshi…), so they split by `onsen_area_name`. A novel area name in a
        split prefecture returns `None` (unassigned) rather than guessing; the
        maintainer adds it to `AREA_REGION` and re-runs. This is the honest analog
        of a missing `kyuhachiId`: surfaced, never silently mis-placed.

Why not the 7 prefectures flat, or the ~100 area names flat? Prefectures are
administrative, not always tourism-coherent (Oita bundles Beppu with the Kuju
highlands); the area names are far too granular to author evergreen guides for.
The split above keeps assignment 100% deterministic and reviewable: every
member onsen is listed in `data/area-regions.json` for a human to check.

`region_for` is pure stdlib and dependency-free (like `fees`/`readings`), so
`publisher/apply.py`'s `add` path and `publisher/backfill_area_id.py` can both
import it without the scraping stack. The DB-reading builder (`build_region_model`,
the CLI) is used only to (re)generate the data files.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SNAPSHOT_DB = REPO / "data" / "snapshot.db"
IDMAP_PATH = REPO / "data" / "onsen-id-map.json"
AREA_ID_MAP_PATH = REPO / "data" / "area-id-map.json"
AREA_REGIONS_PATH = REPO / "data" / "area-regions.json"

# The area_guides publish is versioned like the catalog (area_guides_meta/current).
MODEL_VERSION = 1


# --- region catalog -----------------------------------------------------------
# Ordered: Oita → Kumamoto → the single-region prefectures. `label` is an English
# review aid only; the published name/tagline are authored in the curated file.
REGIONS: dict[str, dict] = {
    # 大分県: split (42 onsens). Japan's onsen heartland, several distinct draws.
    "oita-beppu":     {"label": "Beppu",                      "prefecture": "大分県"},
    "oita-yufuin":    {"label": "Yufuin & Yufu",              "prefecture": "大分県"},
    "oita-kuju":      {"label": "Kuju Highlands & Taketa",    "prefecture": "大分県"},
    "oita-hita":      {"label": "Hita, Kokonoe & Yabakei",    "prefecture": "大分県"},
    "oita-kunisaki":  {"label": "Kunisaki Peninsula & Usa",   "prefecture": "大分県"},
    # 熊本県: split (30 onsens). The Aso volcano, the northern plain, the deep
    # south (Hitoyoshi) and the west coast (Amakusa) are separate tourism worlds.
    "kumamoto-aso":       {"label": "Aso & Oguni Highlands",         "prefecture": "熊本県"},
    "kumamoto-yamaga-kikuchi": {"label": "Yamaga & Kikuchi",         "prefecture": "熊本県"},
    "kumamoto-hitoyoshi": {"label": "Hitoyoshi & Kuma",              "prefecture": "熊本県"},
    "kumamoto-amakusa":   {"label": "Amakusa & Ashikita Coast",      "prefecture": "熊本県"},
    # Single-region prefectures: coherent enough at prefecture scale for now.
    "fukuoka":   {"label": "Fukuoka",   "prefecture": "福岡県"},
    "saga":      {"label": "Saga",      "prefecture": "佐賀県"},
    "nagasaki":  {"label": "Nagasaki",  "prefecture": "長崎県"},
    "miyazaki":  {"label": "Miyazaki",  "prefecture": "宮崎県"},
    "kagoshima": {"label": "Kagoshima", "prefecture": "鹿児島県"},
}

# Single-region prefectures → their one region key.
PREFECTURE_REGION: dict[str, str] = {
    "福岡県": "fukuoka",
    "佐賀県": "saga",
    "長崎県": "nagasaki",
    "宮崎県": "miyazaki",
    "鹿児島県": "kagoshima",
}

# Split prefectures → {normalized onsen_area_name: region key}. Keyed by the
# *normalized* area name (notice suffixes stripped; see normalize_area_name), so
# a source name carrying a temporary closure notice still assigns. Every area name
# present in the current snapshot is covered; add new ones here as they appear.
AREA_REGION: dict[str, dict[str, str]] = {
    "大分県": {
        # Beppu Bay corridor (Beppu Eight + Oita City).
        "別府温泉": "oita-beppu", "鉄輪温泉": "oita-beppu", "明礬温泉": "oita-beppu",
        "亀川温泉": "oita-beppu", "浜脇温泉": "oita-beppu", "高崎山温泉": "oita-beppu",
        "府内温泉": "oita-beppu", "賀来温泉": "oita-beppu", "生石温泉": "oita-beppu",
        "丹生温泉": "oita-beppu",
        # Yufuin basin.
        "由布院温泉": "oita-yufuin", "塚原温泉": "oita-yufuin", "湯平温泉": "oita-yufuin",
        # Kuju highlands + Taketa (carbonated springs, mountain huts).
        "長湯温泉": "oita-kuju", "七里田温泉": "oita-kuju", "赤川温泉": "oita-kuju",
        "筋湯温泉": "oita-kuju", "筌の口温泉": "oita-kuju", "星生温泉": "oita-kuju",
        "法華院温泉": "oita-kuju", "九酔渓温泉": "oita-kuju", "赤松温泉": "oita-kuju",
        # Hita basin + Kokonoe + Yabakei gorge (western Oita).
        "天ヶ瀬温泉": "oita-hita", "夜明温泉": "oita-hita", "壁湯天然洞窟温泉": "oita-hita",
        "川底温泉": "oita-hita", "深耶馬渓温泉": "oita-hita",
        # Kunisaki peninsula + Usa + Kitsuki.
        "くにさき六郷温泉": "oita-kunisaki", "山香温泉": "oita-kunisaki", "夷谷温泉": "oita-kunisaki",
    },
    "熊本県": {
        # Aso caldera + Oguni/Waita highlands (incl. Kurokawa).
        "阿蘇内牧温泉": "kumamoto-aso", "地獄温泉": "kumamoto-aso", "垂玉温泉": "kumamoto-aso",
        "大阿蘇　火の山温泉": "kumamoto-aso", "岳の湯温泉": "kumamoto-aso",
        "小田温泉": "kumamoto-aso", "黒川温泉": "kumamoto-aso", "杖立温泉": "kumamoto-aso",
        # Northern Kumamoto plain (Yamaga, Kikuchi, Tamana belt).
        "山鹿温泉": "kumamoto-yamaga-kikuchi", "平山温泉": "kumamoto-yamaga-kikuchi",
        "植木温泉": "kumamoto-yamaga-kikuchi", "菊池温泉": "kumamoto-yamaga-kikuchi",
        "泗水温泉": "kumamoto-yamaga-kikuchi", "三加和温泉": "kumamoto-yamaga-kikuchi",
        "亀の甲温泉": "kumamoto-yamaga-kikuchi", "宝田温泉": "kumamoto-yamaga-kikuchi",
        "辰頭温泉": "kumamoto-yamaga-kikuchi", "日平温泉": "kumamoto-yamaga-kikuchi",
        # Hitoyoshi-Kuma basin (deep south).
        "人吉温泉": "kumamoto-hitoyoshi",
        # Yatsushiro-Ashikita-Minamata-Amakusa coast (southwest).
        "日奈久温泉": "kumamoto-amakusa", "湯浦温泉": "kumamoto-amakusa",
        "湯の鶴温泉": "kumamoto-amakusa", "湯の児温泉": "kumamoto-amakusa",
        "下田温泉": "kumamoto-amakusa", "弓ヶ浜温泉": "kumamoto-amakusa",
    },
}

# Whitespace-appended source notices carry a date or one of these keywords.
_NOTICE_KEYWORDS = (
    "営業時間", "メンテナンス", "休館", "中止", "改定", "変更", "注意", "設定",
    "予約", "お知らせ", "臨時", "案内",
)
_WS_RUN = re.compile(r"[ 　]+")
_DIGIT = re.compile(r"[0-9０-９]")


def normalize_area_name(name: str | None) -> str | None:
    """Strip an appended source notice from an `onsen_area_name`, if present.

    88onsen sometimes tacks a temporary closure/notice onto the area name after a
    space run, e.g. ``青井岳温泉　　２０２６年…メンテナンス休館``. We cut at the first
    space run that is followed by a date (fullwidth/ascii digit) or a notice
    keyword, and leave genuine multi-token names intact (``大阿蘇　火の山温泉`` has a
    space but no digit/keyword after it, so it is preserved). Idempotent.
    """
    if not name:
        return name
    s = name.strip()
    for m in _WS_RUN.finditer(s):
        tail = s[m.end():]
        if _DIGIT.search(tail) or any(k in tail for k in _NOTICE_KEYWORDS):
            return s[: m.start()].strip()
    return s


def region_for(area_name: str | None, prefecture: str | None) -> str | None:
    """The region `key` an onsen rolls up into, or `None` if unassigned.

    Single-region prefectures map by prefecture (works for any onsen, including
    ones added later). Split prefectures map by normalized area name; a novel area
    name returns `None` so the maintainer assigns it explicitly rather than the
    onsen being silently mis-placed.
    """
    if prefecture in AREA_REGION:
        return AREA_REGION[prefecture].get(normalize_area_name(area_name))
    return PREFECTURE_REGION.get(prefecture)


# --- stable areaId ledger -----------------------------------------------------

def load_area_id_map() -> dict[str, str]:
    """`{regionKey: areaId}` from data/area-id-map.json (`{}` if it doesn't exist).

    Mirrors `data/onsen-id-map.json`: the stable id ledger, hand/tool-owned, never
    regenerated for an existing key. The `_meta` key (if present) is ignored.
    """
    if not AREA_ID_MAP_PATH.exists():
        return {}
    data = json.loads(AREA_ID_MAP_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if k != "_meta"}


def area_id_for(region_key: str | None) -> str | None:
    """The stable `areaId` for a region key, or `None` if the key has no id yet."""
    if region_key is None:
        return None
    return load_area_id_map().get(region_key)


def mint_missing_area_ids(*, commit: bool = False) -> dict[str, str]:
    """Ensure every `REGIONS` key has an `areaId`, minting UUIDs for any missing.

    Returns the (possibly extended) `{regionKey: areaId}` map. Existing ids are
    preserved verbatim. With `commit=True` the extended ledger is written back to
    data/area-id-map.json (sorted by the REGIONS order); otherwise it is only
    returned so a dry-run can report what it would mint. A key is never removed;
    a retired region keeps its id, matching "ids are never reassigned".
    """
    current = load_area_id_map()
    minted = dict(current)
    for key in REGIONS:
        if key not in minted:
            minted[key] = str(uuid.uuid4())
    if commit and minted != current:
        ordered = {k: minted[k] for k in REGIONS if k in minted}
        # Preserve any ledger keys not in REGIONS (retired regions) at the end.
        ordered.update({k: v for k, v in minted.items() if k not in ordered})
        payload = {
            "_meta": {
                "schema": "regionKey → areaId (UUID). The stable id ledger for the "
                          "area-guides feature; mirrors data/onsen-id-map.json. Ids "
                          "are assigned once and never changed or reused; a retired "
                          "region keeps its id. Region membership + centroids live in "
                          "data/area-regions.json, editorial content in "
                          "data/area_guides_curated.json.",
            },
            **ordered,
        }
        AREA_ID_MAP_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return minted


# --- region model builder -----------------------------------------------------

def _load_onsens() -> list[tuple]:
    con = sqlite3.connect(f"file:{SNAPSHOT_DB}?mode=ro", uri=True)
    try:
        return con.execute(
            "select id, onsen_area_name, prefecture, latitude, longitude "
            "from onsens order by id"
        ).fetchall()
    finally:
        con.close()


def build_region_model() -> dict:
    """Compute the full region model from the snapshot + id maps (read-only).

    Returns `{"version", "regions": [...], "unassigned": [...]}`. Each region carries
    its stable `areaId` (from the ledger), `label`, `prefecture`, the centroid
    `center` (arithmetic mean of member lat/lng), and member lists (`memberOnsenIds`
    = kyuhachiIds, plus `memberHids`/`memberAreaNames` for review). `unassigned`
    lists any onsen whose (area, prefecture) `region_for` could not place: a
    reviewer signal, never a silent drop.
    """
    idmap = json.loads(IDMAP_PATH.read_text(encoding="utf-8"))
    area_ids = mint_missing_area_ids()  # dry: just resolve ids for the model
    buckets: dict[str, dict] = {
        key: {"hids": [], "kids": [], "area_names": set(), "lat": [], "lng": []}
        for key in REGIONS
    }
    unassigned = []
    for hid, area, pref, lat, lng in _load_onsens():
        key = region_for(area, pref)
        kid = idmap.get(str(hid))
        if key is None or key not in buckets:
            unassigned.append({"hid": hid, "kyuhachiId": kid,
                               "areaName": area, "prefecture": pref})
            continue
        b = buckets[key]
        b["hids"].append(hid)
        if kid:
            b["kids"].append(kid)
        b["area_names"].add(normalize_area_name(area))
        if lat is not None and lng is not None:
            b["lat"].append(lat)
            b["lng"].append(lng)

    regions = []
    for key, meta in REGIONS.items():
        b = buckets[key]
        center = None
        if b["lat"]:
            center = {"lat": round(sum(b["lat"]) / len(b["lat"]), 6),
                      "lng": round(sum(b["lng"]) / len(b["lng"]), 6)}
        regions.append({
            "key": key,
            "areaId": area_ids.get(key),
            "label": meta["label"],
            "prefecture": meta["prefecture"],
            "center": center,
            "memberCount": len(b["hids"]),
            "memberOnsenIds": sorted(b["kids"]),
            "memberHids": sorted(b["hids"]),
            "memberAreaNames": sorted(b["area_names"]),
        })
    return {"version": MODEL_VERSION, "regions": regions, "unassigned": unassigned}


def write_region_model(model: dict) -> None:
    payload = {
        "_meta": {
            "schema": "Generated region model for the area-guides feature. One entry "
                      "per region: stable areaId (from data/area-id-map.json), English "
                      "label, prefecture, center (centroid of member onsen lat/lng), and "
                      "member lists (memberOnsenIds = published kyuhachiIds; memberHids / "
                      "memberAreaNames for human review). Regenerate with "
                      "`python -m onsen_scraper.regions --build` after a catalog change. "
                      "Editorial name/tagline/sections live in data/area_guides_curated.json.",
            "generatedBy": "onsen_scraper.regions.build_region_model",
        },
        **model,
    }
    AREA_REGIONS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Region model builder for area guides.")
    ap.add_argument("--build", action="store_true",
                    help="mint any missing areaIds and (re)write data/area-regions.json")
    args = ap.parse_args()

    minted = mint_missing_area_ids(commit=args.build)
    new_ids = [k for k in REGIONS if k not in load_area_id_map()]
    model = build_region_model()

    print(f"regions: {len(REGIONS)}   "
          f"onsens placed: {sum(r['memberCount'] for r in model['regions'])}   "
          f"unassigned: {len(model['unassigned'])}")
    if new_ids:
        verb = "minted" if args.build else "would mint"
        print(f"areaIds {verb}: {new_ids}")
    for r in model["regions"]:
        c = r["center"]
        cs = f"{c['lat']:.4f},{c['lng']:.4f}" if c else "(none)"
        print(f"  {r['key']:<26} {r['memberCount']:>2} onsens  "
              f"center={cs:<20} {r['label']}")
    if model["unassigned"]:
        print("\n!! UNASSIGNED onsens (add their area name to AREA_REGION):")
        for u in model["unassigned"]:
            print(f"   hid={u['hid']} {u['prefecture']} / {u['areaName']!r}")

    if args.build:
        write_region_model(model)
        print(f"\nwrote {AREA_REGIONS_PATH.relative_to(REPO)} "
              f"(and minted ids into {AREA_ID_MAP_PATH.relative_to(REPO)})")
    else:
        print(f"\nDry-run: nothing written. Re-run with --build to (re)generate "
              f"{AREA_REGIONS_PATH.name} + {AREA_ID_MAP_PATH.name}.")


if __name__ == "__main__":
    _main()
