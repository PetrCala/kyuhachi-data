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
