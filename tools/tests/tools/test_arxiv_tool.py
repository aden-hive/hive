"""
Tests for the arXiv search and download tool.

Covers:
- search_papers: success, id_list lookup, validation, sorting, error handling
- download_paper: success, missing paper, no PDF URL, network error,
    bad content type, file cleanup on error
- Tool registration
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import arxiv
from fastmcp import FastMCP

from aden_tools.tools.arxiv_tool.arxiv_tool import register_tools

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mcp() -> FastMCP:
    mcp = FastMCP("test-arxiv")
    register_tools(mcp)
    return mcp


def _get_tool(mcp: FastMCP, name: str):
    """Return the raw callable for a registered tool by name."""
    return mcp._tool_manager._tools[name].fn


def _make_arxiv_result(
    short_id="1706.03762",
    title="Attention Is All You Need",
    summary="We propose a new simple network architecture...",
    published="2017-06-12",
    authors=("Vaswani",),
    pdf_url="https://arxiv.org/pdf/1706.03762",
    categories=("cs.CL",),
) -> MagicMock:
    """Build a minimal mock arxiv.Result."""
    result = MagicMock()
    result.get_short_id.return_value = short_id
    result.title = title
    result.summary = summary
    result.published.date.return_value = published
    result.authors = [MagicMock(name=a) for a in authors]
    result.pdf_url = pdf_url
    result.categories = list(categories)
    return result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_all_tools_registered(self):
        mcp = _make_mcp()
        registered = set(mcp._tool_manager._tools.keys())
        assert "search_papers" in registered
        assert "download_paper" in registered


# ---------------------------------------------------------------------------
# search_papers
# ---------------------------------------------------------------------------


class TestSearchPapers:
    def setup_method(self):
        self.mcp = _make_mcp()
        self.search_papers = _get_tool(self.mcp, "search_papers")

    def test_validation_error_missing_params(self):
        result = self.search_papers(query="", id_list=None)
        assert result["success"] is False
        assert "query" in result["error"] or "id_list" in result["error"]

    @patch("aden_tools.tools.arxiv_tool.arxiv_tool._SHARED_ARXIV_CLIENT")
    def test_search_success(self, mock_client):
        mock_client.results.return_value = iter([_make_arxiv_result()])

        result = self.search_papers(query="attention transformer")

        assert result["success"] is True
        assert result["total"] == 1
        paper = result["results"][0]
        assert paper["id"] == "1706.03762"
        assert paper["title"] == "Attention Is All You Need"
        assert paper["pdf_url"] == "https://arxiv.org/pdf/1706.03762"
        assert "cs.CL" in paper["categories"]

    @patch("aden_tools.tools.arxiv_tool.arxiv_tool._SHARED_ARXIV_CLIENT")
    def test_search_success_with_results(self, mock_client):
        mock_client.results.return_value = iter(
            [_make_arxiv_result(short_id=f"000{i}.0000{i}") for i in range(3)]
        )
        result = self.search_papers(query="multi-agent systems", max_results=3)
        assert result["success"] is True
        assert result["total"] == 3

    @patch("aden_tools.tools.arxiv_tool.arxiv_tool._SHARED_ARXIV_CLIENT")
    def test_search_by_id_list(self, mock_client):
        mock_client.results.return_value = iter([_make_arxiv_result()])

        result = self.search_papers(id_list=["1706.03762"])

        assert result["success"] is True
        assert result["id_list"] == ["1706.03762"]
        assert result["query"] == ""

    def test_max_results_clamped(self):
        """max_results above 100 should be silently capped — confirm no crash."""
        with patch("aden_tools.tools.arxiv_tool.arxiv_tool._SHARED_ARXIV_CLIENT") as mock_client:
            mock_client.results.return_value = iter([])
            result = self.search_papers(query="test", max_results=9999)
        assert result["success"] is True

    @patch("aden_tools.tools.arxiv_tool.arxiv_tool._SHARED_ARXIV_CLIENT")
    def test_arxiv_error_handling(self, mock_client):
        mock_client.results.side_effect = arxiv.ArxivError(
            message="arXiv is down", url="", retry=False
        )
        result = self.search_papers(query="test")
        assert result["success"] is False
        assert "arXiv" in result["error"]

    @patch("aden_tools.tools.arxiv_tool.arxiv_tool._SHARED_ARXIV_CLIENT")
    def test_network_error_handling(self, mock_client):
        mock_client.results.side_effect = ConnectionError("unreachable")
        result = self.search_papers(query="test")
        assert result["success"] is False
        assert "unreachable" in result["error"].lower() or "network" in result["error"].lower()


# ---------------------------------------------------------------------------
# download_paper
# ---------------------------------------------------------------------------


class TestDownloadPaper:
    def setup_method(self):
        self.mcp = _make_mcp()
        self.download_paper = _get_tool(self.mcp, "download_paper")

    @patch("aden_tools.tools.arxiv_tool.arxiv_tool.requests.get")
    @patch("aden_tools.tools.arxiv_tool.arxiv_tool._SHARED_ARXIV_CLIENT")
    def test_download_success(self, mock_client, mock_get, tmp_path):
        mock_client.results.return_value = iter([_make_arxiv_result()])

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.iter_content.return_value = [b"%PDF-1.4 fake content"]
        mock_get.return_value = mock_response

        with patch("aden_tools.tools.arxiv_tool.arxiv_tool._TEMP_DIR") as mock_tmp:
            mock_tmp.name = str(tmp_path)
            result = self.download_paper(paper_id="1706.03762")

        assert result["success"] is True
        assert result["paper_id"] == "1706.03762"
        assert result["file_path"].endswith(".pdf")

    @patch("aden_tools.tools.arxiv_tool.arxiv_tool._SHARED_ARXIV_CLIENT")
    def test_no_paper_found(self, mock_client):
        mock_client.results.return_value = iter([])
        result = self.download_paper(paper_id="0000.00000")
        assert result["success"] is False
        assert "No paper found" in result["error"]

    @patch("aden_tools.tools.arxiv_tool.arxiv_tool._SHARED_ARXIV_CLIENT")
    def test_no_pdf_url(self, mock_client):
        paper = _make_arxiv_result(pdf_url=None)
        mock_client.results.return_value = iter([paper])
        result = self.download_paper(paper_id="1706.03762")
        assert result["success"] is False
        assert "PDF URL not available" in result["error"]

    @patch("aden_tools.tools.arxiv_tool.arxiv_tool.requests.get")
    @patch("aden_tools.tools.arxiv_tool.arxiv_tool._SHARED_ARXIV_CLIENT")
    def test_download_network_error(self, mock_client, mock_get):
        import requests

        mock_client.results.return_value = iter([_make_arxiv_result()])
        mock_get.side_effect = requests.RequestException("connection refused")

        result = self.download_paper(paper_id="1706.03762")

        assert result["success"] is False
        assert "Failed during download" in result["error"]

    @patch("aden_tools.tools.arxiv_tool.arxiv_tool.requests.get")
    @patch("aden_tools.tools.arxiv_tool.arxiv_tool._SHARED_ARXIV_CLIENT")
    def test_download_invalid_content_type(self, mock_client, mock_get):
        mock_client.results.return_value = iter([_make_arxiv_result()])

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {"Content-Type": "text/html"}
        mock_get.return_value = mock_response

        result = self.download_paper(paper_id="1706.03762")

        assert result["success"] is False
        assert "Failed during download" in result["error"]

    @patch("aden_tools.tools.arxiv_tool.arxiv_tool.requests.get")
    @patch("aden_tools.tools.arxiv_tool.arxiv_tool._SHARED_ARXIV_CLIENT")
    def test_file_cleanup_on_error(self, mock_client, mock_get, tmp_path):
        """Partial file must be deleted when the download fails mid-write."""
        import requests

        mock_client.results.return_value = iter([_make_arxiv_result()])

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.iter_content.side_effect = requests.RequestException("dropped")
        mock_get.return_value = mock_response

        with patch("aden_tools.tools.arxiv_tool.arxiv_tool._TEMP_DIR") as mock_tmp:
            mock_tmp.name = str(tmp_path)
            result = self.download_paper(paper_id="1706.03762")

        assert result["success"] is False
        # No leftover partial files
        assert list(tmp_path.iterdir()) == []
