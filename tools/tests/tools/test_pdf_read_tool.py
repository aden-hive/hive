"""Tests for pdf_read tool (FastMCP)."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.pdf_read_tool import register_tools


@pytest.fixture
def pdf_read_fn(mcp: FastMCP):
    """Register and return the pdf_read tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["pdf_read"].fn


# ---------------------------------------------------------------------------
# pdfplumber mock helpers
# ---------------------------------------------------------------------------


class FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str | None:
        return self._text


class FakePdf:
    """Mimics pdfplumber.PDF for the bits the tool reads."""

    def __init__(self, page_texts: list[str], metadata: dict | None = None) -> None:
        self.pages = [FakePage(t) for t in page_texts]
        self.metadata = metadata or {}


@contextmanager
def fake_pdfplumber_open(page_texts: list[str], metadata: dict | None = None):
    """Match pdfplumber.open's context-manager shape."""
    yield FakePdf(page_texts, metadata)


def patch_pdfplumber(monkeypatch, page_texts: list[str], metadata: dict | None = None):
    """Replace pdfplumber.open in the tool module with a fake."""
    from aden_tools.tools.pdf_read_tool import pdf_read_tool

    def _open(_path, password=""):
        return fake_pdfplumber_open(page_texts, metadata)

    monkeypatch.setattr(pdf_read_tool.pdfplumber, "open", _open)


class TestPdfReadTool:
    """Local-file behavior."""

    def test_read_pdf_file_not_found(self, pdf_read_fn, tmp_path: Path):
        result = pdf_read_fn(file_path=str(tmp_path / "missing.pdf"))
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_read_pdf_invalid_extension(self, pdf_read_fn, tmp_path: Path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not a pdf", encoding="utf-8")
        result = pdf_read_fn(file_path=str(txt_file))
        assert "error" in result
        assert "not a pdf" in result["error"].lower()

    def test_read_pdf_directory(self, pdf_read_fn, tmp_path: Path):
        result = pdf_read_fn(file_path=str(tmp_path))
        assert "error" in result
        assert "not a file" in result["error"].lower()

    def test_max_pages_clamped_low(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        patch_pdfplumber(monkeypatch, ["page text"])
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file), max_pages=0)
        # 0 clamps to 1 — extraction succeeds.
        assert "error" not in result
        assert result["pages_extracted"] == 1

    def test_max_pages_clamped_high(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        patch_pdfplumber(monkeypatch, ["p"] * 5)
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file), max_pages=2000)
        # 2000 clamps to 1000 — still extracts all 5 pages.
        assert "error" not in result
        assert result["pages_extracted"] == 5

    def test_pages_parameter_accepted(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        patch_pdfplumber(monkeypatch, ["a", "b", "c", "d", "e"])
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        for pages, expected in (("all", 5), ("1", 1), ("1-3", 3), ("1,3,5", 3), (None, 5)):
            result = pdf_read_fn(file_path=str(pdf_file), pages=pages)
            assert "error" not in result, f"pages={pages!r} errored: {result}"
            assert result["pages_extracted"] == expected

    def test_include_metadata_parameter(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        patch_pdfplumber(
            monkeypatch,
            ["page"],
            metadata={"Title": "Doc Title", "Author": "Someone"},
        )
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result_no = pdf_read_fn(file_path=str(pdf_file), include_metadata=False)
        assert "metadata" not in result_no

        result_yes = pdf_read_fn(file_path=str(pdf_file), include_metadata=True)
        assert result_yes["metadata"]["title"] == "Doc Title"
        assert result_yes["metadata"]["author"] == "Someone"

    def test_truncation_flag_for_page_range(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        """Requested pages > max_pages: response carries truncation metadata."""
        patch_pdfplumber(monkeypatch, [f"Page {i + 1}" for i in range(50)])
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file), pages="1-20", max_pages=10)

        assert result["pages_extracted"] == 10
        assert result.get("truncated") is True
        assert "truncation_warning" in result

    def test_pages_array_shape(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        """New: result includes per-page entries with number + text."""
        patch_pdfplumber(monkeypatch, ["first page text", "second page text"])
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file))

        assert result["pages"] == [
            {"number": 1, "text": "first page text", "needs_vision": True},
            {"number": 2, "text": "second page text", "needs_vision": True},
        ]
        # Back-compat: marker-joined content still present.
        assert "--- Page 1 ---" in result["content"]
        assert "--- Page 2 ---" in result["content"]

    def test_needs_vision_marker(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        """Pages below the text threshold are flagged needs_vision."""
        # Page 1 is well over 200 chars; page 2 is empty (scanned page).
        long_text = "lorem ipsum " * 50  # ~600 chars
        patch_pdfplumber(monkeypatch, [long_text, ""])
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file))

        assert result["pages"][0]["needs_vision"] is False
        assert result["pages"][1]["needs_vision"] is True
        assert result["needs_vision_pages"] == [2]

    def test_no_needs_vision_pages_key_when_all_have_text(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        """needs_vision_pages omitted when every page is text-rich."""
        long_text = "lorem ipsum " * 50
        patch_pdfplumber(monkeypatch, [long_text, long_text])
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file))

        assert "needs_vision_pages" not in result

    def test_password_propagated_to_pdfplumber(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        """password argument is passed through to pdfplumber.open."""
        from aden_tools.tools.pdf_read_tool import pdf_read_tool

        captured: dict[str, str] = {}

        def fake_open(_path, password=""):
            captured["password"] = password
            return fake_pdfplumber_open(["text"])

        monkeypatch.setattr(pdf_read_tool.pdfplumber, "open", fake_open)
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        pdf_read_fn(file_path=str(pdf_file), password="hunter2")
        assert captured["password"] == "hunter2"

    def test_wrong_password_returns_clear_error(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        """Encryption error from pdfplumber is mapped to a clear error string."""
        from aden_tools.tools.pdf_read_tool import pdf_read_tool

        def fake_open(_path, password=""):
            raise Exception("File has not been decrypted: bad password")

        monkeypatch.setattr(pdf_read_tool.pdfplumber, "open", fake_open)
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file), password="wrong")
        assert "error" in result
        assert "password" in result["error"].lower()

    def test_neither_file_path_nor_files_errors(self, pdf_read_fn):
        result = pdf_read_fn()
        assert "error" in result
        assert "file_path" in result["error"] or "files" in result["error"]

    def test_both_file_path_and_files_errors(self, pdf_read_fn, tmp_path: Path):
        pdf_file = tmp_path / "a.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")
        result = pdf_read_fn(file_path=str(pdf_file), files=[str(pdf_file)])
        assert "error" in result


class TestPdfReadMultiFile:
    """Multi-file mode via `files`."""

    def test_files_returns_pdfs_array(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        patch_pdfplumber(monkeypatch, ["text"])
        a = tmp_path / "a.pdf"
        b = tmp_path / "b.pdf"
        a.write_bytes(b"%PDF-1.4")
        b.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(files=[str(a), str(b)])
        assert "pdfs" in result
        assert len(result["pdfs"]) == 2
        for entry in result["pdfs"]:
            assert "error" not in entry
            assert entry["pages_extracted"] == 1

    def test_files_too_many_errors(self, pdf_read_fn, tmp_path: Path):
        result = pdf_read_fn(files=[str(tmp_path / f"{i}.pdf") for i in range(11)])
        assert "error" in result
        assert "too many" in result["error"].lower()

    def test_files_partial_failure_is_per_entry(self, pdf_read_fn, tmp_path: Path, monkeypatch):
        """One bad PDF in the batch returns error in that entry only."""
        patch_pdfplumber(monkeypatch, ["text"])
        good = tmp_path / "good.pdf"
        good.write_bytes(b"%PDF-1.4")
        missing = tmp_path / "missing.pdf"

        result = pdf_read_fn(files=[str(good), str(missing)])
        assert "pdfs" in result
        assert "error" not in result["pdfs"][0]
        assert "error" in result["pdfs"][1]


class TestPdfReadUrlSupport:
    """URL-fetch behavior."""

    @patch("httpx.get")
    def test_url_download_succeeds(self, mock_get, pdf_read_fn, monkeypatch):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = b"%PDF-1.4\nfake pdf content"
        mock_get.return_value = mock_response

        patch_pdfplumber(monkeypatch, ["PDF text content"])

        result = pdf_read_fn(file_path="https://example.com/document.pdf")
        assert "error" not in result
        assert "PDF text content" in result["content"]
        mock_get.assert_called_once()

    @patch("httpx.get")
    def test_url_non_pdf_content_type(self, mock_get, pdf_read_fn):
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

    @patch("httpx.get")
    def test_url_http_404_error(self, mock_get, pdf_read_fn):
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = pdf_read_fn(file_path="https://example.com/missing.pdf")
        assert "error" in result
        assert "404" in result["error"]

    @patch("httpx.get")
    def test_url_http_500_error(self, mock_get, pdf_read_fn):
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        result = pdf_read_fn(file_path="https://example.com/error.pdf")
        assert "error" in result
        assert "500" in result["error"]

    @patch("httpx.get")
    def test_url_timeout_error(self, mock_get, pdf_read_fn):
        mock_get.side_effect = httpx.TimeoutException("Timeout")

        result = pdf_read_fn(file_path="https://example.com/slow.pdf")
        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("httpx.get")
    def test_url_network_error(self, mock_get, pdf_read_fn):
        mock_get.side_effect = httpx.RequestError("Connection failed")

        result = pdf_read_fn(file_path="https://example.com/doc.pdf")
        assert "error" in result
        assert "failed to download" in result["error"].lower()

    @patch("httpx.get")
    def test_url_with_http_scheme(self, mock_get, pdf_read_fn, monkeypatch):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = b"%PDF-1.4\ncontent"
        mock_get.return_value = mock_response

        patch_pdfplumber(monkeypatch, ["Text"])

        result = pdf_read_fn(file_path="http://example.com/doc.pdf")
        assert "error" not in result
        mock_get.assert_called_once()

    def test_local_file_path_still_works(self, pdf_read_fn, tmp_path: Path):
        pdf_file = tmp_path / "local.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        # No pdfplumber patch: real pdfplumber will fail to parse the stub,
        # so we just assert the URL-download path was NOT taken (no "download"
        # error wording).
        result = pdf_read_fn(file_path=str(pdf_file))
        assert isinstance(result, dict)
        if "error" in result:
            assert "download" not in result["error"].lower()

    @patch("httpx.get")
    @patch("aden_tools.tools.pdf_read_tool.pdf_read_tool.tempfile.NamedTemporaryFile")
    def test_temporary_file_cleanup(self, mock_tempfile, mock_get, pdf_read_fn, monkeypatch):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = b"%PDF-1.4\ncontent"
        mock_get.return_value = mock_response

        mock_temp = MagicMock()
        mock_temp.name = "/tmp/test_pdf_cleanup.pdf"
        mock_tempfile.return_value = mock_temp

        patch_pdfplumber(monkeypatch, ["Text"])

        pdf_read_fn(file_path="https://example.com/doc.pdf")

        mock_temp.write.assert_called_once()
        mock_temp.close.assert_called_once()

    @patch("httpx.get")
    def test_url_json_content_type(self, mock_get, pdf_read_fn):
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

    @patch("httpx.get")
    def test_url_exceeds_max_bytes(self, mock_get, pdf_read_fn):
        big = b"x" * (3 * 1024 * 1024)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = b"%PDF-1.4\n" + big
        mock_get.return_value = mock_response

        result = pdf_read_fn(file_path="https://example.com/big.pdf", max_bytes_mb=2.0)
        assert "error" in result
        assert "max_bytes" in result["error"].lower()

    @patch("httpx.get")
    def test_url_content_length_header_rejects_oversized(self, mock_get, pdf_read_fn):
        """Even when Content-Length lies upward, oversized bodies fail."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf", "content-length": "999999999"}
        mock_response.content = b"%PDF-1.4"
        mock_get.return_value = mock_response

        result = pdf_read_fn(file_path="https://example.com/huge.pdf", max_bytes_mb=1.0)
        assert "error" in result
        assert "max_bytes" in result["error"].lower()

    def test_ssrf_localhost_rejected(self, pdf_read_fn):
        result = pdf_read_fn(file_path="http://localhost:8080/doc.pdf")
        assert "error" in result
        assert "private" in result["error"].lower() or "loopback" in result["error"].lower()

    def test_ssrf_link_local_rejected(self, pdf_read_fn):
        result = pdf_read_fn(file_path="http://169.254.169.254/latest/meta-data/")
        assert "error" in result

    def test_ssrf_rfc1918_rejected(self, pdf_read_fn):
        for host in ("10.0.0.5", "192.168.1.1", "172.20.0.1"):
            result = pdf_read_fn(file_path=f"http://{host}/file.pdf")
            assert "error" in result, f"{host} should be rejected"


# ---------------------------------------------------------------------------
# Layer G: fail-fast + terminal-yield. pdf_read must bound its own runtime
# well under the framework's 60s tool-call timeout, and on failure must
# return a structured response that steers the agent toward terminal_exec
# fallbacks (pdftotext, pdfinfo, pdfimages, pdfgrep). The previous behavior
# burnt the whole 60s budget per attempt with no actionable next step.
# ---------------------------------------------------------------------------


class TestPdfReadFailFast:
    """Internal timeout + terminal-yield response."""

    def test_pdf_extract_times_out_yields_terminal_hint(self, pdf_read_fn, tmp_path: Path, monkeypatch) -> None:
        """A hanging pdfplumber.open returns within the internal-timeout
        budget (not the framework's 60s ceiling) with a structured
        terminal-yield response."""
        import threading as _threading
        import time as _time

        from aden_tools.tools.pdf_read_tool import pdf_read_tool

        # Crank the timeout down so the test doesn't actually wait 20s.
        monkeypatch.setattr(pdf_read_tool, "_PDF_EXTRACT_TIMEOUT_SECONDS", 0.5)

        # pdfplumber.open blocks forever on a never-set Event. The worker
        # thread is daemon=True so the test process can exit even with it
        # parked here.
        forever = _threading.Event()

        def fake_open(_path, password=""):
            forever.wait()
            raise AssertionError("should not return")

        monkeypatch.setattr(pdf_read_tool.pdfplumber, "open", fake_open)

        pdf_file = tmp_path / "stuck.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        started = _time.monotonic()
        result = pdf_read_fn(file_path=str(pdf_file))
        elapsed = _time.monotonic() - started

        # Strict ceiling: 0.5s budget + small overhead. Far below 60s.
        assert elapsed < 5.0, f"pdf_read must fail fast on a stuck pdfplumber; took {elapsed:.2f}s"
        assert result["error"] == "pdf_extract_timeout"
        assert result["path"] == str(pdf_file.resolve())
        # Yield response carries the cheatsheet + a concrete next call.
        assert "terminal_hint" in result
        assert "pdftotext" in result["terminal_hint"]
        assert "next_step" in result
        assert "terminal_exec" in result["next_step"]
        assert "pdftotext" in result["next_step"]
        # Release the worker so the daemon thread isn't permanently parked
        # (still daemon=True so process can exit either way).
        forever.set()

    def test_scanned_pdf_response_includes_terminal_hint(self, pdf_read_fn, tmp_path: Path, monkeypatch) -> None:
        """The needs_vision_pages success-response now augments the
        existing attach_file next_step with a terminal_hint cheatsheet
        so non-vision models have a fallback path."""
        patch_pdfplumber(monkeypatch, ["", "", ""])  # all-empty pages → scanned
        pdf_file = tmp_path / "scanned.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file))

        assert result["needs_vision_pages"] == [1, 2, 3]
        # Primary path unchanged: attach_file on vision-capable models.
        assert "attach_file" in result["next_step"]
        # Secondary path (Layer G): terminal-tool cheatsheet for the
        # non-vision case.
        assert "terminal_hint" in result
        assert "pdftotext" in result["terminal_hint"]

    def test_pdfplumber_open_failure_yields_terminal_hint(self, pdf_read_fn, tmp_path: Path, monkeypatch) -> None:
        """A non-encryption failure inside pdfplumber.open lands in the
        terminal-yield response so the agent can probe via pdfinfo."""
        from aden_tools.tools.pdf_read_tool import pdf_read_tool

        def fake_open(_path, password=""):
            raise RuntimeError("PDF header malformed: bytes 0x00 0x00")

        monkeypatch.setattr(pdf_read_tool.pdfplumber, "open", fake_open)

        pdf_file = tmp_path / "malformed.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file))

        assert result.get("error", "").startswith("Failed to open PDF")
        assert "terminal_hint" in result
        assert "pdfinfo" in result["next_step"]

    def test_encrypted_pdf_yields_with_legacy_error_message(self, pdf_read_fn, tmp_path: Path, monkeypatch) -> None:
        """Encrypted-PDF responses retain the legacy ``Cannot read encrypted
        PDF`` message (existing callers may pattern-match on it) but now
        also carry the terminal_hint so the agent can route through qpdf."""
        from aden_tools.tools.pdf_read_tool import pdf_read_tool

        def fake_open(_path, password=""):
            raise Exception("File has not been decrypted: bad password")

        monkeypatch.setattr(pdf_read_tool.pdfplumber, "open", fake_open)

        pdf_file = tmp_path / "locked.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        result = pdf_read_fn(file_path=str(pdf_file), password="wrong")

        assert "encrypted" in result["error"].lower()
        assert "terminal_hint" in result
        assert "qpdf" in result["next_step"]
