#!/usr/bin/env python3
"""
publish-area-guides: publish the /area_guides/{areaId} collection and bump the
/area_guides_meta/current version doc.

Reads the region model (`data/area-regions.json`: the stable `areaId` + the
`center` centroid per region) and the curated editorial content
(`data/area_guides_curated.json`: bilingual `name`, optional `tagline`, and the
ordered `sections`), joins them, and writes one `/area_guides/{areaId}` document
per region, then upserts `/area_guides_meta/current` with a monotonically
increasing `version`, `publishedAt`, and `totalCount`. Mirrors the catalog's
versioned-publish pattern: additive MERGE writes, dry-run by default, `--commit`
to write, idempotent (a re-run with unchanged content writes nothing and does not
bump the version).

This is the data repo's half of the app's "area guides" feature (app ADR-008):
evergreen, time-agnostic tourist info (specialties, produce, attractions, history,
culture) for the coarse region a user is in. Every user-facing string is bilingual
`{en, ja}` by design. `areaId` is a stable id this repo owns (see
`onsen_scraper.regions`); the join field `areaId` on `/onsens` is written by
`publisher/backfill_area_id.py`.

Human-review gate: the curated content is user-facing, so `--commit` is refused
while `data/area_guides_curated.json`'s `_meta.reviewStatus` is not `"reviewed"`.
A dry-run always runs (and prints the plan) so the content can be proofed; flip
`reviewStatus` to `"reviewed"` only after a human has verified every claim.

Retired regions: unlike onsens, area guides carry no soft-delete flag. A region
dropped from the curated source is simply no longer published; any lingering live
doc for it is reported here as an orphan and removed only with `--prune`.

Auth: gcloud Application Default Credentials (same as `publisher/apply.py`).
Run `gcloud auth application-default login` if 401. A dry-run reads live to report
what would change vs. is already current; with no auth it degrades to the offline
plan (every guide counted as a change) instead of erroring.

Usage:
  python publisher/publish_area_guides.py            # dry-run (default): print plan, write nothing
  python publisher/publish_area_guides.py --commit    # write the guides + bump the version doc
  python publisher/publish_area_guides.py --commit --prune   # also delete orphaned live guides
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from firestore_rest import (  # noqa: E402
    BASE, PROJECT, dval, fetch_collection, field_at, get_fields, ival, patch,
    sval, token, _open,
)
import urllib.request  # noqa: E402

AREA_REGIONS = REPO / "data" / "area-regions.json"
CURATED = REPO / "data" / "area_guides_curated.json"

# Canonical section order; only kinds present in the curated content are published.
SECTION_ORDER = ["specialties", "produce", "attractions", "history", "culture"]
# The top-level keys every published /area_guides doc carries (the app contract).
GUIDE_DOC_KEYS = {"name", "tagline", "center", "sections", "version", "updatedAt"}


# --- typed-value encoders (map/array shapes firestore_rest doesn't cover) ------

def _bilingual(d: dict) -> dict:
    """{en, ja} -> a Firestore mapValue with both string subfields."""
    return {"mapValue": {"fields": {"en": sval(d.get("en")), "ja": sval(d.get("ja"))}}}


def _center_val(c: dict) -> dict:
    return {"mapValue": {"fields": {"lat": dval(c["lat"]), "lng": dval(c["lng"])}}}


def _section_val(s: dict) -> dict:
    fields = {"kind": sval(s["kind"]), "body": _bilingual(s["body"])}
    if s.get("highlights"):
        fields["highlights"] = {"arrayValue": {
            "values": [_bilingual(h) for h in s["highlights"]]}}
    return {"mapValue": {"fields": fields}}


def _sections_val(sections: list) -> dict:
    return {"arrayValue": {"values": [_section_val(s) for s in sections]}}


# --- content assembly ---------------------------------------------------------

def canonical_sections(sections: list) -> list:
    """Curated sections in canonical kind order, keeping only present kinds and
    dropping empty highlight lists (so the encoded shape is stable for no-op
    detection)."""
    by_kind = {s["kind"]: s for s in sections}
    out = []
    for kind in SECTION_ORDER:
        s = by_kind.get(kind)
        if not s:
            continue
        item = {"kind": kind, "body": {"en": s["body"]["en"], "ja": s["body"]["ja"]}}
        hi = s.get("highlights") or []
        if hi:
            item["highlights"] = [{"en": h["en"], "ja": h["ja"]} for h in hi]
        out.append(item)
    return out


def region_content(key: str, curated: dict, model: dict):
    """The plain-Python content (name, tagline, center, sections) for one region,
    or None with a reason if it can't be published. `model` is {key: {areaId, center}}."""
    m = model.get(key)
    if not m or not m.get("areaId"):
        return None, "no areaId in area-regions.json (run regions.py --build)"
    if not m.get("center"):
        return None, "no center (region has no member onsens)"
    name = curated.get("name")
    if not name or not name.get("en") or not name.get("ja"):
        return None, "missing bilingual name"
    content = {
        "name": {"en": name["en"], "ja": name["ja"]},
        "tagline": None,
        "center": {"lat": m["center"]["lat"], "lng": m["center"]["lng"]},
        "sections": canonical_sections(curated.get("sections", [])),
    }
    tag = curated.get("tagline")
    if tag and tag.get("en") and tag.get("ja"):
        content["tagline"] = {"en": tag["en"], "ja": tag["ja"]}
    if not content["sections"]:
        return None, "no publishable sections"
    return (m["areaId"], content), None


def live_content(fields: dict):
    """Extract the comparable content (name, tagline, center, sections) from a live
    /area_guides doc's `fields`, decoded to plain Python (ignores version/updatedAt)."""
    return {
        "name": field_at(fields, "name"),
        "tagline": field_at(fields, "tagline"),
        "center": field_at(fields, "center"),
        "sections": field_at(fields, "sections"),
    }


def guide_fields(content: dict, version: int, now: str) -> dict:
    """Encode a full /area_guides doc. tagline is always in the field set (null when
    absent) so the doc is fully owned and a dropped tagline can't go stale."""
    return {
        "name": _bilingual(content["name"]),
        "tagline": _bilingual(content["tagline"]) if content["tagline"] else {"nullValue": None},
        "center": _center_val(content["center"]),
        "sections": _sections_val(content["sections"]),
        "version": ival(version),
        "updatedAt": {"timestampValue": now},
    }


# --- live state ---------------------------------------------------------------

def read_live(commit: bool):
    """(tok, {areaId: fields} | None, meta_fields | None, read_ok). On --commit a
    read failure propagates; on a dry-run it degrades to no no-op detection."""
    try:
        tok = token()
        guides = fetch_collection("area_guides", tok)
        meta = get_fields("area_guides_meta/current", tok)
        return tok, guides, meta, True
    except Exception as e:  # noqa: BLE001 (auth/network; non-fatal for a dry-run)
        if commit:
            raise
        print(f"!! could not read live area guides ({type(e).__name__}: {e}); "
              f"reporting the full plan without no-op detection")
        return None, None, None, False


def delete_doc(path: str, tok: str) -> int:
    req = urllib.request.Request(
        f"{BASE}/{path}", method="DELETE", headers={"Authorization": f"Bearer {tok}"})
    with _open(req) as r:
        return r.status


# --- main ---------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Publish /area_guides + bump /area_guides_meta/current.")
    ap.add_argument("--commit", action="store_true", help="execute the writes + version bump")
    ap.add_argument("--prune", action="store_true",
                    help="also delete live guides for regions no longer in the curated source")
    args = ap.parse_args()

    model = {r["key"]: r for r in json.loads(AREA_REGIONS.read_text(encoding="utf-8"))["regions"]}
    curated_doc = json.loads(CURATED.read_text(encoding="utf-8"))
    review_status = curated_doc.get("_meta", {}).get("reviewStatus")
    curated = curated_doc["regions"]

    # Assemble the desired docs {areaId: (key, content)}; collect skips with reasons.
    desired, skipped = {}, []
    for key, c in curated.items():
        result, reason = region_content(key, c, model)
        if result is None:
            skipped.append((key, reason))
            continue
        area_id, content = result
        desired[area_id] = (key, content)

    print(f"publish area guides: {'COMMIT' if args.commit else 'DRY-RUN'}   "
          f"project={PROJECT}   regions={len(curated)}   publishable={len(desired)}")
    print(f"reviewStatus: {review_status!r}")
    if skipped:
        print(f"!! {len(skipped)} region(s) not publishable (skipped):")
        for key, reason in skipped:
            print(f"   {key}: {reason}")

    tok, live_guides, live_meta, read_ok = read_live(args.commit)
    cur_version = int(live_meta.get("version", {}).get("integerValue", 0)) if live_meta else 0
    next_version = cur_version + 1

    # Partition desired into changed vs already-current (by decoded content compare).
    to_write, current = [], []
    for area_id, (key, content) in sorted(desired.items(), key=lambda kv: kv[1][0]):
        if not read_ok:
            to_write.append((area_id, key, content))
            continue
        live = live_guides.get(area_id)
        if live is not None and live_content(live) == content:
            current.append((area_id, key))
        else:
            to_write.append((area_id, key, content))

    # Orphans: live guides whose id is no longer desired (retired regions).
    orphans = sorted(set(live_guides) - set(desired)) if read_ok else []

    unknown = " (live unread, counted as changes)" if not read_ok else ""
    ver_note = f"{cur_version} -> {next_version}" if read_ok else f"current+1 (current unknown offline)"
    print(f"\nwould write: {len(to_write)}   already current: {len(current)}{unknown}")
    print(f"totalCount: {len(desired)}   version: {ver_note}")
    for area_id, key, _c in to_write:
        print(f"  write  {key:<26} {area_id}")
    if orphans:
        verb = "DELETE (--prune)" if args.prune else "orphan (kept; pass --prune to delete)"
        for area_id in orphans:
            print(f"  {verb}: /area_guides/{area_id}")

    will_bump = bool(to_write) or (read_ok and (live_meta is None
                 or int(live_meta.get("totalCount", {}).get("integerValue", -1)) != len(desired)))

    if not args.commit:
        note = (f"Would write {len(to_write)} guide(s)"
                + (f", delete {len(orphans)} orphan(s)" if (orphans and args.prune) else "")
                + (" and upsert area_guides_meta/current" if will_bump else
                   " (meta already current; version would NOT be bumped)"))
        if review_status != "reviewed":
            print(f"\n!! reviewStatus is {review_status!r}, not 'reviewed': --commit is BLOCKED "
                  f"until the content is human-verified and the flag is flipped.")
        print(f"\nDry-run only, nothing written. {note}. Re-run with --commit"
              f"{' (after review)' if review_status != 'reviewed' else ''}.")
        return

    if review_status != "reviewed":
        raise SystemExit(
            f"refusing to --commit: data/area_guides_curated.json reviewStatus is "
            f"{review_status!r}, not 'reviewed'. Human-verify the content first, then "
            f"set _meta.reviewStatus to 'reviewed'.")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if to_write:
        print(f"\n-- writing {len(to_write)} area_guides docs (version {next_version}) --")
        for area_id, key, content in to_write:
            fields = guide_fields(content, next_version, now)
            assert set(fields) == GUIDE_DOC_KEYS, f"{key}: doc keys drifted from the contract"
            patch(f"area_guides/{area_id}", fields, sorted(fields), tok)
        print(f"    wrote {len(to_write)}.")
    if args.prune and orphans:
        print(f"-- deleting {len(orphans)} orphaned guides --")
        for area_id in orphans:
            delete_doc(f"area_guides/{area_id}", tok)
        print(f"    deleted {len(orphans)}.")

    if will_bump or (args.prune and orphans):
        patch("area_guides_meta/current",
              {"version": ival(next_version), "publishedAt": {"timestampValue": now},
               "totalCount": ival(len(desired))},
              ["version", "publishedAt", "totalCount"], tok)
        print(f"area_guides_meta/current: version {cur_version} -> {next_version}, "
              f"totalCount {len(desired)}  (upserted)")
    else:
        print("\nAll guides already current, nothing written, version not bumped.")


if __name__ == "__main__":
    main()
