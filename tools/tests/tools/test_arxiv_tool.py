"""Tests for arXiv tool."""

import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.arxiv_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance with tools registered."""
    server = FastMCP("test")
    register_tools(server)
    return server


class TestSearchPapers:
    """Tests for search_papers tool."""

    def test_search_basic(self, mcp):
        """Test basic search functionality."""
        mock_result = Mock()
        mock_result.entry_id = "http://arxiv.org/abs/1706.03762v5"
        mock_result.title = "Attention Is All You Need"
        mock_result.authors = [Mock(name="Ashish Vaswani")]
        mock_result.summary = "We propose a new architecture..."
        mock_result.published = datetime(2017, 6, 12)
        mock_result.updated = datetime(2017, 12, 6)
        mock_result.pdf_url = "http://arxiv.org/pdf/1706.03762v5"
        mock_result.categories = ["cs.CL", "cs.LG"]

        with patch("arxiv.Search") as mock_search:
            mock_search.return_value.results.return_value = iter([mock_result])

            tool_fn = mcp._tool_manager._tools["search_papers"].fn
            result = tool_fn(query="transformer", max_results=1)

        assert "papers" in result
        assert len(result["papers"]) == 1
        assert result["papers"][0]["paper_id"] == "1706.03762v5"
        assert result["papers"][0]["title"] == "Attention Is All You Need"
        assert result["num_results"] == 1

    def test_search_empty_query(self, mcp):
        """Test validation of empty query."""
        tool_fn = mcp._tool_manager._tools["search_papers"].fn
        result = tool_fn(query="")
        assert "error" in result
        assert "1-500 characters" in result["error"]

    def test_search_query_too_long(self, mcp):
        """Test validation of query length."""
        tool_fn = mcp._tool_manager._tools["search_papers"].fn
        result = tool_fn(query="x" * 501)
        assert "error" in result

    def test_search_max_results_clamping(self, mcp):
        """Test max_results is clamped to valid range."""
        with patch("arxiv.Search") as mock_search:
            mock_search.return_value.results.return_value = iter([])

            tool_fn = mcp._tool_manager._tools["search_papers"].fn

            # Below minimum
            result = tool_fn(query="test", max_results=0)
            mock_search.assert_called()
            assert mock_search.call_args[1]["max_results"] == 1

            # Above maximum
            result = tool_fn(query="test", max_results=200)
            assert mock_search.call_args[1]["max_results"] == 100

    def test_search_sort_options(self, mcp):
        """Test different sort options."""
        import arxiv

        with patch("arxiv.Search") as mock_search:
            mock_search.return_value.results.return_value = iter([])

            tool_fn = mcp._tool_manager._tools["search_papers"].fn

            # Test relevance
            tool_fn(query="test", sort_by="relevance")
            assert mock_search.call_args[1]["sort_by"] == arxiv.SortCriterion.Relevance

            # Test recent
            tool_fn(query="test", sort_by="recent")
            assert mock_search.call_args[1]["sort_by"] == arxiv.SortCriterion.LastUpdatedDate

            # Test submitted
            tool_fn(query="test", sort_by="submitted")
            assert mock_search.call_args[1]["sort_by"] == arxiv.SortCriterion.SubmittedDate

    def test_search_error_handling(self, mcp):
        """Test error handling for search failures."""
        with patch("arxiv.Search") as mock_search:
            mock_search.return_value.results.side_effect = Exception("Network error")

            tool_fn = mcp._tool_manager._tools["search_papers"].fn
            result = tool_fn(query="test")

        assert "error" in result
        assert "failed" in result["error"].lower()


class TestDownloadPaper:
    """Tests for download_paper tool."""

    def test_download_success(self, mcp, tmp_path):
        """Test successful paper download."""
        # Setup file to be "downloaded"
        pdf_path = tmp_path / "arxiv_papers" / "1706.03762.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        
        mock_paper = Mock()
        mock_paper.title = "Test Paper"
        
        def mock_download(filename):
            # Simulate download by writing file
            Path(filename).write_bytes(b"fake pdf content")
        
        mock_paper.download_pdf = Mock(side_effect=mock_download)

        with patch("aden_tools.tools.arxiv_tool.arxiv_tool.tempfile.gettempdir", return_value=str(tmp_path)):
            with patch("arxiv.Search") as mock_search:
                mock_search.return_value.results.return_value = iter([mock_paper])

                tool_fn = mcp._tool_manager._tools["download_paper"].fn
                result = tool_fn(paper_id="1706.03762")

        assert "file_path" in result
        assert result["paper_id"] == "1706.03762"
        assert result["file_size_bytes"] > 0
        assert result["title"] == "Test Paper"

    def test_download_with_arxiv_prefix(self, mcp, tmp_path):
        """Test download handles 'arXiv:' prefix."""
        mock_paper = Mock()
        mock_paper.title = "Test"
        
        def mock_download(filename):
            Path(filename).write_bytes(b"fake")
        
        mock_paper.download_pdf = Mock(side_effect=mock_download)

        with patch("aden_tools.tools.arxiv_tool.arxiv_tool.tempfile.gettempdir", return_value=str(tmp_path)):
            with patch("arxiv.Search") as mock_search:
                mock_search.return_value.results.return_value = iter([mock_paper])

                tool_fn = mcp._tool_manager._tools["download_paper"].fn
                result = tool_fn(paper_id="arXiv:1706.03762")

        # Should clean the ID
        assert result["paper_id"] == "1706.03762"

    def test_download_paper_not_found(self, mcp):
        """Test download of non-existent paper."""
        with patch("arxiv.Search") as mock_search:
            mock_search.return_value.results.return_value = iter([])

            tool_fn = mcp._tool_manager._tools["download_paper"].fn
            result = tool_fn(paper_id="9999.99999")

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_download_empty_paper_id(self, mcp):
        """Test validation of empty paper_id."""
        tool_fn = mcp._tool_manager._tools["download_paper"].fn
        result = tool_fn(paper_id="")
        assert "error" in result
        assert "required" in result["error"].lower()

    def test_download_error_handling(self, mcp):
        """Test error handling for download failures."""
        with patch("arxiv.Search") as mock_search:
            mock_search.side_effect = Exception("Network error")

            tool_fn = mcp._tool_manager._tools["download_paper"].fn
            result = tool_fn(paper_id="1706.03762")

        assert "error" in result
        assert "failed" in result["error"].lower()


class TestRateLimiter:
    """Tests for rate limiter."""

    def test_rate_limiter_enforces_delay(self):
        """Test that rate limiter enforces 3-second delays."""
        from aden_tools.tools.arxiv_tool.arxiv_tool import _ArxivRateLimiter

        # Reset state
        _ArxivRateLimiter._last_request_time = 0

        start = time.time()
        _ArxivRateLimiter.wait()  # First call should not block
        first_elapsed = time.time() - start
        assert first_elapsed < 0.1  # Should be nearly instant

        _ArxivRateLimiter.wait()  # Second call should block
        second_elapsed = time.time() - start
        assert second_elapsed >= 3.0  # Should wait ~3 seconds


class TestFullWorkflow:
    """Integration tests for full workflow."""

    def test_search_then_download(self, mcp, tmp_path):
        """Test complete search → download workflow."""
        # Mock search result
        mock_result = Mock()
        mock_result.entry_id = "http://arxiv.org/abs/1706.03762v5"
        mock_result.title = "Test Paper"
        mock_result.authors = [Mock(name="Author")]
        mock_result.summary = "Abstract"
        mock_result.published = datetime.now()
        mock_result.updated = None
        mock_result.pdf_url = "http://url"
        mock_result.categories = ["cs.CL"]

        # Mock download
        mock_paper = Mock()
        mock_paper.title = "Test Paper"
        
        def mock_download(filename):
            Path(filename).write_bytes(b"fake pdf")
        
        mock_paper.download_pdf = Mock(side_effect=mock_download)

        with patch("aden_tools.tools.arxiv_tool.arxiv_tool.tempfile.gettempdir", return_value=str(tmp_path)):
            with patch("arxiv.Search") as mock_search:
                # Setup search
                mock_search.return_value.results.return_value = iter([mock_result])

                # 1. Search
                search_fn = mcp._tool_manager._tools["search_papers"].fn
                search_result = search_fn(query="transformer")
                assert len(search_result["papers"]) == 1
                paper_id = search_result["papers"][0]["paper_id"]

                # Setup download
                mock_search.return_value.results.return_value = iter([mock_paper])

                # 2. Download
                download_fn = mcp._tool_manager._tools["download_paper"].fn
                download_result = download_fn(paper_id=paper_id)

        assert "file_path" in download_result
        assert download_result["paper_id"] == paper_id
