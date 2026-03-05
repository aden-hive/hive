"""Tests for subdomain_enumerator - Certificate Transparency log subdomain discovery."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.subdomain_enumerator.subdomain_enumerator import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


def _make_crt_response(entries, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = entries
    return resp


class TestSubdomainEnumeratorErrors:
    @pytest.mark.asyncio
    async def test_crtsh_non_200_returns_error(self, tool_fns):
        import httpx

        with patch(
            "aden_tools.tools.subdomain_enumerator.subdomain_enumerator.httpx"
        ) as mock_httpx:
            mock_httpx.TimeoutException = httpx.TimeoutException
            mock_client = AsyncMock()
            mock_client.get.return_value = _make_crt_response([], status_code=503)
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tool_fns["subdomain_enumerate"](domain="example.com")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self, tool_fns):
        import httpx

        with patch(
            "aden_tools.tools.subdomain_enumerator.subdomain_enumerator.httpx"
        ) as mock_httpx:
            mock_httpx.TimeoutException = httpx.TimeoutException
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("timed out")
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tool_fns["subdomain_enumerate"](domain="example.com")
        assert "error" in result


class TestSubdomainEnumeratorSuccessful:
    @pytest.mark.asyncio
    async def test_returns_subdomains(self, tool_fns):
        import httpx

        entries = [
            {"name_value": "www.example.com"},
            {"name_value": "mail.example.com"},
            {"name_value": "*.example.com"},  # wildcard should be filtered
        ]
        with patch(
            "aden_tools.tools.subdomain_enumerator.subdomain_enumerator.httpx"
        ) as mock_httpx:
            mock_httpx.TimeoutException = httpx.TimeoutException
            mock_client = AsyncMock()
            mock_client.get.return_value = _make_crt_response(entries)
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tool_fns["subdomain_enumerate"](domain="example.com")

        assert "error" not in result
        assert "www.example.com" in result["subdomains"]
        assert "mail.example.com" in result["subdomains"]
        # Wildcards must be excluded
        assert not any(s.startswith("*.") for s in result["subdomains"])

    @pytest.mark.asyncio
    async def test_grade_input_present(self, tool_fns):
        import httpx

        entries = [{"name_value": "www.example.com"}]
        with patch(
            "aden_tools.tools.subdomain_enumerator.subdomain_enumerator.httpx"
        ) as mock_httpx:
            mock_httpx.TimeoutException = httpx.TimeoutException
            mock_client = AsyncMock()
            mock_client.get.return_value = _make_crt_response(entries)
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tool_fns["subdomain_enumerate"](domain="example.com")

        assert "grade_input" in result
        assert "no_dev_staging_exposed" in result["grade_input"]
        assert "no_admin_exposed" in result["grade_input"]

    @pytest.mark.asyncio
    async def test_interesting_subdomain_flagged(self, tool_fns):
        import httpx

        entries = [
            {"name_value": "staging.example.com"},
            {"name_value": "admin.example.com"},
        ]
        with patch(
            "aden_tools.tools.subdomain_enumerator.subdomain_enumerator.httpx"
        ) as mock_httpx:
            mock_httpx.TimeoutException = httpx.TimeoutException
            mock_client = AsyncMock()
            mock_client.get.return_value = _make_crt_response(entries)
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tool_fns["subdomain_enumerate"](domain="example.com")

        assert result["grade_input"]["no_dev_staging_exposed"] is False
        assert result["grade_input"]["no_admin_exposed"] is False

    @pytest.mark.asyncio
    async def test_domain_strips_protocol(self, tool_fns):
        import httpx

        entries = [{"name_value": "www.example.com"}]
        with patch(
            "aden_tools.tools.subdomain_enumerator.subdomain_enumerator.httpx"
        ) as mock_httpx:
            mock_httpx.TimeoutException = httpx.TimeoutException
            mock_client = AsyncMock()
            mock_client.get.return_value = _make_crt_response(entries)
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tool_fns["subdomain_enumerate"](domain="https://example.com")

        assert result["domain"] == "example.com"
