#!/usr/bin/env python3
"""
Surgical catalog publisher — apply *human-adjudicated* changes to Firestore as
MERGE writes. The additive opposite of the app repo's clean-slate reseed: it
PATCHes only named fields (updateMask), never overwrites a whole doc, never
deletes an onsen, and never touches /users/**.

It is driven by a reviewed *decisions* file (one adjudicated change per onsen):
  - {"hid": N, "action": "update"} → fetch the live page and merge the changed
    MATERIAL fields (+ updatedAt) into /onsens/{kyuhachiId}.
  - {"hid": N, "action": "retire"} → set isActive:false (+ updatedAt). Onsen
    docs are never deleted; existing visits + frozen challenge snapshots keep
    counting.
  - {"hid": N, "action": "add"}    → CREATE /onsens/{kyuhachiId} for a new onsen,
    assembling the full doc from the /map seed (name/area/lat/lng) + a live detail
    scrape + the curated hours + generated nameKana/nameRomaji + a rehosted photo. The one
    create (vs PATCH) write; idempotent (skips if the doc already exists) and gated.
    Requires a minted kyuhachiId (catalog-sync mint) and a curated-hours entry.
  - {"hid": N, "action": "skip"}   → no-op (explicitly reviewed, no change).

The decisions file is normally scaffolded from a catalog-diff changelog.json
(--from-changelog), then hand-reviewed before applying.

Auth: gcloud Application Default Credentials (same as the app repo's
reseed-catalog.py). Run `gcloud auth application-default login` if 401.

Usage:
  # 1. scaffold a decisions skeleton from a diff changelog (no writes, no auth):
  python publisher/apply.py --from-changelog reports/<ts>/changelog.json --out decisions.json
  # 2. review/edit decisions.json, then dry-run (re-fetches the live pages):
  python publisher/apply.py --decisions decisions.json
  # 3. apply:
  python publisher/apply.py --decisions decisions.json --commit
"""
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / ".claude/skills/catalog-diff"))
from onsen_scraper import (  # noqa: E402
    fee_for,
    fetch_detail_page,
    name_kana,
    name_romaji,
    parse_detail_page,
)
import catalog_diff as cd  # noqa: E402
import image_processor as ip  # noqa: E402  (publisher/image_processor.py — photo rehosting)
import backfill_schedule as bsf  # noqa: E402  (reuse the curated-hours encoders + Firestore GET)

PROJECT = "kyuhachi-fddcc"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
IDMAP = json.loads((REPO / "data/onsen-id-map.json").read_text())
CURATED_HOURS = REPO / "data" / "hours_curated.json"

# parser field -> Firestore field path (MATERIAL fields only).
FIELD_PATH = {
    "prefecture": "prefecture", "address": "address", "phone": "phone",
    "admission_fee": "admissionFee", "spring_quality": "springQuality",
    "website_url": "websiteUrl", "business_hours": "businessHours.raw",
}

ACTIONS = ("update", "retire", "skip", "add")  # `add` creates the live doc for a new onsen (needs a kyuhachiId)


def token() -> str:
    return subprocess.check_output(
        ["gcloud", "auth", "application-default", "print-access-token"], text=True
    ).strip()


def sval(v):
    return {"stringValue": v} if v else {"nullValue": None}


def ival(n):
    return {"nullValue": None} if n is None else {"integerValue": str(n)}


def dval(x):
    return {"nullValue": None} if x is None else {"doubleValue": float(x)}


def bval(b):
    return {"booleanValue": bool(b)}


# Schedule encoding lives in backfill_schedule.py (sched_val), which solely owns
# businessHours.schedule via the curated parse. apply.py no longer encodes
# schedules — see build_update.


def _open(req, timeout=30, retries=3):
    """urlopen with a timeout, retrying transient network errors / 429 / 5xx.
    A single hung connection must not stall a 100+ doc publish loop forever."""
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if attempt < retries and e.code in (429, 500, 502, 503):
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries:
                continue
            raise


def patch(kid: str, fields: dict, mask: list[str], tok: str) -> int:
    qs = "&".join(f"updateMask.fieldPaths={m}" for m in mask)
    req = urllib.request.Request(
        f"{BASE}/onsens/{kid}?{qs}", data=json.dumps({"fields": fields}).encode(),
        method="PATCH",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    try:
        with _open(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {e.read().decode()[:300]}")
        raise


def create(kid: str, fields: dict, tok: str) -> int:
    """Create /onsens/{kid} with the full field set. Server rejects (409) if it
    already exists — but apply_decision checks existence first, so this is the
    sole *create* (vs PATCH) write in the publisher and is reached only for a
    genuinely new doc."""
    req = urllib.request.Request(
        f"{BASE}/onsens?documentId={kid}", data=json.dumps({"fields": fields}).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    try:
        with _open(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {e.read().decode()[:300]}")
        raise


def build_update(hid: int, tok: str | None = None):
    """Fetch live, diff vs baseline, return (fields, mask, summary) for changed material fields.
    On --commit (tok set) a genuinely changed source photo is also rehosted (see below)."""
    base = cd.load_snapshot()[hid]
    live = parse_detail_page(fetch_detail_page(hid), hid)
    fields, mask, summary = {}, [], []
    for pf, path in FIELD_PATH.items():
        if cd.norm(pf, base.get(pf)) == cd.norm(pf, live.get(pf)):
            continue
        val = live.get(pf)
        summary.append((pf, base.get(pf), val))
        if "." in path:  # nested map field, e.g. businessHours.raw — preserves .schedule
            top, sub = path.split(".")
            fields.setdefault(top, {"mapValue": {"fields": {}}})["mapValue"]["fields"][sub] = sval(val)
        else:
            fields[path] = sval(val)
        mask.append(path)
    # Keep numeric adultFee in sync whenever the fee text changes, so the app's
    # cost stats never go stale — derived via the shared fees parser (one source
    # of truth, same as the cost-analysis skill + backfill).
    if "admissionFee" in mask:
        fields["adultFee"] = ival(fee_for(hid, live.get("admission_fee"))[0])
        mask.append("adultFee")
    # Photo: image_url is MUTED for diffing (the source churns cosmetic URLs), so an
    # image-only change never reaches here — but when we're already writing a material
    # update and the source photo genuinely changed, rehost it too so the app's fast
    # Storage copy + blurhash stay current. The published URL is deterministic (uuid5 of
    # the kyuhachiId), so this never churns imageUrl on its own. Done only on --commit
    # (tok set); a dry-run just surfaces the change in the summary.
    if cd.norm("image_url", base.get("image_url")) != cd.norm("image_url", live.get("image_url")):
        summary.append(("image_url", base.get("image_url"), live.get("image_url")))
        if tok:
            kid = IDMAP[str(hid)]
            new_img = live.get("image_url")
            if new_img:
                raw = ip.download(new_img)
                fields["imageUrl"] = sval(ip.upload(ip.to_webp(raw), kid, ip.DEFAULT_BUCKET, tok))
                fields["blurhash"] = sval(ip.blurhash_of(raw))
            else:  # photo removed at source
                fields["imageUrl"] = sval(None)
                fields["blurhash"] = sval(None)
            mask += ["imageUrl", "blurhash"]
    # NOTE: businessHours.schedule (+ exceptions/confidence) is NOT written here.
    # It is owned solely by data/hours_curated.json (the LLM parse) via
    # backfill_schedule.py --from-curated — the regex parser (onsen_scraper/hours.py)
    # is too unreliable on Japanese phrasing to trust for the published grid (e.g.
    # 翌日休 → spurious Sunday). When this update changes businessHours.raw, the
    # weekly grid is therefore intentionally left stale-but-honest (raw stays the
    # fallback) until the onsen is re-curated. The catalog-sync flow runs
    # recurate-hours + the curated backfill right after apply.py so the grid is
    # corrected in the same session; an hours change must never silently ship a
    # regex schedule.
    return fields, mask, summary


# --- new-onsen create (`add`) -------------------------------------------------
# A new onsen has no baseline to diff, so `add` assembles its doc from the union of
# every source the maintenance paths use: the /map seed (name / areaName / lat / lng,
# which the detail page lacks), a live detail scrape (the descriptive fields), the
# curated hours (the weekly grid — never the regex), a generated reading, and a
# rehosted photo. The result must match the app's OnsenDocument contract exactly.

_MAP_SEED = None
_CURATED = None


def map_seed():
    """The live /map seed {hid: {name, areaName, address, lat, lng}}, fetched once."""
    global _MAP_SEED
    if _MAP_SEED is None:
        from onsen_scraper.mapseed import fetch_map_seed
        _MAP_SEED = fetch_map_seed()
    return _MAP_SEED


def curated_hours():
    global _CURATED
    if _CURATED is None:
        _CURATED = json.loads(CURATED_HOURS.read_text(encoding="utf-8"))["onsens"]
    return _CURATED


def catalog_version(tok: str | None):
    """The live catalog data version a new doc enters at; None in an unauthed dry-run."""
    if not tok:
        return None
    meta = bsf.get_fields("catalog_meta/current", tok)
    return int(meta.get("version", {}).get("integerValue", 0)) if meta else None


def _business_hours_val(hid: int, raw):
    """ParsedHours map {raw, schedule, exceptions?, confidence?} from the curated entry
    (schedule via the curated parse, never the regex), or null when neither exists."""
    entry = curated_hours().get(str(hid))
    if raw is None and not entry:
        return {"nullValue": None}
    fields = {"raw": sval(raw)}
    if entry:
        fields["schedule"] = bsf.sched_val(bsf.expand_curated(entry))
        if entry.get("exceptions"):
            fields["exceptions"] = bsf.exc_val(entry["exceptions"])
        if entry.get("confidence"):
            fields["confidence"] = bsf.conf_val(entry["confidence"])
    else:
        fields["schedule"] = {"nullValue": None}
    return {"mapValue": {"fields": fields}}


def build_add(hid: int, tok: str | None):
    """Assemble the OnsenDocument field set (minus createdAt/updatedAt) for a new
    onsen. On --commit (tok set) the source photo is rehosted to Storage and the live
    catalog version read; a dry-run leaves imageUrl/blurhash/catalogVersion null and
    surfaces the source photo in the summary. Returns (fields, summary)."""
    seed = map_seed().get(hid)
    if not seed:
        raise SystemExit(f"hid {hid}: not in the live /map seed — cannot add (delisted at source?)")
    live = parse_detail_page(fetch_detail_page(hid), hid)
    name = seed.get("name")
    adult = fee_for(hid, live.get("admission_fee"))[0]
    fields = {
        "name": sval(name),
        "nameKana": sval(name_kana(name)),
        "nameRomaji": sval(name_romaji(name)),
        "areaName": sval(seed.get("areaName")),
        "address": sval(live.get("address") or seed.get("address")),
        "prefecture": sval(live.get("prefecture")),
        "lat": dval(seed.get("lat")),
        "lng": dval(seed.get("lng")),
        "phone": sval(live.get("phone")),
        "businessHours": _business_hours_val(hid, live.get("business_hours")),
        "admissionFee": sval(live.get("admission_fee")),
        "adultFee": ival(adult),
        "springQuality": sval(live.get("spring_quality")),
        "websiteUrl": sval(live.get("website_url")),
        "imageUrl": sval(None),
        "blurhash": sval(None),
        "isActive": bval(True),
        "catalogVersion": ival(catalog_version(tok)),
    }
    src_img = live.get("image_url")
    if tok and src_img:
        kid = IDMAP[str(hid)]
        rawimg = ip.download(src_img)
        fields["imageUrl"] = sval(ip.upload(ip.to_webp(rawimg), kid, ip.DEFAULT_BUCKET, tok))
        fields["blurhash"] = sval(ip.blurhash_of(rawimg))
    summary = [("name", name), ("areaName", seed.get("areaName")),
               ("prefecture", live.get("prefecture")),
               ("coords", f"{seed.get('lat')}, {seed.get('lng')}"),
               ("adultFee", adult), ("source_image", src_img)]
    return fields, summary


# The top-level keys every published onsen doc carries (the app's OnsenDocument
# contract). A new doc must match this exactly — validated before the first create
# so a renamed/added field on the app side aborts instead of writing a bad doc.
ONSEN_DOC_KEYS = {
    "name", "nameKana", "nameRomaji", "areaName", "address", "prefecture", "lat", "lng",
    "phone", "businessHours", "admissionFee", "adultFee", "springQuality", "websiteUrl",
    "imageUrl", "blurhash", "isActive", "catalogVersion", "createdAt", "updatedAt",
}


def validate_add_schema(fields: dict, tok: str | None) -> None:
    """Guard the first *create* write. Hard-fail if the proposed doc's keys don't
    match the OnsenDocument contract; when authed, also compare against a real live
    doc and warn on any drift (a soft check — existing docs can be heterogeneous)."""
    proposed = set(fields)
    if proposed != ONSEN_DOC_KEYS:
        raise SystemExit(
            f"add: doc keys don't match the OnsenDocument contract "
            f"(missing={sorted(ONSEN_DOC_KEYS - proposed)}, "
            f"extra={sorted(proposed - ONSEN_DOC_KEYS)}) — refusing to create")
    if tok:
        ref_kid = next((IDMAP[str(h)] for h in (1, 5, 7, 8) if str(h) in IDMAP), None)
        ref = bsf.get_fields(f"onsens/{ref_kid}", tok) if ref_kid else None
        if ref is not None and set(ref) != proposed:
            print(f"    ⚠ live reference /onsens/{ref_kid} key drift: "
                  f"only-on-ref={sorted(set(ref) - proposed)}, "
                  f"only-on-new={sorted(proposed - set(ref))}")


def load_decisions(path: Path) -> list[dict]:
    """Read a reviewed decisions file. Accepts a top-level list or {"decisions": [...]}.
    Each item: {hid, action: update|retire|skip|add, note?}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["decisions"] if isinstance(data, dict) else data
    bad = sorted({d.get("action") for d in items if d.get("action") not in ACTIONS})
    if bad:
        raise SystemExit(f"unknown action(s) in {path}: {bad}; allowed {ACTIONS}")
    return items


def scaffold_from_changelog(path: Path) -> list[dict]:
    """Turn a catalog-diff changelog.json into a decisions skeleton for human review.
    Defaults: material→update, low-signal→skip, removed→retire, added/fetchFailed→skip.
    The human edits the actions before applying."""
    cl = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for m in cl.get("modified", []):
        if m.get("severity") == "material":
            out.append({"hid": m["hid"], "action": "update",
                        "note": "material: " + ", ".join(m.get("materialFields", []))})
        else:
            out.append({"hid": m["hid"], "action": "skip",
                        "note": "low-signal only: " + ", ".join(m.get("mutedFields", []))})
    for r in cl.get("removed", []):
        out.append({"hid": r["hid"], "action": "retire", "note": "removed/delisted at source"})
    for a in cl.get("added", []):
        out.append({"hid": a["hid"], "action": "add",
                    "note": "NEW onsen — create live doc (mint a kyuhachiId first)"})
    for f in cl.get("fetchFailed", []):
        out.append({"hid": f["hid"], "action": "skip", "note": "fetch failed — re-run before deciding"})
    return out


def apply_decision(d: dict, now: str, tok: str | None, commit: bool) -> None:
    hid = d["hid"]
    note = d.get("note", "")
    if d["action"] == "skip":
        print(f"hid {hid} → SKIP   # {note}\n")
        return
    if str(hid) not in IDMAP:
        print(f"hid {hid} → no kyuhachiId in id map; skipping\n")
        return
    kid = IDMAP[str(hid)]
    if d["action"] == "add":
        if tok and bsf.get_fields(f"onsens/{kid}", tok) is not None:
            print(f"hid {hid} → /onsens/{kid}  ADD: doc already exists — skip (idempotent)\n")
            return
        fields, summary = build_add(hid, tok)
        print(f"hid {hid} → /onsens/{kid}  ADD (new onsen)   # {note}")
        for k, v in summary:
            print(f"    {k}: {v!r}")
        fields["createdAt"] = {"timestampValue": now}
        fields["updatedAt"] = {"timestampValue": now}
        validate_add_schema(fields, tok)
        if commit:
            create(kid, fields, tok)
            print("    created.")
        else:
            print(f"    would create ({len(fields)} fields): {', '.join(sorted(fields))}")
        print()
        return
    if d["action"] == "retire":
        fields = {"isActive": {"booleanValue": False}, "updatedAt": {"timestampValue": now}}
        mask = ["isActive", "updatedAt"]
        print(f"hid {hid} → /onsens/{kid}  RETIRE isActive:false   # {note}")
    else:  # update
        fields, mask, summary = build_update(hid, tok)
        if not summary:
            print(f"hid {hid} → UPDATE: no material changes vs source; nothing to write\n")
            return
        fields["updatedAt"] = {"timestampValue": now}
        mask.append("updatedAt")
        print(f"hid {hid} → /onsens/{kid}  UPDATE   # {note}")
        for pf, old, new in summary:
            print(f"    {pf}:  {old!r}\n           → {new!r}")
    print(f"    mask: {mask}")
    if commit:
        patch(kid, fields, mask, tok)
        print("    committed.")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--decisions", type=Path, help="reviewed decisions JSON to apply")
    ap.add_argument("--from-changelog", type=Path,
                    help="scaffold a decisions skeleton from a catalog-diff changelog.json (no apply)")
    ap.add_argument("--out", type=Path, help="write the scaffold here (default: stdout)")
    ap.add_argument("--commit", action="store_true", help="execute the merge writes (with --decisions)")
    args = ap.parse_args()

    if args.from_changelog:
        skeleton = scaffold_from_changelog(args.from_changelog)
        text = json.dumps({"decisions": skeleton}, ensure_ascii=False, indent=2)
        if args.out:
            args.out.write_text(text + "\n", encoding="utf-8")
            print(f"wrote {len(skeleton)}-item decisions skeleton → {args.out}  "
                  "(review/edit the actions, then re-run with --decisions to apply)")
        else:
            print(text)
        return

    if not args.decisions:
        raise SystemExit("provide --decisions FILE to apply, or --from-changelog FILE to scaffold one")

    decisions = load_decisions(args.decisions)
    tok = token() if args.commit else None
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(f"Surgical catalog publish — {'COMMIT' if args.commit else 'DRY-RUN'}   "
          f"project={PROJECT}   decisions={args.decisions.name} ({len(decisions)})\n")
    for d in decisions:
        apply_decision(d, now, tok, args.commit)
    if not args.commit:
        print("Dry-run only — nothing written. Re-run with --commit to apply.")


if __name__ == "__main__":
    main()
