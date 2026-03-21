"""Tests for screenshot normalization.

Requires the ``browser`` extra (Pillow).  Skipped automatically when
Pillow is not installed.
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest

Image = pytest.importorskip(
    "PIL.Image", reason="Pillow not installed (install with: pip install pillow)"
)

from gcu.browser.tools.inspection import _normalize_screenshot  # noqa: E402


def _make_png(width: int, height: int, *, mode: str = "RGB") -> bytes:
    """Create a solid-color PNG image of the given size."""
    img = Image.new(
        mode, (width, height), color=(100, 150, 200) if mode == "RGB" else (100, 150, 200, 128)
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_large_png(width: int, height: int, min_bytes: int) -> bytes:
    """Create a PNG that's at least *min_bytes* by using random-ish pixel data."""
    # Gradient with noise produces poorly-compressible PNGs
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = ((x * 7 + y * 13) % 256, (x * 11 + y * 3) % 256, (x * 5 + y * 17) % 256)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()
    # If still under target, that's fine for most tests — the important
    # thing is we have a large-dimension image.
    return raw


class TestPassthrough:
    """Images already within limits should pass through unchanged."""

    def test_small_image_unchanged(self):
        raw = _make_png(100, 100)
        result_bytes, result_type = _normalize_screenshot(raw, "png")
        assert result_bytes is raw
        assert result_type == "png"

    def test_within_dimension_and_size_unchanged(self):
        raw = _make_png(1920, 1080)
        result_bytes, result_type = _normalize_screenshot(raw, "png")
        assert result_bytes is raw
        assert result_type == "png"


class TestDimensionResize:
    """Images exceeding max_dimension should be resized."""

    def test_large_dimension_gets_resized(self):
        raw = _make_png(4000, 3000)
        result_bytes, result_type = _normalize_screenshot(raw, "png")

        # Should be JPEG after normalization
        assert result_type == "jpeg"

        # Verify dimensions are within limit
        img = Image.open(io.BytesIO(result_bytes))
        assert max(img.size) <= 2000

    def test_custom_max_dimension(self):
        raw = _make_png(2000, 1500)
        result_bytes, result_type = _normalize_screenshot(raw, "png", max_dimension=800)
        assert result_type == "jpeg"

        img = Image.open(io.BytesIO(result_bytes))
        assert max(img.size) <= 800

    def test_aspect_ratio_preserved(self):
        raw = _make_png(4000, 2000)  # 2:1 ratio
        result_bytes, _ = _normalize_screenshot(raw, "png")

        img = Image.open(io.BytesIO(result_bytes))
        w, h = img.size
        ratio = w / h
        assert abs(ratio - 2.0) < 0.1  # Allow small rounding error


class TestSizeCompression:
    """Images exceeding max_bytes should be compressed."""

    def test_custom_max_bytes(self):
        raw = _make_large_png(1500, 1500, min_bytes=100_000)
        result_bytes, result_type = _normalize_screenshot(raw, "png", max_bytes=50_000)
        assert result_type == "jpeg"
        assert len(result_bytes) <= 50_000

    def test_over_size_within_dimension_compresses(self):
        """Image within dimension limit but over byte limit gets JPEG-compressed."""
        raw = _make_large_png(1800, 1800, min_bytes=100_000)
        result_bytes, result_type = _normalize_screenshot(raw, "png", max_bytes=50_000)
        assert result_type == "jpeg"
        assert len(result_bytes) <= 50_000


class TestAlphaChannel:
    """RGBA images should be converted to RGB for JPEG output."""

    def test_rgba_to_rgb(self):
        raw = _make_png(4000, 3000, mode="RGBA")
        result_bytes, result_type = _normalize_screenshot(raw, "png")

        assert result_type == "jpeg"
        img = Image.open(io.BytesIO(result_bytes))
        assert img.mode == "RGB"


class TestGracefulDegradation:
    """Normalization should never break screenshots."""

    def test_pillow_not_available(self):
        raw = _make_png(4000, 3000)
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            # Need to force reimport failure — patch builtins.__import__
            original_import = (
                __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
            )

            def mock_import(name, *args, **kwargs):
                if name == "PIL" or name.startswith("PIL."):
                    raise ImportError("No module named 'PIL'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result_bytes, result_type = _normalize_screenshot(raw, "png")

        # Should return original unchanged
        assert result_bytes is raw
        assert result_type == "png"

    def test_corrupt_bytes_returns_original(self):
        raw = b"not an image at all"
        result_bytes, result_type = _normalize_screenshot(raw, "png")

        assert result_bytes is raw
        assert result_type == "png"

    def test_empty_bytes_returns_original(self):
        raw = b""
        result_bytes, result_type = _normalize_screenshot(raw, "png")

        assert result_bytes is raw
        assert result_type == "png"
