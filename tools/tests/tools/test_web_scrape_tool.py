"""Tests for web_scrape tool (FastMCP)."""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.web_scrape_tool import register_tools
from aden_tools.tools.web_scrape_tool.web_scrape_tool import (
    _check_url_target,
    _is_internal_address,
)


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
    async def test_truncation_respects_max_length(self, mock_pw, mock_stealth, web_scrape_fn):
        """Truncated content (including the ellipsis) must not exceed max_length."""
        # max_length is clamped to >=1000, so build content larger than that
        long_text = "a" * 5000
        html = f"<html><body>{long_text}</body></html>"
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com", max_length=1000)
        assert "error" not in result
        assert len(result["content"]) <= 1000
        assert result["content"].endswith("...")
        assert result["length"] == len(result["content"])

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


class TestWebScrapeToolAIFriendlyOutput:
    """Tests for the AI-friendly output additions: structured data,
    headings, page_type, block-level newlines, inline links, truncation
    metadata, and offset-based pagination."""

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_block_level_newlines_preserved(self, mock_pw, mock_stealth, web_scrape_fn):
        """Block elements (p, h1, li) produce newlines, not space-collapsed."""
        html = """
        <html><body>
            <h1>Title</h1>
            <p>First paragraph.</p>
            <p>Second paragraph.</p>
            <ul><li>Item one</li><li>Item two</li></ul>
        </body></html>
        """
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com")
        assert "error" not in result
        content = result["content"]
        assert "Title" in content
        assert "First paragraph." in content
        assert "Second paragraph." in content
        # Block separation should produce newlines, not run paragraphs together
        assert "First paragraph.\n" in content or "First paragraph.\n\nSecond" in content
        assert "Item one" in content and "Item two" in content

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_headings_outline_returned(self, mock_pw, mock_stealth, web_scrape_fn):
        """Headings outline lists h1-h6 with level + text."""
        html = """
        <html><body>
            <h1>Top</h1>
            <h2>Section A</h2>
            <h3>Sub A1</h3>
        </body></html>
        """
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com")
        assert result["headings"] == [
            {"level": 1, "text": "Top"},
            {"level": 2, "text": "Section A"},
            {"level": 3, "text": "Sub A1"},
        ]

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_inline_links_when_include_links(self, mock_pw, mock_stealth, web_scrape_fn):
        """include_links=True inlines anchors as [text](url) in content."""
        html = """
        <html><body>
            <p>See <a href="/docs">our docs</a> for details.</p>
        </body></html>
        """
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com", include_links=True)
        assert "[our docs](https://example.com/docs)" in result["content"]
        # Separate links list still present for back-compat
        assert any(link["text"] == "our docs" for link in result["links"])

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_structured_data_json_ld(self, mock_pw, mock_stealth, web_scrape_fn):
        """JSON-LD blocks are parsed and surfaced under structured_data."""
        html = """
        <html><head>
            <script type="application/ld+json">
            {"@type": "Article", "headline": "Hello"}
            </script>
        </head><body><p>body</p></body></html>
        """
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com")
        assert "structured_data" in result
        assert result["structured_data"]["json_ld"] == [{"@type": "Article", "headline": "Hello"}]

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_structured_data_open_graph(self, mock_pw, mock_stealth, web_scrape_fn):
        """OpenGraph meta tags are surfaced under structured_data.open_graph."""
        html = """
        <html><head>
            <meta property="og:title" content="OG Title">
            <meta property="og:type" content="article">
        </head><body><p>body</p></body></html>
        """
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com")
        assert result["structured_data"]["open_graph"] == {
            "title": "OG Title",
            "type": "article",
        }

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_truncation_metadata(self, mock_pw, mock_stealth, web_scrape_fn):
        """Truncated responses set truncated/total_length/next_offset."""
        html = f"<html><body>{'a' * 5000}</body></html>"
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com", max_length=1000)
        assert result["truncated"] is True
        assert result["total_length"] == 5000
        assert result["next_offset"] == 1000
        assert result["offset"] == 0

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_offset_pagination(self, mock_pw, mock_stealth, web_scrape_fn):
        """offset arg returns content starting from the given character."""
        body = "a" * 1000 + "b" * 1000 + "c" * 1000
        html = f"<html><body>{body}</body></html>"
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com", max_length=1000, offset=1000)
        assert result["offset"] == 1000
        # Window should start in the b-region
        assert result["content"].startswith("b")
        assert result["truncated"] is True
        assert result["next_offset"] == 2000

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_page_type_listing(self, mock_pw, mock_stealth, web_scrape_fn):
        """3+ <article> elements => page_type 'listing'."""
        html = """
        <html><body>
            <article><h2>Post 1</h2></article>
            <article><h2>Post 2</h2></article>
            <article><h2>Post 3</h2></article>
        </body></html>
        """
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com")
        assert result["page_type"] == "listing"

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    async def test_page_type_article(self, mock_pw, mock_stealth, web_scrape_fn):
        """Single <article> => page_type 'article'."""
        html = "<html><body><article><p>Hello</p></article></body></html>"
        mock_cm, _, _ = _make_playwright_mocks(html, final_url="https://example.com")
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com")
        assert result["page_type"] == "article"


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
        assert result["error"] == "HTTP 404: Failed to fetch URL"
        assert result["status"] == 404
        assert "hint" in result
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


_MOD = "aden_tools.tools.web_scrape_tool.web_scrape_tool"


class TestIsInternalAddress:
    """Tests for _is_internal_address."""

    def test_loopback_ipv4(self):
        assert _is_internal_address("127.0.0.1") is True

    def test_private_10_range(self):
        assert _is_internal_address("10.0.0.1") is True

    def test_private_192_168(self):
        assert _is_internal_address("192.168.1.1") is True

    def test_link_local_aws_metadata(self):
        assert _is_internal_address("169.254.169.254") is True

    def test_public_ipv4(self):
        assert _is_internal_address("8.8.8.8") is False

    def test_public_ipv6(self):
        assert _is_internal_address("2607:f8b0:4004:800::200e") is False

    def test_invalid_string_blocked(self):
        assert _is_internal_address("not-an-ip") is True


def _fake_addrinfo(ip: str, port: int = 443) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


class TestCheckUrlTarget:
    """Tests for _check_url_target."""

    @patch(f"{_MOD}.socket.getaddrinfo")
    def test_public_hostname_allowed(self, mock_dns):
        mock_dns.return_value = _fake_addrinfo("93.184.216.34")
        assert _check_url_target("https://example.com/page") is None

    @patch(f"{_MOD}.socket.getaddrinfo")
    def test_private_hostname_blocked(self, mock_dns):
        mock_dns.return_value = _fake_addrinfo("10.0.0.1")
        result = _check_url_target("https://evil.com/steal")
        assert result is not None
        assert "internal" in result.lower()

    def test_raw_private_ip_blocked(self):
        result = _check_url_target("http://127.0.0.1/admin")
        assert result is not None

    @patch(
        f"{_MOD}.socket.getaddrinfo",
        side_effect=socket.gaierror("NXDOMAIN"),
    )
    def test_dns_failure_returns_error(self, _mock_dns):
        result = _check_url_target("https://nonexistent.invalid/")
        assert result is not None
        assert "DNS" in result


class TestWebScrapeSSRF:
    """SSRF protection through the web_scrape tool."""

    @pytest.mark.asyncio
    async def test_blocks_private_ip(self, web_scrape_fn):
        result = await web_scrape_fn(url="http://192.168.1.1/admin")
        assert "error" in result
        assert result.get("blocked_by_ssrf_protection") is True

    @pytest.mark.asyncio
    async def test_blocks_localhost(self, web_scrape_fn):
        result = await web_scrape_fn(url="http://127.0.0.1/secret")
        assert "error" in result
        assert result.get("blocked_by_ssrf_protection") is True

    @pytest.mark.asyncio
    async def test_blocks_metadata_endpoint(self, web_scrape_fn):
        result = await web_scrape_fn(url="http://169.254.169.254/latest/meta-data/")
        assert "error" in result
        assert result.get("blocked_by_ssrf_protection") is True

    @pytest.mark.asyncio
    @patch(_STEALTH_PATH)
    @patch(_PW_PATH)
    @patch(f"{_MOD}._check_url_target", return_value=None)
    async def test_allows_public_url(self, _mock_check, mock_pw, mock_stealth, web_scrape_fn):
        html = "<html><body><p>Hello world</p></body></html>"
        mock_cm, _, _ = _make_playwright_mocks(html)
        mock_pw.return_value = mock_cm
        mock_stealth.return_value.apply_stealth_async = AsyncMock()

        result = await web_scrape_fn(url="https://example.com/")
        assert "error" not in result
        assert "Hello world" in result["content"]
