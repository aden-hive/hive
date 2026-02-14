import tempfile
from pathlib import Path

import pytest
from pypdf import PdfWriter

from aden_tools.tools.pdf_read_tool.pdf_read_tool import pdf_read_logic


# -----------------------
# Helpers
# -----------------------

def create_test_pdf(path: Path, pages: int = 1):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)

    with open(path, "wb") as f:
        writer.write(f)


# -----------------------
# Tests
# -----------------------

def test_pdf_read_basic():
    """Test reading a single-page PDF."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "test.pdf"
        create_test_pdf(pdf_path, pages=1)

        result = pdf_read_logic(str(pdf_path))

        assert "error" not in result
        assert result["total_pages"] == 1
        assert result["pages_extracted"] == 1
        assert "content" in result


def test_pdf_read_multipage():
    """Test reading a multi-page PDF."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "multi.pdf"
        create_test_pdf(pdf_path, pages=3)

        result = pdf_read_logic(str(pdf_path))

        assert "error" not in result
        assert result["total_pages"] == 3
        assert result["pages_extracted"] == 3
        assert "content" in result


def test_pdf_read_file_not_found():
    """Test handling of missing file."""
    result = pdf_read_logic("non_existent_file.pdf")

    assert "error" in result
    assert "not found" in result["error"].lower()


def test_pdf_read_invalid_file():
    """Test handling of invalid/corrupted PDF."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_path = Path(tmpdir) / "fake.pdf"

        fake_path.write_text("this is not a real pdf")

        result = pdf_read_logic(str(fake_path))

        assert "error" in result
        assert isinstance(result["error"], str)
        assert len(result["error"]) > 0

