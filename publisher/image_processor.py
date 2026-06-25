#!/usr/bin/env python3
"""Onsen photo rehosting helpers.

Pure helpers (no Firestore writes) that turn a raw source photo URL on
www.88onsen.com into a fast, app-ready Firebase Storage object:

  download(url)  -> bytes        # GET the original, reject non-images
  to_webp(raw)   -> bytes        # downscale to display size, re-encode WebP
  blurhash_of(raw) -> str        # BlurHash for an instant placeholder
  upload(webp, kid, bucket, tok) -> str   # → tokenized download URL

Why rehost: the source URLs live on a plain Apache origin with no CDN and no
Cache-Control (~1s TLS, ~1.5s TTFB, 16-35 KB/s) — a 100KB photo takes 3-5s to
load in the app, a 400KB one ~12s. Firebase Storage serves from Google's edge
with caching, and resizing to display size shrinks the bytes ~10x.

The upload sets a *deterministic* `firebaseStorageDownloadTokens` (uuid5 of the
kyuhachiId), so the published download URL is stable across re-runs and a
re-upload is a true no-op on the stored `imageUrl`. Tokenised download URLs are
served publicly without a Storage-rules change (the token gates access).

The publisher (`backfill_images.py` / `apply.py`) wires these into the merge-write
flow. Auth for upload is the same gcloud ADC bearer token used for Firestore.
"""
import io
import json
import urllib.parse
import uuid

import blurhash
import requests
from PIL import Image

# Default Firebase Storage bucket for project kyuhachi-fddcc (the `.firebasestorage.app`
# bucket is a real GCS bucket of the same name, reachable via the GCS JSON API).
DEFAULT_BUCKET = "kyuhachi-fddcc.firebasestorage.app"

# Long, immutable cache: the object content for a given kyuhachiId only changes
# when the source photo does, and a content change re-runs through here anyway.
CACHE_CONTROL = "public, max-age=31536000, immutable"

# Display-size target. The detail header and preview hero render at most ~400pt
# wide (~1200px @3x); 1080px on the long edge covers that with headroom while
# cutting full-res originals down by ~10x.
DEFAULT_MAX_PX = 1080
DEFAULT_QUALITY = 80

# A small raster is plenty for a 4x3-component BlurHash; encoding the full image
# as nested lists would be needlessly slow.
BLURHASH_SAMPLE_PX = 64

# Fixed namespace so download_token(kid) is stable forever → stable public URL.
_TOKEN_NAMESPACE = uuid.UUID("b8f1d2a4-3c5e-4f6a-9b7c-1d2e3f4a5b6c")

# Same polite browser UA the scraper uses (some origins 403 a bare urllib UA).
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def download(url: str, *, timeout: float = 20.0) -> bytes:
    """GET the raw image bytes. Raises ValueError if the response isn't an image."""
    resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "")
    if not ctype.lower().startswith("image/"):
        raise ValueError(f"not an image ({ctype or 'no content-type'}): {url}")
    return resp.content


def to_webp(raw: bytes, *, max_px: int = DEFAULT_MAX_PX, quality: int = DEFAULT_QUALITY) -> bytes:
    """Downscale to fit `max_px` on the long edge (never upscales) and re-encode WebP."""
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((max_px, max_px))  # in place, preserves aspect ratio, shrink-only
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()


def blurhash_of(raw: bytes, *, x: int = 4, y: int = 3, sample_px: int = BLURHASH_SAMPLE_PX) -> str:
    """Compute a BlurHash. `blurhash.encode` wants a nested list of sRGB rows, so we
    downsample to a small raster and hand it the pixels row by row."""
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((sample_px, sample_px))
    w, h = img.size
    px = img.load()
    rows = [[list(px[c, r]) for c in range(w)] for r in range(h)]
    return blurhash.encode(rows, x, y)


def storage_path(kid: str) -> str:
    """Deterministic Storage object name for an onsen's photo."""
    return f"onsen-images/{kid}.webp"


def download_token(kid: str) -> str:
    """Stable per-onsen Firebase download token → unchanging public URL across runs."""
    return str(uuid.uuid5(_TOKEN_NAMESPACE, kid))


def download_url(bucket: str, kid: str, token: str) -> str:
    """The public, CDN-cached Firebase Storage download URL (token-gated, no auth)."""
    enc = urllib.parse.quote(storage_path(kid), safe="")
    return f"https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{enc}?alt=media&token={token}"


def upload(data: bytes, kid: str, bucket: str, tok: str, *, timeout: float = 30.0) -> str:
    """Upload WebP bytes to Firebase Storage with Cache-Control + a deterministic
    download token, via the GCS JSON multipart API. Returns the public download URL.

    `tok` is a gcloud ADC bearer token (cloud-platform scope covers GCS writes).
    Overwrites `onsen-images/{kid}.webp` in place on re-run.
    """
    token = download_token(kid)
    metadata = {
        "name": storage_path(kid),
        "contentType": "image/webp",
        "cacheControl": CACHE_CONTROL,
        # Custom metadata Firebase reads to authorise tokenised download URLs.
        "metadata": {"firebaseStorageDownloadTokens": token},
    }
    boundary = "kyuhachi_image_part_boundary"
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: image/webp\r\n\r\n"
    ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")

    url = f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?uploadType=multipart"
    resp = requests.post(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return download_url(bucket, kid, token)
