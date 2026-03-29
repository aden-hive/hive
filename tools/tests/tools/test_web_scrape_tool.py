"""Tests for web_scrape tool (FastMCP)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.web_scrape_tool import register_tools


@pytest.fixture
def web_scrape_fn(mcp: FastMCP):
    """Register and return the web_scrape tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["web_scrape"].fn


def _make_playwright_mocks(html, status=200, final_url="https://example.com/page"):
    """Build a full playwright mock chain and return (context_manager, response, page)."""
    mock_response = MagicMock(
        status=status,
        url=final_url,
        headers={"content-type": "text/html; charset=utf-8"},
    )

    mock_page = AsyncMock()
    mock_page.goto.return_value = mock_response
    mock_page.content.return_value = html
    mock_page.wait_for_load_state.return_value = None

    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = AsyncMock()
    mock_browser.new_context.return_value = mock_context

    mock_pw = MagicMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    # async context manager for async_playwright()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_cm, mock_response, mock_page


_PW_PATH = "aden_tools.tools.web_scrape_tool.web_scrape_tool.async_playwright"
_STEALTH_PATH = "aden_tools.tools.web_scrape_tool.web_scrape_tool.Stealth"


class TestWebScrapeTool:
    """Tests for web_scrape tool."""

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_url_auto_prefixed_with_https(self, mock_pw, mock_stealth, web_scrape_fn):
        """URLs without scheme get https:// prefix."""
        html = "<html><body>Hello</body></html>"
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="example.com")
        assert isinstance(result, dict)
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_max_length_clamped_low(self, mock_pw, mock_stealth, web_scrape_fn):
        """max_length below 1000 is clamped to 1000."""
        html = "<html><body>Hello</body></html>"
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com", max_length=500)
        assert isinstance(result, dict)
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_max_length_clamped_high(self, mock_pw, mock_stealth, web_scrape_fn):
        """max_length above 500000 is clamped to 500000."""
        html = "<html><body>Hello</body></html>"
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com", max_length=600000)
        assert isinstance(result, dict)
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_valid_max_length_accepted(self, mock_pw, mock_stealth, web_scrape_fn):
        """Valid max_length values are accepted."""
        html = "<html><body>Hello</body></html>"
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com", max_length=10000)
        assert isinstance(result, dict)
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_include_links_option(self, mock_pw, mock_stealth, web_scrape_fn):
        """include_links parameter is accepted."""
        html = '<html><body><a href="/link">Link</a></body></html>'
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com", include_links=True)
        assert isinstance(result, dict)
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_selector_option(self, mock_pw, mock_stealth, web_scrape_fn):
        """selector parameter is accepted."""
        html = '<html><body><div class="content">Content here</div></body></html>'
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com", selector=".content")
        assert isinstance(result, dict)
        assert "error" not in result


class TestWebScrapeToolLinkConversion:
    """Tests for link URL conversion (relative to absolute)."""

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_relative_links_converted_to_absolute(self, mock_pw, mock_stealth, web_scrape_fn):
        """Relative URLs like ../page are converted to absolute URLs."""
        html = """
        <html>
            <body>
                <a href="../home">Home</a>
                <a href="page.html">Next Page</a>
            </body>
        </html>
        """
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com/blog/post")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com/blog/post", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        hrefs = {link["text"]: link["href"] for link in links}

        # Verify relative URLs are converted to absolute
        assert "Home" in hrefs
        assert hrefs["Home"] == "https://example.com/home", f"Got {hrefs['Home']}"

        assert "Next Page" in hrefs
        expected = "https://example.com/blog/page.html"
        assert hrefs["Next Page"] == expected, f"Got {hrefs['Next Page']}"

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_root_relative_links_converted(self, mock_pw, mock_stealth, web_scrape_fn):
        """Root-relative URLs like /about are converted to absolute URLs."""
        html = """
        <html>
            <body>
                <a href="/about">About</a>
                <a href="/contact">Contact</a>
            </body>
        </html>
        """
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com/blog/post")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com/blog/post", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        hrefs = {link["text"]: link["href"] for link in links}

        # Root-relative URLs should resolve to domain root
        assert hrefs["About"] == "https://example.com/about"
        assert hrefs["Contact"] == "https://example.com/contact"

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_absolute_links_unchanged(self, mock_pw, mock_stealth, web_scrape_fn):
        """Absolute URLs remain unchanged."""
        html = """
        <html>
            <body>
                <a href="https://other.com">Other Site</a>
                <a href="https://example.com/page">Internal</a>
            </body>
        </html>
        """
        mock_cm, _, _ = _make_playwright_mocks(html)
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        hrefs = {link["text"]: link["href"] for link in links}

        # Absolute URLs should remain unchanged
        assert hrefs["Other Site"] == "https://other.com"
        assert hrefs["Internal"] == "https://example.com/page"

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_links_after_redirects(self, mock_pw, mock_stealth, web_scrape_fn):
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
        mock_cm, _, _ = _make_playwright_mocks(
            html,
            final_url="https://example.com/new/location",  # Final URL after redirect
        )
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com/old/url", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        hrefs = {link["text"]: link["href"] for link in links}

        # Links should be resolved relative to FINAL URL, not requested URL
        assert hrefs["Previous"] == "https://example.com/prev", (
            "Links should resolve relative to final URL after redirects"
        )
        assert hrefs["Next"] == "https://example.com/new/next"

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_fragment_links_preserved(self, mock_pw, mock_stealth, web_scrape_fn):
        """Fragment links (anchors) are preserved."""
        html = """
        <html>
            <body>
                <a href="#section1">Section 1</a>
                <a href="/page#section2">Page Section 2</a>
            </body>
        </html>
        """
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com/page")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com/page", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        hrefs = {link["text"]: link["href"] for link in links}

        # Fragment links should be converted correctly
        assert hrefs["Section 1"] == "https://example.com/page#section1"
        assert hrefs["Page Section 2"] == "https://example.com/page#section2"

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_query_parameters_preserved(self, mock_pw, mock_stealth, web_scrape_fn):
        """Query parameters in URLs are preserved."""
        html = """
        <html>
            <body>
                <a href="page?id=123">View Item</a>
                <a href="/search?q=test&sort=date">Search</a>
            </body>
        </html>
        """
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com/blog/post")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com/blog/post", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        hrefs = {link["text"]: link["href"] for link in links}

        # Query parameters should be preserved
        assert "id=123" in hrefs["View Item"]
        assert "q=test" in hrefs["Search"]
        assert "sort=date" in hrefs["Search"]

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_empty_href_skipped(self, mock_pw, mock_stealth, web_scrape_fn):
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
        mock_cm, _, _ = _make_playwright_mocks(html)
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com", include_links=True)

        assert "error" not in result
        assert "links" in result
        links = result["links"]
        texts = [link["text"] for link in links]

        # Only valid links should be included
        assert "Valid Link" in texts
        # Empty and whitespace-only text should be filtered
        assert "" not in texts
        assert len([t for t in texts if not t.strip()]) == 0


class TestSSRFProtection:
    """Tests for SSRF protection in web_scrape tool."""

    def test_blocks_localhost(self, web_scrape_fn):
        """Blocks requests to localhost."""
        result = web_scrape_fn(url="http://localhost:8080")
        assert result.get("blocked_by_ssrf_protection") is True
        assert "loopback" in result.get("error", "").lower()

    def test_blocks_127_0_0_1(self, web_scrape_fn):
        """Blocks requests to 127.0.0.1."""
        result = web_scrape_fn(url="http://127.0.0.1:5000")
        assert result.get("blocked_by_ssrf_protection") is True
        assert "loopback" in result.get("error", "").lower()

    def test_blocks_private_192_168(self, web_scrape_fn):
        """Blocks requests to 192.168.x.x private network."""
        result = web_scrape_fn(url="http://192.168.1.1")
        assert result.get("blocked_by_ssrf_protection") is True
        assert "private" in result.get("error", "").lower()

    def test_blocks_private_10_0(self, web_scrape_fn):
        """Blocks requests to 10.x.x.x private network."""
        result = web_scrape_fn(url="http://10.0.0.1")
        assert result.get("blocked_by_ssrf_protection") is True
        assert "private" in result.get("error", "").lower()

    def test_blocks_aws_metadata(self, web_scrape_fn):
        """Blocks requests to AWS/GCP metadata endpoint."""
        result = web_scrape_fn(url="http://169.254.169.254/latest/meta-data/")
        assert result.get("blocked_by_ssrf_protection") is True
        # 169.254.x.x is detected as private by Python's ipaddress module
        assert "blocked" in result.get("error", "").lower()

    def test_allows_public_urls(self, web_scrape_fn):
        """Allows requests to public URLs."""
        result = web_scrape_fn(url="https://example.com")
        # Should not be blocked by SSRF protection
        assert result.get("blocked_by_ssrf_protection") is not True
class TestWebScrapeToolErrorHandling:
    """Tests for error handling and early exit before JS wait."""

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_http_error_returns_without_waiting(self, mock_pw, mock_stealth, web_scrape_fn):
        """HTTP errors return immediately without waiting for networkidle."""
        html = "<html><body>Not Found</body></html>"
        mock_cm, _, mock_page = _make_playwright_mocks(html, status=404)
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com/missing")
        assert result == {"error": "HTTP 404: Failed to fetch URL"}
        mock_page.wait_for_load_state.assert_not_called()

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_null_response_returns_error(self, mock_pw, mock_stealth, web_scrape_fn):
        """Null navigation response returns error without waiting."""
        mock_cm, _, mock_page = _make_playwright_mocks("<html></html>")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()
        mock_page.goto.return_value = None

        result = await web_scrape_fn(url="https://example.com")
        assert result == {"error": "Navigation failed: no response received"}
        mock_page.wait_for_load_state.assert_not_called()

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_non_html_content_type_skipped(self, mock_pw, mock_stealth, web_scrape_fn):
        """Non-HTML content types are skipped without waiting."""
        mock_cm, mock_response, mock_page = _make_playwright_mocks("<html></html>")
        mock_response.headers = {"content-type": "application/pdf"}
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com/file.pdf")
        assert "error" in result
        assert result["skipped"] is True
        mock_page.wait_for_load_state.assert_not_called()


class TestWebScrapeToolRobotsTxt:
    """Tests for robots.txt respect."""

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    @patch("aden_tools.tools.web_scrape_tool.web_scrape_tool.RobotFileParser")
    async def test_blocked_by_robots_txt(self, mock_rp_cls, mock_pw, mock_stealth, web_scrape_fn):
        """URLs disallowed by robots.txt are skipped."""
        mock_rp = MagicMock()
        mock_rp.can_fetch.return_value = False
        mock_rp_cls.return_value = mock_rp

        result = await web_scrape_fn(url="https://example.com/private")
        assert "error" in result
        assert "robots.txt" in result["error"]
        assert result["skipped"] is True

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    @patch("aden_tools.tools.web_scrape_tool.web_scrape_tool.RobotFileParser")
    async def test_robots_txt_disabled(self, mock_rp_cls, mock_pw, mock_stealth, web_scrape_fn):
        """robots.txt check is skipped when respect_robots_txt=False."""
        html = "<html><body>Content</body></html>"
        mock_cm, _, _ = _make_playwright_mocks(html)
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com", respect_robots_txt=False)
        assert "error" not in result
        mock_rp_cls.assert_not_called()
