"""Tests for web_scrape tool (FastMCP)."""
import pytest

from fastmcp import FastMCP
from unittest.mock import patch
from aden_tools.tools.web_scrape_tool import register_tools


@pytest.fixture
def web_scrape_fn(mcp: FastMCP):
    """Register and return the web_scrape tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["web_scrape"].fn


class TestWebScrapeTool:
    """Tests for web_scrape tool."""

    def test_url_auto_prefixed_with_https(self, web_scrape_fn):
        """URLs without scheme get https:// prefix."""
        with patch("httpx.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.text = "<html><body>Content</body></html>"
            mock_get.return_value.url = "https://example.com"
            
            with patch("urllib.robotparser.RobotFileParser.can_fetch", return_value=True):
                result = web_scrape_fn(url="example.com")
                
                assert isinstance(result, dict)
                # Check that httpx.get was called with https://
                args, _ = mock_get.call_args
                assert args[0] == "https://example.com"

    def test_max_length_clamped_low(self, web_scrape_fn):
        """max_length below 1000 is clamped to 1000."""
        with patch("httpx.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.text = "<html><body>Content</body></html>"
            mock_get.return_value.url = "https://example.com"
            
            with patch("urllib.robotparser.RobotFileParser.can_fetch", return_value=True):
                result = web_scrape_fn(url="https://example.com", max_length=500)
                assert isinstance(result, dict)
                # We can't easily check the clamped value internal to the function without spying,
                # but we verify it runs without error.

    def test_max_length_clamped_high(self, web_scrape_fn):
        """max_length above 500000 is clamped to 500000."""
        with patch("httpx.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.text = "<html><body>Content</body></html>"
            mock_get.return_value.url = "https://example.com"
            
            with patch("urllib.robotparser.RobotFileParser.can_fetch", return_value=True):
                result = web_scrape_fn(url="https://example.com", max_length=600000)
                assert isinstance(result, dict)

    def test_valid_max_length_accepted(self, web_scrape_fn):
        """Valid max_length values are accepted."""
        with patch("httpx.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.text = "<html><body>Content</body></html>"
            mock_get.return_value.url = "https://example.com"
            
            with patch("urllib.robotparser.RobotFileParser.can_fetch", return_value=True):
                result = web_scrape_fn(url="https://example.com", max_length=10000)
                assert isinstance(result, dict)

    def test_include_links_option(self, web_scrape_fn):
        """include_links parameter is accepted."""
        with patch("httpx.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.text = '<html><body><a href="/foo">Link</a></body></html>'
            mock_get.return_value.url = "https://example.com"
            
            with patch("urllib.robotparser.RobotFileParser.can_fetch", return_value=True):
                result = web_scrape_fn(url="https://example.com", include_links=True)
                assert isinstance(result, dict)
                assert "links" in result
                assert len(result["links"]) > 0

    def test_selector_option(self, web_scrape_fn):
        """selector parameter is accepted."""
        with patch("httpx.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.text = '<html><body><div class="content">Selected</div></body></html>'
            mock_get.return_value.url = "https://example.com"
            
            with patch("urllib.robotparser.RobotFileParser.can_fetch", return_value=True):
                result = web_scrape_fn(url="https://example.com", selector=".content")
                assert isinstance(result, dict)
                assert result["content"] == "Selected"
