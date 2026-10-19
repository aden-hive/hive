"""Tests for web_scrape tool (FastMCP)."""

import socket
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.web_scrape_tool import register_tools
from aden_tools.tools.web_scrape_tool.web_scrape_tool import (
    _check_url_target,
    _is_internal_address,
)

_MOD = "aden_tools.tools.web_scrape_tool.web_scrape_tool"
_PW_PATH = f"{_MOD}.async_playwright"
_STEALTH_PATH = f"{_MOD}.Stealth"


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _scrape_artifact_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect scrape artifact writes into a per-test tmp dir so tests
    don't pollute ~/.hive/web-scrape-artifacts (the production fallback
    when HIVE_STORAGE_PATH is unset)."""
    monkeypatch.setenv("HIVE_STORAGE_PATH", str(tmp_path))


@pytest.fixture
def web_scrape_fn(mcp: FastMCP):
    """Register and return the web_scrape tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["web_scrape"].fn


def _saved_body(result: dict) -> str:
    """Read the extracted text body the tool wrote to disk."""
    path = result.get("saved_to")
    return Path(path).read_text(encoding="utf-8") if path else ""


def _make_playwright_mocks(html, status=200, final_url="https://example.com/page", content_type="text/html; charset=utf-8"):
    """Build a full playwright mock chain and return (context_manager, response, page)."""
    mock_response = MagicMock(status=status, url=final_url, headers={"content-type": content_type})
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

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_cm, mock_response, mock_page


@pytest.fixture
def scrape(web_scrape_fn):
    """Run web_scrape against mocked Playwright and return (result, mock_page).

    Positional: ``html`` body the mocked page will return.
    Keyword:
      - ``url``: URL passed to web_scrape (default https://example.com)
      - ``status``, ``final_url``, ``content_type``: tune the mock response
      - ``null_response``: when True, page.goto returns None (sim. nav failure)
      - any other kwargs forward to web_scrape_fn (selector, include_links, ...)
    """

    async def _run(
        html="<html><body>Hello</body></html>",
        *,
        url="https://example.com",
        status=200,
        final_url="https://example.com/page",
        content_type="text/html; charset=utf-8",
        null_response=False,
        **scrape_kwargs,
    ):
        mock_cm, _, mock_page = _make_playwright_mocks(html, status=status, final_url=final_url, content_type=content_type)
        if null_response:
            mock_page.goto.return_value = None
        with patch(_PW_PATH) as mock_pw, patch(_STEALTH_PATH) as mock_stealth:
            mock_pw.return_value = mock_cm
            mock_stealth.return_value.apply_stealth_async = AsyncMock()
            result = await web_scrape_fn(url=url, **scrape_kwargs)
        return result, mock_page

    return _run


# ---------------------------------------------------------------------------
# Tool behavior
# ---------------------------------------------------------------------------


class TestWebScrapeTool:
    @pytest.mark.asyncio
    async def test_url_auto_prefixed_with_https(self, scrape):
        """URLs without scheme get https:// prefix."""
        result, _ = await scrape(url="example.com")
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_body_written_to_disk(self, scrape):
        """Extracted body lands on disk; total_length matches; response
        carries no inline body."""
        result, _ = await scrape("<html><body><p>Hello world</p></body></html>")
        assert "error" not in result
        # Inline body fields are gone — payload lives on disk.
        for gone in ("content", "length", "next_offset", "truncated", "offset"):
            assert gone not in result
        assert result["saved_to"]
        body = _saved_body(result)
        assert "Hello world" in body
        assert result["total_length"] == len(body)

    @pytest.mark.asyncio
    async def test_include_links_option(self, scrape):
        result, _ = await scrape(
            '<html><body><a href="/link">Link</a></body></html>',
            include_links=True,
        )
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_selector_option(self, scrape):
        result, _ = await scrape(
            '<html><body><div class="content">Content here</div></body></html>',
            selector=".content",
        )
        assert "error" not in result


# ---------------------------------------------------------------------------
# Link conversion
# ---------------------------------------------------------------------------


def _hrefs(result: dict) -> dict[str, str]:
    return {link["text"]: link["href"] for link in result["links"]}


class TestWebScrapeToolLinkConversion:
    @pytest.mark.asyncio
    async def test_relative_links_converted_to_absolute(self, scrape):
        html = """
        <html><body>
            <a href="../home">Home</a>
            <a href="page.html">Next Page</a>
        </body></html>
        """
        result, _ = await scrape(
            html,
            url="https://example.com/blog/post",
            final_url="https://example.com/blog/post",
            include_links=True,
        )
        hrefs = _hrefs(result)
        assert hrefs["Home"] == "https://example.com/home"
        assert hrefs["Next Page"] == "https://example.com/blog/page.html"

    @pytest.mark.asyncio
    async def test_root_relative_links_converted(self, scrape):
        html = '<html><body><a href="/about">About</a><a href="/contact">Contact</a></body></html>'
        result, _ = await scrape(
            html,
            url="https://example.com/blog/post",
            final_url="https://example.com/blog/post",
            include_links=True,
        )
        hrefs = _hrefs(result)
        assert hrefs["About"] == "https://example.com/about"
        assert hrefs["Contact"] == "https://example.com/contact"

    @pytest.mark.asyncio
    async def test_absolute_links_unchanged(self, scrape):
        html = '<html><body><a href="https://other.com">Other Site</a><a href="https://example.com/page">Internal</a></body></html>'
        result, _ = await scrape(html, include_links=True)
        hrefs = _hrefs(result)
        assert hrefs["Other Site"] == "https://other.com"
        assert hrefs["Internal"] == "https://example.com/page"

    @pytest.mark.asyncio
    async def test_links_after_redirects(self, scrape):
        """Links resolve relative to FINAL URL, not the requested URL."""
        html = '<html><body><a href="../prev">Previous</a><a href="next">Next</a></body></html>'
        result, _ = await scrape(
            html,
            url="https://example.com/old/url",
            final_url="https://example.com/new/location",
            include_links=True,
        )
        hrefs = _hrefs(result)
        assert hrefs["Previous"] == "https://example.com/prev"
        assert hrefs["Next"] == "https://example.com/new/next"

    @pytest.mark.asyncio
    async def test_fragment_links_preserved(self, scrape):
        html = '<html><body><a href="#section1">Section 1</a><a href="/page#section2">Page Section 2</a></body></html>'
        result, _ = await scrape(
            html,
            url="https://example.com/page",
            final_url="https://example.com/page",
            include_links=True,
        )
        hrefs = _hrefs(result)
        assert hrefs["Section 1"] == "https://example.com/page#section1"
        assert hrefs["Page Section 2"] == "https://example.com/page#section2"

    @pytest.mark.asyncio
    async def test_query_parameters_preserved(self, scrape):
        html = '<html><body><a href="page?id=123">View Item</a><a href="/search?q=test&sort=date">Search</a></body></html>'
        result, _ = await scrape(
            html,
            url="https://example.com/blog/post",
            final_url="https://example.com/blog/post",
            include_links=True,
        )
        hrefs = _hrefs(result)
        assert "id=123" in hrefs["View Item"]
        assert "q=test" in hrefs["Search"]
        assert "sort=date" in hrefs["Search"]

    @pytest.mark.asyncio
    async def test_empty_href_skipped(self, scrape):
        """Links with empty or whitespace-only text are filtered."""
        html = '<html><body><a href="/valid">Valid Link</a><a href="/empty"></a><a href="/whitespace">   </a></body></html>'
        result, _ = await scrape(html, include_links=True)
        texts = [link["text"] for link in result["links"]]
        assert "Valid Link" in texts
        assert all(t.strip() for t in texts)


# ---------------------------------------------------------------------------
# AI-friendly output: structured data, headings, page_type, body persistence
# ---------------------------------------------------------------------------


class TestWebScrapeToolAIFriendlyOutput:
    @pytest.mark.asyncio
    async def test_block_level_newlines_preserved(self, scrape):
        """Block elements (p, h1, li) produce newlines, not space-collapsed."""
        html = """
        <html><body>
            <h1>Title</h1>
            <p>First paragraph.</p>
            <p>Second paragraph.</p>
            <ul><li>Item one</li><li>Item two</li></ul>
        </body></html>
        """
        result, _ = await scrape(html)
        content = _saved_body(result)
        assert "Title" in content
        assert "First paragraph." in content
        assert "Second paragraph." in content
        assert "First paragraph.\n" in content or "First paragraph.\n\nSecond" in content
        assert "Item one" in content and "Item two" in content

    @pytest.mark.asyncio
    async def test_headings_outline_returned(self, scrape):
        html = "<html><body><h1>Top</h1><h2>Section A</h2><h3>Sub A1</h3></body></html>"
        result, _ = await scrape(html)
        assert result["headings"] == [
            {"level": 1, "text": "Top"},
            {"level": 2, "text": "Section A"},
            {"level": 3, "text": "Sub A1"},
        ]

    @pytest.mark.asyncio
    async def test_inline_links_when_include_links(self, scrape):
        """include_links=True inlines anchors as [text](url) in the saved body."""
        html = '<html><body><p>See <a href="/docs">our docs</a> for details.</p></body></html>'
        result, _ = await scrape(html, include_links=True)
        assert "[our docs](https://example.com/docs)" in _saved_body(result)
        assert any(link["text"] == "our docs" for link in result["links"])

    @pytest.mark.asyncio
    async def test_structured_data_json_ld(self, scrape):
        html = (
            '<html><head><script type="application/ld+json">{"@type": "Article", "headline": "Hello"}</script></head><body><p>body</p></body></html>'
        )
        result, _ = await scrape(html)
        assert result["structured_data"]["json_ld"] == [{"@type": "Article", "headline": "Hello"}]

    @pytest.mark.asyncio
    async def test_structured_data_open_graph(self, scrape):
        html = (
            "<html><head>"
            '<meta property="og:title" content="OG Title">'
            '<meta property="og:type" content="article">'
            "</head><body><p>body</p></body></html>"
        )
        result, _ = await scrape(html)
        assert result["structured_data"]["open_graph"] == {
            "title": "OG Title",
            "type": "article",
        }

    @pytest.mark.asyncio
    async def test_full_body_persisted_regardless_of_size(self, scrape):
        """The complete extracted body is written to disk — no truncation,
        no pagination. The agent reads/greps the file on demand."""
        result, _ = await scrape(f"<html><body>{'a' * 5000}</body></html>")
        body = _saved_body(result)
        assert result["total_length"] == 5000
        assert body == "a" * 5000

    @pytest.mark.asyncio
    async def test_page_type_listing(self, scrape):
        """3+ <article> elements => page_type 'listing'."""
        html = "<html><body><article><h2>Post 1</h2></article><article><h2>Post 2</h2></article><article><h2>Post 3</h2></article></body></html>"
        result, _ = await scrape(html)
        assert result["page_type"] == "listing"

    @pytest.mark.asyncio
    async def test_page_type_article(self, scrape):
        result, _ = await scrape("<html><body><article><p>Hello</p></article></body></html>")
        assert result["page_type"] == "article"


# ---------------------------------------------------------------------------
# Error handling — verify early exit before networkidle wait
# ---------------------------------------------------------------------------


class TestWebScrapeToolErrorHandling:
    @pytest.mark.asyncio
    async def test_http_error_returns_without_waiting(self, scrape):
        result, page = await scrape(
            "<html><body>Not Found</body></html>",
            url="https://example.com/missing",
            status=404,
        )
        assert result["error"] == "HTTP 404: Failed to fetch URL"
        assert result["status"] == 404
        assert "hint" in result
        page.wait_for_load_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_null_response_returns_error(self, scrape):
        result, page = await scrape("<html></html>", null_response=True)
        assert result == {"error": "Navigation failed: no response received"}
        page.wait_for_load_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_html_content_type_skipped(self, scrape):
        result, page = await scrape(
            "<html></html>",
            url="https://example.com/file.pdf",
            content_type="application/pdf",
        )
        assert "error" in result
        assert result["skipped"] is True
        page.wait_for_load_state.assert_not_called()


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------


class TestWebScrapeToolRobotsTxt:
    @pytest.mark.asyncio
    @patch(f"{_MOD}.httpx.AsyncClient")
    @patch(f"{_MOD}.RobotFileParser")
    async def test_blocked_by_robots_txt(self, mock_rp_cls, mock_httpx_cls, scrape):
        """URLs disallowed by robots.txt are skipped before any page load."""
        # Stub httpx.AsyncClient(...) async context manager.
        mock_resp = MagicMock(status_code=200, text="User-agent: *\nDisallow: /")
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cm = MagicMock()
        mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cm.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_cls.return_value = mock_client_cm

        mock_rp = MagicMock()
        mock_rp.can_fetch.return_value = False
        mock_rp_cls.return_value = mock_rp

        # robots.txt is only consulted when explicitly opted in (the tool
        # defaults respect_robots_txt=False).
        result, _ = await scrape("<html></html>", url="https://example.com/private", respect_robots_txt=True)
        assert "robots.txt" in result["error"]
        assert result["skipped"] is True

    @pytest.mark.asyncio
    @patch(f"{_MOD}.RobotFileParser")
    async def test_robots_txt_disabled(self, mock_rp_cls, scrape):
        """robots.txt check is skipped when respect_robots_txt=False."""
        result, _ = await scrape("<html><body>Content</body></html>", respect_robots_txt=False)
        assert "error" not in result
        mock_rp_cls.assert_not_called()


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------


class TestIsInternalAddress:
    @pytest.mark.parametrize(
        "ip, expected",
        [
            ("127.0.0.1", True),  # loopback
            ("10.0.0.1", True),  # private 10.x
            ("192.168.1.1", True),  # private 192.168.x
            ("169.254.169.254", True),  # AWS metadata
            ("8.8.8.8", False),  # public IPv4
            ("2607:f8b0:4004:800::200e", False),  # public IPv6
            ("not-an-ip", True),  # unparseable → fail closed
        ],
    )
    def test_classification(self, ip, expected):
        assert _is_internal_address(ip) is expected


def _fake_addrinfo(ip: str, port: int = 443) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


class TestCheckUrlTarget:
    @pytest.mark.asyncio
    @patch(f"{_MOD}.socket.getaddrinfo")
    async def test_public_hostname_allowed(self, mock_dns):
        mock_dns.return_value = _fake_addrinfo("93.184.216.34")
        assert await _check_url_target("https://example.com/page") is None

    @pytest.mark.asyncio
    @patch(f"{_MOD}.socket.getaddrinfo")
    async def test_private_hostname_blocked(self, mock_dns):
        mock_dns.return_value = _fake_addrinfo("10.0.0.1")
        result = await _check_url_target("https://evil.com/steal")
        assert result is not None
        assert "internal" in result.lower()

    @pytest.mark.asyncio
    async def test_raw_private_ip_blocked(self):
        assert await _check_url_target("http://127.0.0.1/admin") is not None

    @pytest.mark.asyncio
    @patch(f"{_MOD}.socket.getaddrinfo", side_effect=socket.gaierror("NXDOMAIN"))
    async def test_dns_failure_returns_error(self, _mock_dns):
        result = await _check_url_target("https://nonexistent.invalid/")
        assert result is not None
        assert "DNS" in result


class TestWebScrapeSSRF:
    """End-to-end SSRF protection through the web_scrape tool."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://192.168.1.1/admin",
            "http://127.0.0.1/secret",
            "http://169.254.169.254/latest/meta-data/",
        ],
    )
    async def test_blocks_internal_targets(self, url, web_scrape_fn):
        result = await web_scrape_fn(url=url)
        assert "error" in result
        assert result.get("blocked_by_ssrf_protection") is True

    @pytest.mark.asyncio
    @patch(f"{_MOD}._check_url_target", new_callable=AsyncMock, return_value=None)
    async def test_allows_public_url(self, _mock_check, scrape):
        result, _ = await scrape("<html><body><p>Hello world</p></body></html>", url="https://example.com/")
        assert "error" not in result
        assert "Hello world" in _saved_body(result)
