"""Tests for the onsen photo rehosting helpers (publisher/image_processor.py).

Fully offline — Pillow + blurhash run for real on synthetic images; the network
(download/upload) is monkeypatched. `image_processor.py` lives in a non-package
dir, so we add it to sys.path (same trick as test_publish_schedule)."""
import io
import os
import sys
import urllib.parse
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "publisher"))

import image_processor as ip  # noqa: E402

B83 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#$%*+,-.:;=?@[]^_{|}~"


def _png(size, *, noisy=False) -> bytes:
    """A PNG of the given (w, h). Noisy = near-incompressible, so re-encoding shrinks it."""
    if noisy:
        img = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    else:
        img = Image.new("RGB", size, (180, 90, 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, *, content=b"", headers=None, status=200):
        self.content = content
        self.headers = headers or {}
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise AssertionError(f"HTTP {self._status}")


# --- to_webp ------------------------------------------------------------------

def test_to_webp_is_webp_and_capped_to_max_px():
    out = ip.to_webp(_png((2000, 1500)), max_px=1080)
    img = Image.open(io.BytesIO(out))
    assert img.format == "WEBP"
    assert max(img.size) <= 1080
    assert img.size == (1080, 810)  # aspect preserved


def test_to_webp_does_not_upscale():
    out = ip.to_webp(_png((300, 200)), max_px=1080)
    assert Image.open(io.BytesIO(out)).size == (300, 200)


def test_to_webp_shrinks_bytes_for_a_large_photo():
    raw = _png((1600, 1200), noisy=True)
    out = ip.to_webp(raw)
    assert len(out) < len(raw)


# --- blurhash -----------------------------------------------------------------

def test_blurhash_of_returns_valid_hash():
    h = ip.blurhash_of(_png((800, 600)), x=4, y=3)
    assert isinstance(h, str)
    assert len(h) == 28  # 4x3 components → fixed 28-char base83 string
    assert all(ch in B83 for ch in h)


# --- naming / URLs / tokens ---------------------------------------------------

def test_storage_path():
    assert ip.storage_path("abc-123") == "onsen-images/abc-123.webp"


def test_download_token_is_deterministic_and_per_onsen():
    assert ip.download_token("kid-A") == ip.download_token("kid-A")
    assert ip.download_token("kid-A") != ip.download_token("kid-B")


def test_download_url_format():
    tok = ip.download_token("kid-A")
    url = ip.download_url("bucket.firebasestorage.app", "kid-A", tok)
    assert url.startswith("https://firebasestorage.googleapis.com/v0/b/bucket.firebasestorage.app/o/")
    assert urllib.parse.quote("onsen-images/kid-A.webp", safe="") in url
    assert f"alt=media&token={tok}" in url


# --- download (mocked) --------------------------------------------------------

def test_download_returns_bytes_for_image(monkeypatch):
    monkeypatch.setattr(
        ip.requests, "get",
        lambda *a, **k: _FakeResponse(content=b"IMGBYTES", headers={"Content-Type": "image/jpeg"}),
    )
    assert ip.download("https://example/x.jpg") == b"IMGBYTES"


def test_download_rejects_non_image(monkeypatch):
    monkeypatch.setattr(
        ip.requests, "get",
        lambda *a, **k: _FakeResponse(content=b"<html>", headers={"Content-Type": "text/html"}),
    )
    with pytest.raises(ValueError, match="not an image"):
        ip.download("https://example/x.html")


# --- upload (mocked) ----------------------------------------------------------

def test_upload_sets_token_cache_control_and_returns_stable_url(monkeypatch):
    captured = {}

    def fake_post(url, *, data, headers, timeout):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        return _FakeResponse(status=200)

    monkeypatch.setattr(ip.requests, "post", fake_post)

    returned = ip.upload(b"WEBPBYTES", "kid-A", "bucket.firebasestorage.app", "TOKEN123")

    # Returned URL is the deterministic public download URL.
    expected_token = ip.download_token("kid-A")
    assert returned == ip.download_url("bucket.firebasestorage.app", "kid-A", expected_token)

    # Hit the GCS multipart upload endpoint with the bearer token.
    assert "uploadType=multipart" in captured["url"]
    assert "bucket.firebasestorage.app" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer TOKEN123"
    assert captured["headers"]["Content-Type"].startswith("multipart/related")

    # Body carries the object name, cache-control, the WebP bytes, and the same token.
    body = captured["data"]
    assert b"onsen-images/kid-A.webp" in body
    assert ip.CACHE_CONTROL.encode() in body
    assert expected_token.encode() in body
    assert b"WEBPBYTES" in body
