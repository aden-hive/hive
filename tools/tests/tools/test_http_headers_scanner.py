"""Tests for http_headers_scanner - OWASP security headers analysis."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.http_headers_scanner.http_headers_scanner import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


def _mock_response(headers: dict, status_code: int = 200, url: str = "https://example.com"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.url = url
    resp.headers = {k.lower(): v for k, v in headers.items()}
    return resp


class TestHttpHeadersScanConnectionErrors:
    @pytest.mark.asyncio
    async def test_connect_error(self, tool_fns):
        import httpx

        with patch(
            "aden_tools.tools.http_headers_scanner.http_headers_scanner.httpx.AsyncClient"
        ) as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                side_effect=httpx.ConnectError("refused")
            )
            result = await tool_fns["http_headers_scan"](url="https://example.com")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_timeout_error(self, tool_fns):
        import httpx

        with patch(
            "aden_tools.tools.http_headers_scanner.http_headers_scanner.httpx.AsyncClient"
        ) as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                side_effect=httpx.TimeoutException("timed out")
            )
            result = await tool_fns["http_headers_scan"](url="https://example.com")
        assert "error" in result
        assert "timed out" in result["error"]


class TestHttpHeadersScanSecureHeaders:
    @pytest.mark.asyncio
    async def test_all_security_headers_present(self, tool_fns):
        headers = {
            "strict-transport-security": "max-age=31536000; includeSubDomains",
            "content-security-policy": "default-src 'self'",
            "x-frame-options": "DENY",
            "x-content-type-options": "nosniff",
            "referrer-policy": "strict-origin-when-cross-origin",
            "permissions-policy": "camera=()",
        }
        mock_resp = _mock_response(headers)
        with patch(
            "aden_tools.tools.http_headers_scanner.http_headers_scanner.httpx.AsyncClient"
        ) as mock_client:
            mock_get = AsyncMock(return_value=mock_resp)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await tool_fns["http_headers_scan"](url="https://example.com")

        assert result["grade_input"]["hsts"] is True
        assert result["grade_input"]["csp"] is True
        assert result["grade_input"]["x_frame_options"] is True
        assert result["grade_input"]["x_content_type_options"] is True
        assert len(result["headers_missing"]) == 0

    @pytest.mark.asyncio
    async def test_no_security_headers(self, tool_fns):
        mock_resp = _mock_response({})
        with patch(
            "aden_tools.tools.http_headers_scanner.http_headers_scanner.httpx.AsyncClient"
        ) as mock_client:
            mock_get = AsyncMock(return_value=mock_resp)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await tool_fns["http_headers_scan"](url="https://example.com")

        assert result["grade_input"]["hsts"] is False
        assert result["grade_input"]["csp"] is False
        assert len(result["headers_missing"]) == 6

    @pytest.mark.asyncio
    async def test_leaky_server_header_detected(self, tool_fns):
        # Use original casing — the scanner does `headers.get("Server")` not lowercased
        headers = {"Server": "Apache/2.4.51 (Ubuntu)"}
        mock_resp = _mock_response(headers)
        # Preserve original-case header in mock so scanner's .get("Server") works
        mock_resp.headers = headers
        with patch(
            "aden_tools.tools.http_headers_scanner.http_headers_scanner.httpx.AsyncClient"
        ) as mock_client:
            mock_get = AsyncMock(return_value=mock_resp)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await tool_fns["http_headers_scan"](url="https://example.com")

        assert result["grade_input"]["no_leaky_headers"] is False
        assert any(h["header"] == "Server" for h in result["leaky_headers"])

    @pytest.mark.asyncio
    async def test_url_auto_prefixes_https(self, tool_fns):
        mock_resp = _mock_response({})
        with patch(
            "aden_tools.tools.http_headers_scanner.http_headers_scanner.httpx.AsyncClient"
        ) as mock_client:
            mock_get = AsyncMock(return_value=mock_resp)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await tool_fns["http_headers_scan"](url="example.com")

        # Should not error; auto-prefixes https://
        assert "error" not in result
