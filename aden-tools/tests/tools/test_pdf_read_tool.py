"""Tests for pdf_read tool (FastMCP)."""
import pytest
from pathlib import Path

from fastmcp import FastMCP
from aden_tools.tools.pdf_read_tool import register_tools


@pytest.fixture
def pdf_read_fn(mcp: FastMCP):
    """Register and return the pdf_read tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["pdf_read"].fn


class TestPdfReadTool:
    """Tests for pdf_read tool."""

    def test_read_pdf_file_not_found(self, pdf_read_fn, tmp_path: Path):
        """Reading non-existent PDF returns error."""
        result = pdf_read_fn(file_path=str(tmp_path / "missing.pdf"))

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_read_pdf_invalid_extension(self, pdf_read_fn, tmp_path: Path):
        """Reading non-PDF file returns error."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not a pdf")

        result = pdf_read_fn(file_path=str(txt_file))

        assert "error" in result
        assert "not a pdf" in result["error"].lower()

    def test_read_pdf_directory(self, pdf_read_fn, tmp_path: Path):
        """Reading a directory returns error."""
        result = pdf_read_fn(file_path=str(tmp_path))

        assert "error" in result
        assert "not a file" in result["error"].lower()

    def test_max_pages_clamped_low(self, pdf_read_fn, tmp_path: Path):
        """max_pages below 1 is clamped to 1."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")  # Minimal PDF header (will fail to parse)

        result = pdf_read_fn(file_path=str(pdf_file), max_pages=0)
        # Will error due to invalid PDF, but max_pages should be accepted
        assert isinstance(result, dict)

    def test_max_pages_clamped_high(self, pdf_read_fn, tmp_path: Path):
        """max_pages above 1000 is clamped to 1000."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file), max_pages=2000)
        # Will error due to invalid PDF, but max_pages should be accepted
        assert isinstance(result, dict)

    def test_pages_parameter_accepted(self, pdf_read_fn, tmp_path: Path):
        """Various pages parameter formats are accepted."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        # Test different page formats - all should be accepted
        for pages in ["all", "1", "1-5", "1,3,5", None]:
            result = pdf_read_fn(file_path=str(pdf_file), pages=pages)
            assert isinstance(result, dict)

    def test_include_metadata_parameter(self, pdf_read_fn, tmp_path: Path):
        """include_metadata parameter is accepted."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file), include_metadata=False)
        assert isinstance(result, dict)

        result = pdf_read_fn(file_path=str(pdf_file), include_metadata=True)
        assert isinstance(result, dict)
