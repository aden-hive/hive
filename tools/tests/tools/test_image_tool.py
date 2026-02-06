"""Tests for image_tool (FastMCP)."""

from pathlib import Path
import pytest
import sys

from fastmcp import FastMCP

# Import module & register_tools always so tests can monkeypatch PIL availability
from aden_tools.tools.image_tools import image_tool as image_tool_mod
from aden_tools.tools.image_tools.image_tool import register_tools

# Detect Pillow availability (for creating sample images); tests can simulate absence via monkeypatch
try:
    from PIL import Image  # type: ignore
    PILLOW_AVAILABLE = True
except Exception:
    PILLOW_AVAILABLE = False


@pytest.fixture
def mcp() -> FastMCP:
    """Create a fresh FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def image_tools(mcp: FastMCP):
    """Register image tools and return mapping of tool functions."""
    if not PILLOW_AVAILABLE:
        pytest.skip("Pillow not installed")
    register_tools(mcp)
    return {
        "resize": mcp._tool_manager._tools["image_resize"].fn,
        "compress": mcp._tool_manager._tools["image_compress"].fn,
        "convert": mcp._tool_manager._tools["image_convert"].fn,
        "metadata": mcp._tool_manager._tools["image_metadata"].fn,
    }


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    """Create a simple PNG image."""
    if not PILLOW_AVAILABLE:
        pytest.skip("Pillow not installed")
    p = tmp_path / "sample.png"
    Image.new("RGB", (100, 100), color="red").save(p, "PNG")
    return p


@pytest.fixture
def sample_jpeg(tmp_path: Path) -> Path:
    """Create a simple JPEG image."""
    if not PILLOW_AVAILABLE:
        pytest.skip("Pillow not installed")
    p = tmp_path / "sample.jpg"
    Image.new("RGB", (200, 200), color="blue").save(p, "JPEG", quality=85)
    return p


@pytest.fixture
def sample_rgba(tmp_path: Path) -> Path:
    """Create an RGBA PNG (transparent) image."""
    if not PILLOW_AVAILABLE:
        pytest.skip("Pillow not installed")
    p = tmp_path / "sample_rgba.png"
    Image.new("RGBA", (150, 150), color=(255, 0, 0, 128)).save(p, "PNG")
    return p


# -----------------------
# image_resize tests
# -----------------------
class TestImageResize:
    def test_resize_file_not_found(self, image_tools, tmp_path: Path):
        res = image_tools["resize"](image_path=str(tmp_path / "missing.png"), width=50, height=50)
        assert "error" in res
        assert "not found" in res["error"].lower()

    def test_resize_invalid_extension(self, image_tools, tmp_path: Path):
        txt = tmp_path / "t.txt"
        txt.write_text("not an image")
        res = image_tools["resize"](image_path=str(txt), width=50, height=50)
        assert "error" in res
        assert "unsupported" in res["error"].lower()

    def test_resize_basic(self, image_tools, sample_png: Path, tmp_path: Path):
        out = tmp_path / "out.png"
        res = image_tools["resize"](
            image_path=str(sample_png), width=50, height=50, maintain_aspect_ratio=False, output_path=str(out)
        )
        assert res.get("success") is True
        assert Path(res["output_path"]).exists()
        assert res["original_size"] == [100, 100]
        assert res["new_size"] == [50, 50]

    def test_resize_maintain_aspect(self, image_tools, sample_png: Path):
        res = image_tools["resize"](image_path=str(sample_png), width=200, height=50, maintain_aspect_ratio=True)
        assert res.get("success") is True
        # original is 100x100, constrained height -> new_size should be <= (200,50)
        w, h = res["new_size"]
        assert h <= 50 and w <= 200

    def test_resize_dimension_validation(self, image_tools, sample_png: Path):
        res = image_tools["resize"](image_path=str(sample_png), width=0, height=100)
        assert "error" in res
        assert "positive" in res["error"].lower()


# -----------------------
# image_compress tests
# -----------------------
class TestImageCompress:
    def test_compress_file_not_found(self, image_tools, tmp_path: Path):
        res = image_tools["compress"](image_path=str(tmp_path / "missing.jpg"), quality=75)
        assert "error" in res

    def test_compress_quality_validation(self, image_tools, sample_jpeg: Path):
        res = image_tools["compress"](image_path=str(sample_jpeg), quality=5)
        assert "error" in res
        assert "quality" in res["error"].lower()

        res2 = image_tools["compress"](image_path=str(sample_jpeg), quality=100)
        assert "error" in res2

    def test_compress_jpeg_reduces_size(self, image_tools, sample_jpeg: Path, tmp_path: Path):
        original_kb = round(sample_jpeg.stat().st_size / 1024, 2)
        out = tmp_path / "compressed.jpg"
        res = image_tools["compress"](image_path=str(sample_jpeg), quality=30, output_path=str(out))
        assert res.get("success") is True
        assert Path(res["output_path"]).exists()
        compressed_kb = res["compressed_kb"]
        # allow small variance
        assert compressed_kb <= original_kb + 1.0

    def test_compress_png_outputs_file(self, image_tools, sample_png: Path, tmp_path: Path):
        out = tmp_path / "compressed.png"
        res = image_tools["compress"](image_path=str(sample_png), quality=75, output_path=str(out))
        assert res.get("success") is True
        assert Path(res["output_path"]).exists()


# -----------------------
# image_convert tests
# -----------------------
class TestImageConvert:
    def test_convert_file_not_found(self, image_tools, tmp_path: Path):
        res = image_tools["convert"](image_path=str(tmp_path / "missing.png"), target_format="jpg")
        assert "error" in res

    def test_convert_unsupported_format(self, image_tools, sample_png: Path):
        res = image_tools["convert"](image_path=str(sample_png), target_format="tiff")
        assert "error" in res
        assert "unsupported" in res["error"].lower()

    def test_convert_png_to_jpg_and_back(self, image_tools, sample_png: Path, tmp_path: Path):
        out_jpg = tmp_path / "to.jpg"
        res1 = image_tools["convert"](image_path=str(sample_png), target_format="jpg", output_path=str(out_jpg))
        assert res1.get("success") is True
        assert Path(res1["output_path"]).exists()
        out_png = tmp_path / "back.png"
        res2 = image_tools["convert"](image_path=str(out_jpg), target_format="png", output_path=str(out_png))
        assert res2.get("success") is True
        assert Path(res2["output_path"]).exists()

    def test_convert_to_webp(self, image_tools, sample_png: Path, tmp_path: Path):
        out_webp = tmp_path / "img.webp"
        res = image_tools["convert"](image_path=str(sample_png), target_format="webp", output_path=str(out_webp))
        assert res.get("success") is True
        assert Path(res["output_path"]).suffix.lower() == ".webp"


# -----------------------
# image_metadata tests
# -----------------------
class TestImageMetadata:
    def test_metadata_file_not_found(self, image_tools, tmp_path: Path):
        res = image_tools["metadata"](image_path=str(tmp_path / "missing.png"))
        assert "error" in res

    def test_metadata_basic(self, image_tools, sample_png: Path):
        res = image_tools["metadata"](image_path=str(sample_png), include_exif=False)
        assert res.get("success") is True
        assert res["format"].upper() in {"PNG", "JPEG"}
        assert res["size"] == [100, 100]
        assert res["file_size_kb"] > 0

    def test_metadata_exif_no_crash(self, image_tools, sample_jpeg: Path):
        res = image_tools["metadata"](image_path=str(sample_jpeg), include_exif=True)
        assert res.get("success") is True

    def test_metadata_rgba(self, image_tools, sample_rgba: Path):
        res = image_tools["metadata"](image_path=str(sample_rgba))
        assert res.get("success") is True
        assert res["mode"] in ("RGBA", "RGB")

# -----------------------
# edge cases
# -----------------------
class TestEdgeCases:
    def test_corrupted_file(self, image_tools, tmp_path: Path):
        corrupted = tmp_path / "bad.png"
        corrupted.write_bytes(b"not a png")
        res = image_tools["metadata"](image_path=str(corrupted))
        assert "error" in res

    @pytest.mark.skipif(sys.platform.startswith("win"), reason="chmod-based permission denial is not reliable on Windows")
    def test_permission_error(self, image_tools, sample_png: Path):
        # Make file unreadable (may require OS support)
        sample_png.chmod(0o000)
        try:
            res = image_tools["metadata"](image_path=str(sample_png))
            assert "error" in res
        finally:
            sample_png.chmod(0o644)