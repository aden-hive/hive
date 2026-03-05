"""Tests for tech_stack_detector - website technology fingerprinting."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.tech_stack_detector.tech_stack_detector import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


def _make_response(
    status_code=200,
    headers=None,
    text="<html></html>",
    cookies=None,
    url="https://example.com",
):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = MagicMock()
    resp.headers.get = lambda key, default=None: (headers or {}).get(key, default)
    # Support dict-style iteration for _analyze_cookies
    resp.headers.__iter__ = lambda self: iter(headers or {})
    resp.headers.__contains__ = lambda self, key: key in (headers or {})
    resp.text = text
    resp.cookies = MagicMock()
    resp.cookies.__iter__ = lambda self: iter(cookies or [])
    resp.url = url
    return resp


class TestTechStackConnectErrors:
    @pytest.mark.asyncio
    async def test_connect_error_returns_error(self, tool_fns):
        import httpx

        with patch("aden_tools.tools.tech_stack_detector.tech_stack_detector.httpx") as mock_httpx:
            mock_httpx.ConnectError = httpx.ConnectError
            mock_httpx.TimeoutException = httpx.TimeoutException
            mock_httpx.HTTPError = httpx.HTTPError
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("refused")
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tool_fns["tech_stack_detect"](url="https://example.com")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self, tool_fns):
        import httpx

        with patch("aden_tools.tools.tech_stack_detector.tech_stack_detector.httpx") as mock_httpx:
            mock_httpx.ConnectError = httpx.ConnectError
            mock_httpx.TimeoutException = httpx.TimeoutException
            mock_httpx.HTTPError = httpx.HTTPError
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("timed out")
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tool_fns["tech_stack_detect"](url="https://example.com")
        assert "error" in result


class TestTechStackSuccessful:
    @pytest.mark.asyncio
    async def test_returns_grade_input(self, tool_fns):
        import httpx

        resp = _make_response(headers={"server": "nginx/1.18"})
        probe_resp = MagicMock()
        probe_resp.status_code = 404

        with patch("aden_tools.tools.tech_stack_detector.tech_stack_detector.httpx") as mock_httpx:
            mock_httpx.ConnectError = httpx.ConnectError
            mock_httpx.TimeoutException = httpx.TimeoutException
            mock_httpx.HTTPError = httpx.HTTPError
            mock_client = AsyncMock()
            mock_client.get.side_effect = [resp] + [probe_resp] * 50
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tool_fns["tech_stack_detect"](url="https://example.com")

        assert "grade_input" in result
        assert "server_version_hidden" in result["grade_input"]

    @pytest.mark.asyncio
    async def test_auto_prefixes_https(self, tool_fns):
        import httpx

        resp = _make_response()
        probe_resp = MagicMock()
        probe_resp.status_code = 404

        with patch("aden_tools.tools.tech_stack_detector.tech_stack_detector.httpx") as mock_httpx:
            mock_httpx.ConnectError = httpx.ConnectError
            mock_httpx.TimeoutException = httpx.TimeoutException
            mock_httpx.HTTPError = httpx.HTTPError
            mock_client = AsyncMock()
            mock_client.get.side_effect = [resp] + [probe_resp] * 50
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tool_fns["tech_stack_detect"](url="example.com")

        # Should succeed (auto-prefixed to https://)
        assert "error" not in result
