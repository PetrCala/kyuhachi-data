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


def bump_catalog_version(now: str, tok: str):
    fields = get_fields("catalog_meta/current", tok)
    if fields is None:
        print("catalog_meta/current does not exist yet — skipping version bump "
              "(the first full publish will create it).")
        return
    cur = int(fields.get("version", {}).get("integerValue", 0))
    patch("catalog_meta/current",
          {"version": {"integerValue": str(cur + 1)}, "publishedAt": {"timestampValue": now}},
          ["version", "publishedAt"], tok)
    print(f"catalog_meta/current: version {cur} → {cur + 1}  (bumped)")
