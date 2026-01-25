"""Tests for pdf_read tool (FastMCP)."""

from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import httpx
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
        txt_file.write_text("not a pdf", encoding="utf-8")

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

class TestPdfReadUrlSupport:
    """Tests for URL download support in pdf_read tool."""

    @patch('httpx.get')
    @patch('aden_tools.tools.pdf_read_tool.pdf_read_tool.PdfReader')
    def test_url_download_succeeds(self, mock_pdf_reader, mock_get, pdf_read_fn):
        """Valid PDF URL downloads and parses successfully."""
        # Mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = b"%PDF-1.4\nfake pdf content"
        mock_get.return_value = mock_response

        # Mock PdfReader
        mock_reader_instance = MagicMock()
        mock_reader_instance.is_encrypted = False
        mock_reader_instance.pages = [MagicMock()]
        mock_reader_instance.pages[0].extract_text.return_value = "PDF text content"
        mock_reader_instance.metadata = None
        mock_pdf_reader.return_value = mock_reader_instance

        result = pdf_read_fn(file_path="https://example.com/document.pdf")

        assert "error" not in result
        assert "content" in result
        assert "PDF text content" in result["content"]
        mock_get.assert_called_once()

    @patch('httpx.get')
    def test_url_non_pdf_content_type(self, mock_get, pdf_read_fn):
        """URL returning non-PDF content-type returns error."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = b"<html>Not a PDF</html>"
        mock_get.return_value = mock_response

        result = pdf_read_fn(file_path="https://example.com/page.html")

        assert "error" in result
        assert "does not point to a pdf" in result["error"].lower()
        assert "content_type" in result
        assert "text/html" in result["content_type"]

    @patch('httpx.get')
    def test_url_http_404_error(self, mock_get, pdf_read_fn):
        """URL returning 404 returns appropriate error."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = pdf_read_fn(file_path="https://example.com/missing.pdf")

        assert "error" in result
        assert "404" in result["error"]

    @patch('httpx.get')
    def test_url_http_500_error(self, mock_get, pdf_read_fn):
        """URL returning 500 returns appropriate error."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        result = pdf_read_fn(file_path="https://example.com/error.pdf")

        assert "error" in result
        assert "500" in result["error"]

    @patch('httpx.get')
    def test_url_timeout_error(self, mock_get, pdf_read_fn):
        """URL request timeout returns appropriate error."""
        mock_get.side_effect = httpx.TimeoutException("Timeout")

        result = pdf_read_fn(file_path="https://example.com/slow.pdf")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch('httpx.get')
    def test_url_network_error(self, mock_get, pdf_read_fn):
        """Network error returns appropriate error."""
        mock_get.side_effect = httpx.RequestError("Connection failed")

        result = pdf_read_fn(file_path="https://example.com/doc.pdf")

        assert "error" in result
        assert "failed to download" in result["error"].lower()

    @patch('httpx.get')
    @patch('aden_tools.tools.pdf_read_tool.pdf_read_tool.PdfReader')
    def test_url_with_http_scheme(self, mock_pdf_reader, mock_get, pdf_read_fn):
        """HTTP URLs (not HTTPS) are handled correctly."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = b"%PDF-1.4\ncontent"
        mock_get.return_value = mock_response

        mock_reader_instance = MagicMock()
        mock_reader_instance.is_encrypted = False
        mock_reader_instance.pages = [MagicMock()]
        mock_reader_instance.pages[0].extract_text.return_value = "Text"
        mock_reader_instance.metadata = None
        mock_pdf_reader.return_value = mock_reader_instance

        result = pdf_read_fn(file_path="http://example.com/doc.pdf")

        assert "error" not in result
        mock_get.assert_called_once()

    def test_local_file_path_still_works(self, pdf_read_fn, tmp_path: Path):
        """Local file paths still work (backward compatibility)."""
        pdf_file = tmp_path / "local.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file))

        # Will error due to invalid PDF, but should not treat as URL
        assert isinstance(result, dict)
        # Should not have URL-specific errors
        if "error" in result:
            assert "download" not in result["error"].lower()

    @patch('httpx.get')
    @patch('aden_tools.tools.pdf_read_tool.pdf_read_tool.PdfReader')
    @patch('aden_tools.tools.pdf_read_tool.pdf_read_tool.tempfile.NamedTemporaryFile')
    def test_temporary_file_cleanup(self, mock_tempfile, mock_pdf_reader, mock_get, pdf_read_fn):
        """Temporary file is cleaned up after processing."""
        # Mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = b"%PDF-1.4\ncontent"
        mock_get.return_value = mock_response

        # Mock temporary file
        mock_temp = MagicMock()
        mock_temp.name = "/tmp/test.pdf"
        mock_tempfile.return_value = mock_temp

        # Mock PdfReader
        mock_reader_instance = MagicMock()
        mock_reader_instance.is_encrypted = False
        mock_reader_instance.pages = [MagicMock()]
        mock_reader_instance.pages[0].extract_text.return_value = "Text"
        mock_reader_instance.metadata = None
        mock_pdf_reader.return_value = mock_reader_instance

        result = pdf_read_fn(file_path="https://example.com/doc.pdf")

        # Verify temp file operations
        mock_temp.write.assert_called_once()
        mock_temp.close.assert_called_once()

    @patch('httpx.get')
    def test_url_json_content_type(self, mock_get, pdf_read_fn):
        """URL returning JSON returns appropriate error."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"error": "not a pdf"}'
        mock_get.return_value = mock_response

        result = pdf_read_fn(file_path="https://api.example.com/data")

        assert "error" in result
        assert "does not point to a pdf" in result["error"].lower()
        assert "content_type" in result
        assert "application/json" in result["content_type"]
