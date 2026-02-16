"""Tests for the ArXiv tool."""

import os
from unittest.mock import MagicMock, patch

import pytest
from aden_tools.tools.arxiv_tool.arxiv_tool import register_tools


class TestArXivTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        # Mocking the decorator behavior
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        self.cred = MagicMock()
        register_tools(self.mcp, credentials=self.cred)

    def _fn(self, name):
        """Retrieve a registered function by its name."""
        return next(f for f in self.fns if f.__name__ == name)

    @patch("arxiv.Client")
    @patch("arxiv.Search")
    def test_arxiv_search_papers(self, mock_search, mock_client):
        # Mock paper objects
        mock_paper = MagicMock()
        mock_paper.title = "Attention is All You Need"
        mock_paper.summary = "Deep learning paper"
        mock_author = MagicMock()
        mock_author.name = "Ashish Vaswani"
        mock_paper.authors = [mock_author]
        mock_paper.published.isoformat.return_value = "2017-06-12T00:00:00Z"
        mock_paper.get_short_id.return_value = "1706.03762v1"
        mock_paper.pdf_url = "http://arxiv.org/pdf/1706.03762v1"
        mock_paper.entry_id = "http://arxiv.org/abs/1706.03762v1"

        # Mock client.results
        mock_client_instance = mock_client.return_value
        mock_client_instance.results.return_value = [mock_paper]

        tool = self._fn("arxiv_search_papers")
        result = tool(query="Attention")

        assert "papers" in result
        assert result["count"] == 1
        assert result["papers"][0]["title"] == "Attention is All You Need"
        assert result["papers"][0]["paper_id"] == "1706.03762v1"

    @patch("arxiv.Client")
    @patch("arxiv.Search")
    def test_arxiv_download_paper(self, mock_search, mock_client):
        mock_paper = MagicMock()
        mock_paper.title = "Attention"
        mock_paper.download_pdf.return_value = "/tmp/attention.pdf"

        mock_client_instance = mock_client.return_value
        mock_client_instance.results.return_value = iter([mock_paper])

        tool = self._fn("arxiv_download_paper")
        result = tool(paper_id="1706.03762")

        assert result["file_path"] == "/tmp/attention.pdf"
        assert result["paper_id"] == "1706.03762"
        mock_paper.download_pdf.assert_called_once()

    @patch("arxiv.Client")
    @patch("arxiv.Search")
    def test_arxiv_download_paper_not_found(self, mock_search, mock_client):
        mock_client_instance = mock_client.return_value
        mock_client_instance.results.return_value = iter([])

        tool = self._fn("arxiv_download_paper")
        result = tool(paper_id="nonexistent")

        assert "error" in result
        assert "not found" in result["error"]
