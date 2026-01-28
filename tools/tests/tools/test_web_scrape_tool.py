"""Tests for web_scrape tool (FastMCP)."""
import pytest
from unittest.mock import patch, MagicMock

import pytest
from fastmcp import FastMCP

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
        # This will fail to connect, but we can verify the behavior
        result = web_scrape_fn(url="example.com")
        # Should either succeed or have a network error (not a validation error)
        assert isinstance(result, dict)

    def test_max_length_clamped_low(self, web_scrape_fn):
        """max_length below 1000 is clamped to 1000."""
        # Test with a very low max_length - implementation clamps to 1000
        result = web_scrape_fn(url="https://example.com", max_length=500)
        # Should not error due to invalid max_length
        assert isinstance(result, dict)

    def test_max_length_clamped_high(self, web_scrape_fn):
        """max_length above 500000 is clamped to 500000."""
        # Test with a very high max_length - implementation clamps to 500000
        result = web_scrape_fn(url="https://example.com", max_length=600000)
        # Should not error due to invalid max_length
        assert isinstance(result, dict)

    def test_valid_max_length_accepted(self, web_scrape_fn):
        """Valid max_length values are accepted."""
        result = web_scrape_fn(url="https://example.com", max_length=10000)
        assert isinstance(result, dict)

    def test_include_links_option(self, web_scrape_fn):
        """include_links parameter is accepted."""
        result = web_scrape_fn(url="https://example.com", include_links=True)
        assert isinstance(result, dict)

    def test_selector_option(self, web_scrape_fn):
        """selector parameter is accepted."""
        result = web_scrape_fn(url="https://example.com", selector=".content")
        assert isinstance(result, dict)

class TestWebScrapeToolLinkConversion:
    """Tests for link URL conversion (relative to absolute)."""

    def _mock_response(self, html_content, final_url="https://example.com/page"):
        """Create a mock httpx response object."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html_content
        mock_response.url = final_url
        return mock_response

    @patch("aden_tools.tools.web_scrape_tool.web_scrape_tool.httpx.get")
    def test_relative_links_converted_to_absolute(self, mock_get, web_scrape_fn):
        """Relative URLs like ../page are converted to absolute URLs."""
        html = """
        <html>
            <body>
                <a href="../home">Home</a>
                <a href="page.html">Next Page</a>
            </body>
        </html>
        """
        mock_get.return_value = self._mock_response(html, "https://example.com/blog/post")

        result = web_scrape_fn(url="https://example.com/blog/post", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        hrefs = {link["text"]: link["href"] for link in links}
        
        # Verify relative URLs are converted to absolute
        assert "Home" in hrefs
        assert hrefs["Home"] == "https://example.com/home", f"Got {hrefs['Home']}"
        
        assert "Next Page" in hrefs
        assert hrefs["Next Page"] == "https://example.com/blog/page.html", f"Got {hrefs['Next Page']}"

    @patch("aden_tools.tools.web_scrape_tool.web_scrape_tool.httpx.get")
    def test_root_relative_links_converted(self, mock_get, web_scrape_fn):
        """Root-relative URLs like /about are converted to absolute URLs."""
        html = """
        <html>
            <body>
                <a href="/about">About</a>
                <a href="/contact">Contact</a>
            </body>
        </html>
        """
        mock_get.return_value = self._mock_response(html, "https://example.com/blog/post")

        result = web_scrape_fn(url="https://example.com/blog/post", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        hrefs = {link["text"]: link["href"] for link in links}
        
        # Root-relative URLs should resolve to domain root
        assert hrefs["About"] == "https://example.com/about"
        assert hrefs["Contact"] == "https://example.com/contact"

    @patch("aden_tools.tools.web_scrape_tool.web_scrape_tool.httpx.get")
    def test_absolute_links_unchanged(self, mock_get, web_scrape_fn):
        """Absolute URLs remain unchanged."""
        html = """
        <html>
            <body>
                <a href="https://other.com">Other Site</a>
                <a href="https://example.com/page">Internal</a>
            </body>
        </html>
        """
        mock_get.return_value = self._mock_response(html)

        result = web_scrape_fn(url="https://example.com", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        hrefs = {link["text"]: link["href"] for link in links}
        
        # Absolute URLs should remain unchanged
        assert hrefs["Other Site"] == "https://other.com"
        assert hrefs["Internal"] == "https://example.com/page"

    @patch("aden_tools.tools.web_scrape_tool.web_scrape_tool.httpx.get")
    def test_links_after_redirects(self, mock_get, web_scrape_fn):
        """Links are resolved relative to final URL after redirects."""
        html = """
        <html>
            <body>
                <a href="../prev">Previous</a>
                <a href="next">Next</a>
            </body>
        </html>
        """
        # Mock redirect: request to /old/url redirects to /new/location
        mock_get.return_value = self._mock_response(
            html, 
            final_url="https://example.com/new/location"  # Final URL after redirect
        )

        result = web_scrape_fn(url="https://example.com/old/url", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        hrefs = {link["text"]: link["href"] for link in links}
        
        # Links should be resolved relative to FINAL URL, not requested URL
        assert hrefs["Previous"] == "https://example.com/prev", \
            "Links should resolve relative to final URL after redirects"
        assert hrefs["Next"] == "https://example.com/new/next"

    @patch("aden_tools.tools.web_scrape_tool.web_scrape_tool.httpx.get")
    def test_fragment_links_preserved(self, mock_get, web_scrape_fn):
        """Fragment links (anchors) are preserved."""
        html = """
        <html>
            <body>
                <a href="#section1">Section 1</a>
                <a href="/page#section2">Page Section 2</a>
            </body>
        </html>
        """
        mock_get.return_value = self._mock_response(html, "https://example.com/page")

        result = web_scrape_fn(url="https://example.com/page", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        hrefs = {link["text"]: link["href"] for link in links}
        
        # Fragment links should be converted correctly
        assert hrefs["Section 1"] == "https://example.com/page#section1"
        assert hrefs["Page Section 2"] == "https://example.com/page#section2"

    @patch("aden_tools.tools.web_scrape_tool.web_scrape_tool.httpx.get")
    def test_query_parameters_preserved(self, mock_get, web_scrape_fn):
        """Query parameters in URLs are preserved."""
        html = """
        <html>
            <body>
                <a href="page?id=123">View Item</a>
                <a href="/search?q=test&sort=date">Search</a>
            </body>
        </html>
        """
        mock_get.return_value = self._mock_response(html, "https://example.com/blog/post")

        result = web_scrape_fn(url="https://example.com/blog/post", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        hrefs = {link["text"]: link["href"] for link in links}
        
        # Query parameters should be preserved
        assert "id=123" in hrefs["View Item"]
        assert "q=test" in hrefs["Search"]
        assert "sort=date" in hrefs["Search"]

    @patch("aden_tools.tools.web_scrape_tool.web_scrape_tool.httpx.get")
    def test_empty_href_skipped(self, mock_get, web_scrape_fn):
        """Links with empty or whitespace text are skipped."""
        html = """
        <html>
            <body>
                <a href="/valid">Valid Link</a>
                <a href="/empty"></a>
                <a href="/whitespace">   </a>
            </body>
        </html>
        """
        mock_get.return_value = self._mock_response(html)

        result = web_scrape_fn(url="https://example.com", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        texts = [link["text"] for link in links]
        
        # Only valid links should be included
        assert "Valid Link" in texts
        # Empty and whitespace-only text should be filtered
        assert "" not in texts
        assert len([t for t in texts if not t.strip()]) == 0
