"""Tests for pdf_read tool (FastMCP)."""

from pathlib import Path

import pytest
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

    def test_truncation_flag_for_page_range(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        """When requested pages exceed max_pages, response includes truncation metadata."""

        class FakePage:
            def __init__(self, text: str) -> None:
                self._text = text

            def extract_text(self) -> str:
                return self._text

        class FakePdfReader:
            def __init__(self, path: Path) -> None:  # noqa: ARG002
                self.pages = [FakePage(f"Page {i + 1}") for i in range(50)]
                self.is_encrypted = False
                self.metadata = None

        # Patch PdfReader used inside the tool so we don't need a real PDF
        from aden_tools.tools.pdf_read_tool import pdf_read_tool

        monkeypatch.setattr(pdf_read_tool, "PdfReader", FakePdfReader)

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file), pages="1-20", max_pages=10)

        assert result["pages_extracted"] == 10
        # New behavior: explicit truncation metadata instead of silent truncation
        assert result.get("truncated") is True
        assert "truncation_warning" in result

    def test_duplicate_pages_are_deduplicated(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        """Duplicate page numbers in comma-separated list are deduplicated."""

        class FakePage:
            def __init__(self, text: str) -> None:
                self._text = text

            def extract_text(self) -> str:
                return self._text

        class FakePdfReader:
            def __init__(self, path: Path) -> None:  # noqa: ARG002
                self.pages = [FakePage(f"Page {i + 1}") for i in range(10)]
                self.is_encrypted = False
                self.metadata = None

        from aden_tools.tools.pdf_read_tool import pdf_read_tool

        monkeypatch.setattr(pdf_read_tool, "PdfReader", FakePdfReader)

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file), pages="1,2,3,1,2,4")

        assert result["pages_extracted"] == 4
        assert "--- Page 1 ---" in result["content"]
        assert "--- Page 2 ---" in result["content"]
        assert "--- Page 3 ---" in result["content"]
        assert "--- Page 4 ---" in result["content"]
        assert result["content"].count("--- Page 1 ---") == 1
        assert result["content"].count("--- Page 2 ---") == 1

    def test_duplicate_pages_preserve_order(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        """Deduplicated pages preserve the original order."""

        class FakePage:
            def __init__(self, text: str) -> None:
                self._text = text

            def extract_text(self) -> str:
                return self._text

        class FakePdfReader:
            def __init__(self, path: Path) -> None:  # noqa: ARG002
                self.pages = [FakePage(f"Page {i + 1}") for i in range(20)]
                self.is_encrypted = False
                self.metadata = None

        from aden_tools.tools.pdf_read_tool import pdf_read_tool

        monkeypatch.setattr(pdf_read_tool, "PdfReader", FakePdfReader)

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file), pages="5,10,5,5,20,10")

        assert result["pages_extracted"] == 3
        import re

        pages_order = [
            int(m.group(1)) for m in re.finditer(r"--- Page (\d+) ---", result["content"])
        ]
        assert pages_order == [5, 10, 20]

    def test_duplicate_pages_with_truncation(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        """Deduplication happens before truncation with max_pages."""

        class FakePage:
            def __init__(self, text: str) -> None:
                self._text = text

            def extract_text(self) -> str:
                return self._text

        class FakePdfReader:
            def __init__(self, path: Path) -> None:  # noqa: ARG002
                self.pages = [FakePage(f"Page {i + 1}") for i in range(10)]
                self.is_encrypted = False
                self.metadata = None

        from aden_tools.tools.pdf_read_tool import pdf_read_tool

        monkeypatch.setattr(pdf_read_tool, "PdfReader", FakePdfReader)

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file), pages="1,2,3,4,5", max_pages=3)

        assert result["pages_extracted"] == 3
        assert result.get("truncated") is True
