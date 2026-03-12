"""Tests for Subdomain Enumerator tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.subdomain_enumerator import register_tools


@pytest.fixture
def subdomain_tools(mcp: FastMCP):
    """Register subdomain enumeration tools and return tool functions."""
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def enumerate_fn(subdomain_tools):
    return subdomain_tools["subdomain_enumerate"]


def _mock_crtsh_response(subdomains: list[str], status_code: int = 200) -> MagicMock:
    """Create a mock crt.sh response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = [{"name_value": sub} for sub in subdomains]
    return resp


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Test domain input cleaning."""

    @pytest.mark.asyncio
    async def test_strips_https_prefix(self, enumerate_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response([])
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("https://example.com")
            assert result["domain"] == "example.com"

    @pytest.mark.asyncio
    async def test_strips_http_prefix(self, enumerate_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response([])
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("http://example.com")
            assert result["domain"] == "example.com"

    @pytest.mark.asyncio
    async def test_strips_path(self, enumerate_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response([])
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("example.com/path")
            assert result["domain"] == "example.com"

    @pytest.mark.asyncio
    async def test_max_results_clamped(self, enumerate_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response([])
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            # max_results should be clamped to 200
            result = await enumerate_fn("example.com", max_results=500)
            # Result should not error
            assert "error" not in result


# ---------------------------------------------------------------------------
# Connection Errors
# ---------------------------------------------------------------------------


class TestConnectionErrors:
    """Test error handling for crt.sh failures."""

    @pytest.mark.asyncio
    async def test_timeout_error(self, enumerate_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("timeout")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("example.com")
            assert "error" in result
            assert "timed out" in result["error"]

    @pytest.mark.asyncio
    async def test_http_error(self, enumerate_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response([], status_code=500)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("example.com")
            assert "error" in result
            assert "500" in result["error"]


# ---------------------------------------------------------------------------
# Subdomain Discovery
# ---------------------------------------------------------------------------


class TestSubdomainDiscovery:
    """Test subdomain extraction from CT logs."""

    @pytest.mark.asyncio
    async def test_subdomains_extracted(self, enumerate_fn):
        subdomains = [
            "www.example.com",
            "api.example.com",
            "mail.example.com",
        ]
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response(subdomains)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("example.com")
            assert result["total_found"] == 3
            assert "www.example.com" in result["subdomains"]
            assert "api.example.com" in result["subdomains"]

    @pytest.mark.asyncio
    async def test_wildcards_filtered(self, enumerate_fn):
        subdomains = [
            "*.example.com",
            "www.example.com",
            "*.api.example.com",
        ]
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response(subdomains)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("example.com")
            # Wildcards should be filtered out
            assert "*.example.com" not in result["subdomains"]
            assert "www.example.com" in result["subdomains"]

    @pytest.mark.asyncio
    async def test_duplicates_removed(self, enumerate_fn):
        subdomains = [
            "www.example.com",
            "www.example.com",
            "www.example.com",
        ]
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response(subdomains)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("example.com")
            assert result["total_found"] == 1


# ---------------------------------------------------------------------------
# Interesting Subdomain Detection
# ---------------------------------------------------------------------------


class TestInterestingSubdomains:
    """Test detection of security-relevant subdomains."""

    @pytest.mark.asyncio
    async def test_staging_flagged(self, enumerate_fn):
        subdomains = ["staging.example.com", "www.example.com"]
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response(subdomains)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("example.com")
            assert len(result["interesting"]) > 0
            interesting_subs = [i["subdomain"] for i in result["interesting"]]
            assert "staging.example.com" in interesting_subs

    @pytest.mark.asyncio
    async def test_admin_flagged(self, enumerate_fn):
        subdomains = ["admin.example.com", "www.example.com"]
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response(subdomains)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("example.com")
            interesting_subs = [i["subdomain"] for i in result["interesting"]]
            assert "admin.example.com" in interesting_subs

    @pytest.mark.asyncio
    async def test_dev_flagged(self, enumerate_fn):
        subdomains = ["dev.example.com", "www.example.com"]
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response(subdomains)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("example.com")
            interesting_subs = [i["subdomain"] for i in result["interesting"]]
            assert "dev.example.com" in interesting_subs


# ---------------------------------------------------------------------------
# Grade Input
# ---------------------------------------------------------------------------


class TestGradeInput:
    """Test grade_input dict is properly constructed."""

    @pytest.mark.asyncio
    async def test_grade_input_keys_present(self, enumerate_fn):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response([])
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("example.com")
            assert "grade_input" in result
            grade = result["grade_input"]
            assert "no_dev_staging_exposed" in grade
            assert "no_admin_exposed" in grade
            assert "reasonable_surface_area" in grade

    @pytest.mark.asyncio
    async def test_no_dev_staging_true_when_clean(self, enumerate_fn):
        subdomains = ["www.example.com", "api.example.com"]
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response(subdomains)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("example.com")
            assert result["grade_input"]["no_dev_staging_exposed"] is True

    @pytest.mark.asyncio
    async def test_reasonable_surface_area(self, enumerate_fn):
        # Less than 50 subdomains = reasonable
        subdomains = [f"sub{i}.example.com" for i in range(30)]
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_crtsh_response(subdomains)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            MockClient.return_value = mock_client

            result = await enumerate_fn("example.com")
            assert result["grade_input"]["reasonable_surface_area"] is True
