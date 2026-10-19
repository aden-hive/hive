"""Tests for HTTP Headers Scanner tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.http_headers_scanner import register_tools


@pytest.fixture
def headers_tools(mcp: FastMCP):
    """Register HTTP headers tools and return tool functions."""
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def scan_fn(headers_tools):
    return headers_tools["http_headers_scan"]


def _mock_response(
    status_code: int = 200,
    headers: dict | None = None,
    url: str = "https://example.com",
) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.url = url
    resp.headers = httpx.Headers(headers or {})
    return resp


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Test URL input cleaning and validation."""

    @pytest.mark.asyncio
    async def test_auto_prefix_https(self, scan_fn):
        mock_resp = _mock_response(headers={"strict-transport-security": "max-age=31536000"})
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("example.com")
            assert "error" not in result
            # Verify https was prefixed
            mock_client.get.assert_called_once()
            call_url = mock_client.get.call_args[0][0]
            assert call_url.startswith("https://")


# ---------------------------------------------------------------------------
# Connection Errors
# ---------------------------------------------------------------------------


class TestConnectionErrors:
    """Test error handling for connection failures."""

    @pytest.mark.asyncio
    async def test_connection_error(self, scan_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("https://example.com")
            assert "error" in result
            assert "Connection failed" in result["error"]

    @pytest.mark.asyncio
    async def test_timeout_error(self, scan_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("Request timed out")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("https://example.com")
            assert "error" in result
            assert "timed out" in result["error"]


# ---------------------------------------------------------------------------
# Security Headers Detection
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    """Test detection of OWASP security headers."""

    @pytest.mark.asyncio
    async def test_all_headers_present(self, scan_fn):
        headers = {
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "camera=(), microphone=()",
        }
        mock_resp = _mock_response(headers=headers)
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("https://example.com")
            assert len(result["headers_present"]) == 6
            assert len(result["headers_missing"]) == 0
            assert result["grade_input"]["hsts"] is True
            assert result["grade_input"]["csp"] is True

    @pytest.mark.asyncio
    async def test_missing_hsts(self, scan_fn):
        headers = {
            "Content-Security-Policy": "default-src 'self'",
            "X-Frame-Options": "DENY",
        }
        mock_resp = _mock_response(headers=headers)
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("https://example.com")
            assert result["grade_input"]["hsts"] is False
            missing_names = [h["header"] for h in result["headers_missing"]]
            assert "Strict-Transport-Security" in missing_names

    @pytest.mark.asyncio
    async def test_missing_csp(self, scan_fn):
        headers = {
            "Strict-Transport-Security": "max-age=31536000",
        }
        mock_resp = _mock_response(headers=headers)
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("https://example.com")
            assert result["grade_input"]["csp"] is False
            missing_names = [h["header"] for h in result["headers_missing"]]
            assert "Content-Security-Policy" in missing_names


# ---------------------------------------------------------------------------
# Leaky Headers Detection
# ---------------------------------------------------------------------------


class TestLeakyHeaders:
    """Test detection of information-leaking headers."""

    @pytest.mark.asyncio
    async def test_server_header_leaked(self, scan_fn):
        headers = {"Server": "Apache/2.4.41 (Ubuntu)"}
        mock_resp = _mock_response(headers=headers)
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("https://example.com")
            assert len(result["leaky_headers"]) > 0
            leaky_names = [h["header"] for h in result["leaky_headers"]]
            assert "Server" in leaky_names
            assert result["grade_input"]["no_leaky_headers"] is False

    @pytest.mark.asyncio
    async def test_x_powered_by_leaked(self, scan_fn):
        headers = {"X-Powered-By": "PHP/8.1.0"}
        mock_resp = _mock_response(headers=headers)
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("https://example.com")
            leaky_names = [h["header"] for h in result["leaky_headers"]]
            assert "X-Powered-By" in leaky_names

    @pytest.mark.asyncio
    async def test_no_leaky_headers(self, scan_fn):
        headers = {
            "Strict-Transport-Security": "max-age=31536000",
            "Content-Type": "text/html",
        }
        mock_resp = _mock_response(headers=headers)
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("https://example.com")
            assert len(result["leaky_headers"]) == 0
            assert result["grade_input"]["no_leaky_headers"] is True


# ---------------------------------------------------------------------------
# Deprecated Headers
# ---------------------------------------------------------------------------


class TestDeprecatedHeaders:
    """Test detection of deprecated headers."""

    @pytest.mark.asyncio
    async def test_xss_protection_deprecated(self, scan_fn):
        headers = {"X-XSS-Protection": "1; mode=block"}
        mock_resp = _mock_response(headers=headers)
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("https://example.com")
            assert "X-XSS-Protection (deprecated)" in result["headers_present"]


# ---------------------------------------------------------------------------
# Grade Input
# ---------------------------------------------------------------------------


class TestGradeInput:
    """Test grade_input dict is properly constructed."""

    @pytest.mark.asyncio
    async def test_grade_input_keys_present(self, scan_fn):
        mock_resp = _mock_response(headers={})
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("https://example.com")
            assert "grade_input" in result
            grade = result["grade_input"]
            assert "hsts" in grade
            assert "csp" in grade
            assert "x_frame_options" in grade
            assert "x_content_type_options" in grade
            assert "referrer_policy" in grade
            assert "permissions_policy" in grade
            assert "no_leaky_headers" in grade


# ---------------------------------------------------------------------------
# Response Metadata
# ---------------------------------------------------------------------------


class TestResponseMetadata:
    """Test response metadata is captured."""

    @pytest.mark.asyncio
    async def test_status_code_captured(self, scan_fn):
        mock_resp = _mock_response(status_code=200, headers={})
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("https://example.com")
            assert result["status_code"] == 200

    @pytest.mark.asyncio
    async def test_final_url_captured(self, scan_fn):
        mock_resp = _mock_response(status_code=200, headers={}, url="https://www.example.com/")
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await scan_fn("https://example.com")
            assert result["url"] == "https://www.example.com/"
