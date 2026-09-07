#!/usr/bin/env python3
"""
Shared Firestore REST plumbing for the publisher scripts (`apply.py` and the
`backfill_*.py` one-field backfills). Auth (gcloud ADC), typed-value encoders,
and the GET/PATCH/POST calls were copy-pasted identically across five scripts —
extracted once so a change (retry policy, auth) doesn't need five edits.

No behavior change vs. the code this replaces: same retries, same timeout, same
typed-value encoding, same PROJECT/BASE.
"""
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request

PROJECT = "kyuhachi-fddcc"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"


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


def get_fields(path: str, tok: str):
    """Return the doc's `fields` dict, or None on 404."""
    req = urllib.request.Request(f"{BASE}/{path}", headers={"Authorization": f"Bearer {tok}"})
    try:
        with _open(req) as r:
            return json.load(r).get("fields", {})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def decode_value(v):
    """Decode one Firestore typed value into a Python scalar/container — the inverse
    of the sval/ival/dval/bval encoders. Null/absent → None; maps/arrays recurse.
    Only the scalar shapes we publish are round-tripped precisely; unknown shapes
    fall through to None."""
    if not v or "nullValue" in v:
        return None
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return v["doubleValue"]
    if "booleanValue" in v:
        return bool(v["booleanValue"])
    if "timestampValue" in v:
        return v["timestampValue"]
    if "mapValue" in v:
        return {k: decode_value(x) for k, x in v["mapValue"].get("fields", {}).items()}
    if "arrayValue" in v:
        return [decode_value(x) for x in v["arrayValue"].get("values", [])]
    return None


def field_at(fields: dict, path: str):
    """Decode a (possibly nested, dotted) field path out of a `fields` dict.
    'businessHours.raw' walks into the nested mapValue. A missing segment → None."""
    cur, parts = fields, path.split(".")
    for i, key in enumerate(parts):
        if not isinstance(cur, dict) or key not in cur:
            return None
        if i == len(parts) - 1:
            return decode_value(cur[key])
        cur = cur[key].get("mapValue", {}).get("fields", {})
    return None


def list_documents(collection: str, tok: str, page_size: int = 300):
    """Yield every raw document ({name, fields, ...}) in a collection, following
    nextPageToken pagination. Read-only — a plain paginated GET, no writes."""
    page_token = None
    while True:
        qs = f"pageSize={page_size}"
        if page_token:
            qs += f"&pageToken={urllib.parse.quote(page_token, safe='')}"
        req = urllib.request.Request(
            f"{BASE}/{collection}?{qs}", headers={"Authorization": f"Bearer {tok}"})
        with _open(req) as r:
            data = json.load(r)
        for doc in data.get("documents", []):
            yield doc
        page_token = data.get("nextPageToken")
        if not page_token:
            break


def fetch_collection(collection: str, tok: str, page_size: int = 300) -> dict:
    """Read a whole collection into {docId: fields}, following pagination. Read-only.
    `docId` is the last path segment of document.name (the kyuhachiId for /onsens).
    One paginated list read instead of N per-doc GETs."""
    return {doc["name"].rsplit("/", 1)[-1]: doc.get("fields", {})
            for doc in list_documents(collection, tok, page_size)}


def live_onsens(commit: bool, page_size: int = 300):
    """(tok, {kid: fields}) for the whole /onsens collection — the shared no-op
    detector the backfills read the current field values from before deciding what
    to PATCH. On --commit a read failure propagates (writes need auth); on a dry-run
    it degrades to (None, None) with a note, so the plan still prints offline (just
    without change-vs-current detection). Read-only."""
    try:
        tok = token()
        return tok, fetch_collection("onsens", tok, page_size)
    except Exception as e:  # noqa: BLE001 — auth (gcloud) or network; both non-fatal for a dry-run
        if commit:
            raise
        print(f"!! could not read live catalog ({type(e).__name__}: {e}); "
              f"reporting the full plan without no-op detection")
        return None, None


def patch(path: str, fields: dict, mask: list, tok: str) -> int:
    qs = "&".join(f"updateMask.fieldPaths={m}" for m in mask)
    req = urllib.request.Request(
        f"{BASE}/{path}?{qs}", data=json.dumps({"fields": fields}).encode(), method="PATCH",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    try:
        with _open(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {e.read().decode()[:300]}")
        raise


def create(collection: str, doc_id: str, fields: dict, tok: str) -> int:
    """Create /{collection}/{doc_id} with the full field set — a POST, not a PATCH.
    The server rejects with 409 if the doc already exists; callers that need
    idempotence check existence first (see apply.py's `add` action)."""
    req = urllib.request.Request(
        f"{BASE}/{collection}?documentId={doc_id}", data=json.dumps({"fields": fields}).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    try:
        with _open(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {e.read().decode()[:300]}")
        raise


def onsen_counts(tok: str) -> tuple:
    """(totalCount, activeCount) over the live /onsens collection. Read-only.

    Counted from the live collection, not from the snapshot DB. The snapshot is
    the diff baseline and retired onsens are pruned out of it, so it cannot see
    a document that exists in Firestore with isActive:false: counting it would
    report the active count as the total and understate totalCount by one per
    retirement. The live collection is the only source that knows both numbers.

    One paginated list read (the whole catalog is a single page at this size).
    """
    return counts_of(fetch_collection("onsens", tok))


def counts_of(live: dict) -> tuple:
    """(totalCount, activeCount) from an already-fetched {kid: fields}. Pure."""
    return len(live), sum(1 for f in live.values() if field_at(f, "isActive") is True)


# --- /catalog_index/current -------------------------------------------------
#
# A slim, derived projection of the catalog for the app repo's public journey
# website, which renders seven values per onsen and used to read all 161
# documents (386 KB) to get them. Packed into one document it is 24 KB and one
# read. The website never reads /onsens again; the app still does, unchanged.
#
# The contract is owned jointly with the app repo: CatalogIndexDocument in
# kyuhachi's shared/src/types/onsen.ts, and ADR-012 there for why it is packed
# into a string rather than stored as a Firestore array of maps (the array
# re-incurs the per-value envelope the document exists to remove: 54 KB against
# this shape's 24 KB). See docs/onsen-schema.md.

CATALOG_INDEX_SCHEMA_VERSION = 1

#: Decimal places for published coordinates (~1.1 m), matching how the app repo
#: encodes walked tracks. More precision than a map dot can express costs bytes.
INDEX_COORD_PRECISION = 5


def index_entries(live: dict) -> list:
    """The packed index rows for an already-fetched {kid: fields}. Pure.

    One positional tuple per onsen, ordered by kyuhachiId so republishing an
    unchanged catalog produces a byte-identical document and a diff means
    something. EVERY onsen goes in, retired ones included: the website has to
    place a visit to an onsen that was later retired, and a frozen challenge
    snapshot can still name one, so filtering on isActive here would lose dots
    the map has to draw.
    """
    return [
        [
            kid,
            field_at(f, "name"),
            field_at(f, "nameRomaji"),
            field_at(f, "areaName"),
            field_at(f, "prefecture"),
            round(field_at(f, "lat"), INDEX_COORD_PRECISION),
            round(field_at(f, "lng"), INDEX_COORD_PRECISION),
        ]
        for kid, f in sorted(live.items())
    ]


def catalog_index_fields(version: int, now: str, live: dict) -> dict:
    """The full /catalog_index/current field set. Pure - no auth, no writes.

    `ensure_ascii=False` is load-bearing, not cosmetic: escaping the Japanese
    names would double the size of the one field this document exists to keep
    small (3 UTF-8 bytes per kanji becoming 6 ASCII ones).
    """
    entries = index_entries(live)
    packed = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    return {
        "schemaVersion": ival(CATALOG_INDEX_SCHEMA_VERSION),
        "version": ival(version),
        "publishedAt": {"timestampValue": now},
        "count": ival(len(entries)),
        "entries": {"stringValue": packed},
    }


def publish_catalog_index(version: int, now: str, live: dict, tok: str):
    """Rewrite /catalog_index/current from the live catalog.

    A full-field PATCH, which creates the document when it is absent, so the
    first publish needs no separate create path. The whole document is replaced
    every time: it is derived, holds nothing /onsens does not, and a partially
    updated index is worse than a rebuilt one.
    """
    fields = catalog_index_fields(version, now, live)
    patch("catalog_index/current", fields, list(fields), tok)
    size = len(fields["entries"]["stringValue"].encode())
    print(f"catalog_index/current: {field_at(fields, 'count')} entries, "
          f"{size // 1024} KB packed  (version {version}, schemaVersion "
          f"{CATALOG_INDEX_SCHEMA_VERSION})")


def bump_catalog_version(now: str, tok: str):
    """Advance /catalog_meta/current: version, publishedAt, and both counts.

    The counts are refreshed here rather than at each call site because this is
    the one place every publisher script agrees to touch after writing. They are
    not currently read by the app (which filters on isActive itself), but they
    are part of the published CatalogMetaDocument contract, and a stale count is
    a landmine for the first reader that trusts one: "I expected activeCount
    docs and got fewer" would fail spuriously against a number frozen at the
    original seed.
    """
    fields = get_fields("catalog_meta/current", tok)
    if fields is None:
        print("catalog_meta/current does not exist yet — skipping version bump "
              "(the first full publish will create it).")
        return
    cur = int(fields.get("version", {}).get("integerValue", 0))
    # After the caller's writes, so an add/retire in this same run is counted.
    # Read once: the counts and the derived catalog index are both projections
    # of the same live collection, and they must not disagree with each other.
    live = fetch_collection("onsens", tok)
    total, active = counts_of(live)
    patch("catalog_meta/current",
          {"version": {"integerValue": str(cur + 1)}, "publishedAt": {"timestampValue": now},
           "totalCount": ival(total), "activeCount": ival(active)},
          ["version", "publishedAt", "totalCount", "activeCount"], tok)
    print(f"catalog_meta/current: version {cur} → {cur + 1}  (bumped)   "
          f"totalCount={total}  activeCount={active}")
    # Republished from the same read and stamped with the same version, so the
    # website can never serve an index derived from a catalog the app has
    # already moved past.
    publish_catalog_index(cur + 1, now, live, tok)
