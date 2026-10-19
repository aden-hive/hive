"""Tests for Tech Stack Detector tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.tech_stack_detector import register_tools
from aden_tools.tools.tech_stack_detector.tech_stack_detector import (
    _detect_cdn,
    _detect_cms_from_html,
    _detect_js_libraries,
    _detect_server,
)


@pytest.fixture
def tech_tools(mcp: FastMCP):
    """Register tech stack tools and return tool functions."""
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def detect_fn(tech_tools):
    return tech_tools["tech_stack_detect"]


class FakeHeaders:
    """Minimal stand-in for httpx.Headers."""

    def __init__(self, headers: dict):
        self._headers = {k.lower(): v for k, v in headers.items()}

    def get(self, name: str, default=None):
        return self._headers.get(name.lower(), default)

    def get_list(self, name: str) -> list[str]:
        val = self._headers.get(name.lower())
        if val is None:
            return []
        if isinstance(val, list):
            return val
        return [val]


# ---------------------------------------------------------------------------
# Helper Function Tests
# ---------------------------------------------------------------------------


class TestDetectServer:
    """Test _detect_server helper."""

    def test_server_with_version(self):
        headers = FakeHeaders({"server": "nginx/1.21.0"})
        result = _detect_server(headers)
        assert result["name"] == "nginx"
        assert result["version"] == "1.21.0"

    def test_server_without_version(self):
        headers = FakeHeaders({"server": "cloudflare"})
        result = _detect_server(headers)
        assert result["name"] == "cloudflare"
        assert result["version"] is None

    def test_no_server_header(self):
        headers = FakeHeaders({})
        result = _detect_server(headers)
        assert result is None


class TestDetectCdn:
    """Test _detect_cdn helper."""

    def test_cloudflare_detected(self):
        headers = FakeHeaders({"cf-ray": "123abc"})
        result = _detect_cdn(headers)
        assert result == "Cloudflare"

    def test_vercel_detected(self):
        headers = FakeHeaders({"x-vercel-id": "abc123"})
        result = _detect_cdn(headers)
        assert result == "Vercel"

    def test_no_cdn(self):
        headers = FakeHeaders({"content-type": "text/html"})
        result = _detect_cdn(headers)
        assert result is None


class TestDetectJsLibraries:
    """Test _detect_js_libraries helper."""

    def test_react_detected(self):
        html = '<script src="/static/react.min.js"></script>'
        result = _detect_js_libraries(html)
        assert "React" in result

    def test_jquery_detected(self):
        html = '<script src="https://cdn.example.com/jquery-3.6.0.min.js"></script>'
        result = _detect_js_libraries(html)
        assert any("jQuery" in lib for lib in result)

    def test_nextjs_detected(self):
        html = '<script id="__NEXT_DATA__" type="application/json">{}</script>'
        result = _detect_js_libraries(html)
        assert "Next.js" in result

    def test_no_libraries(self):
        html = "<html><body>Simple page</body></html>"
        result = _detect_js_libraries(html)
        assert len(result) == 0


class TestDetectCms:
    """Test _detect_cms_from_html helper."""

    def test_wordpress_detected(self):
        html = '<link href="/wp-content/themes/theme/style.css">'
        result = _detect_cms_from_html(html)
        assert result == "WordPress"

    def test_shopify_detected(self):
        html = '<script src="https://cdn.shopify.com/s/files/1/theme.js"></script>'
        result = _detect_cms_from_html(html)
        assert result == "Shopify"

    def test_drupal_detected(self):
        html = '<script src="/core/misc/drupal.js"></script>'
        result = _detect_cms_from_html(html)
        assert result == "Drupal"

    def test_no_cms(self):
        html = "<html><body>Custom site</body></html>"
        result = _detect_cms_from_html(html)
        assert result is None


# ---------------------------------------------------------------------------
# Connection Errors
# ---------------------------------------------------------------------------


class TestConnectionErrors:
    """Test error handling for connection failures."""

    @pytest.mark.asyncio
    async def test_connection_error(self, detect_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await detect_fn("https://example.com")
            assert "error" in result
            assert "Connection failed" in result["error"]

    @pytest.mark.asyncio
    async def test_timeout_error(self, detect_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("timeout")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await detect_fn("https://example.com")
            assert "error" in result
            assert "timed out" in result["error"]


# ---------------------------------------------------------------------------
# Full Detection Flow
# ---------------------------------------------------------------------------


class TestFullDetection:
    """Test full tech stack detection."""

    def _mock_response(
        self,
        html: str = "<html></html>",
        headers: dict | None = None,
        cookies: dict | None = None,
    ):
        resp = MagicMock()
        resp.text = html
        resp.url = "https://example.com"
        resp.headers = httpx.Headers(headers or {})
        resp.cookies = httpx.Cookies(cookies or {})
        return resp

    @pytest.mark.asyncio
    async def test_detects_server(self, detect_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = self._mock_response(headers={"server": "nginx/1.21.0"})
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await detect_fn("https://example.com")
            assert result["server"]["name"] == "nginx"

    @pytest.mark.asyncio
    async def test_detects_framework(self, detect_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = self._mock_response(headers={"x-powered-by": "Express"})
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await detect_fn("https://example.com")
            assert result["framework"] == "Express"


# ---------------------------------------------------------------------------
# Grade Input
# ---------------------------------------------------------------------------


class TestGradeInput:
    """Test grade_input dict is properly constructed."""

    def _mock_response(self, html: str = "<html></html>", headers: dict | None = None):
        resp = MagicMock()
        resp.text = html
        resp.url = "https://example.com"
        resp.headers = httpx.Headers(headers or {})
        resp.cookies = httpx.Cookies()
        return resp

    @pytest.mark.asyncio
    async def test_grade_input_keys_present(self, detect_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = self._mock_response()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await detect_fn("https://example.com")
            assert "grade_input" in result
            grade = result["grade_input"]
            assert "server_version_hidden" in grade
            assert "framework_version_hidden" in grade
            assert "security_txt_present" in grade
            assert "cookies_secure" in grade
            assert "cookies_httponly" in grade

    @pytest.mark.asyncio
    async def test_server_version_exposed(self, detect_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = self._mock_response(headers={"server": "Apache/2.4.41"})
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await detect_fn("https://example.com")
            assert result["grade_input"]["server_version_hidden"] is False
