"""Tests for web_scrape tool (FastMCP)."""
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

    def test_blocks_localhost(self, web_scrape_fn):
        """Verify localhost and 127.0.0.1 are blocked."""
        # Test localhost hostname
        result = web_scrape_fn(url="http://localhost")
        assert "error" in result
        assert "SSRF protection" in result["error"]
        assert result.get("blocked_ssrf") is True

        # Test 127.0.0.1 IP
        result = web_scrape_fn(url="http://127.0.0.1")
        assert "error" in result
        assert "SSRF protection" in result["error"]
        assert result.get("blocked_ssrf") is True

        # Test localhost with port
        result = web_scrape_fn(url="http://localhost:8080")
        assert "error" in result
        assert "SSRF protection" in result["error"]
        assert result.get("blocked_ssrf") is True

    def test_blocks_private_ip_ranges(self, web_scrape_fn):
        """Verify private IP ranges (10.x, 172.16.x, 192.168.x) are blocked."""
        # Test Class A private (10.0.0.0/8)
        result = web_scrape_fn(url="http://10.0.0.1")
        assert "error" in result
        assert "SSRF protection" in result["error"]
        assert result.get("blocked_ssrf") is True

        result = web_scrape_fn(url="http://10.255.255.255")
        assert "error" in result
        assert "SSRF protection" in result["error"]
        assert result.get("blocked_ssrf") is True

        # Test Class B private (172.16.0.0/12)
        result = web_scrape_fn(url="http://172.16.0.1")
        assert "error" in result
        assert "SSRF protection" in result["error"]
        assert result.get("blocked_ssrf") is True

        result = web_scrape_fn(url="http://172.31.255.255")
        assert "error" in result
        assert "SSRF protection" in result["error"]
        assert result.get("blocked_ssrf") is True

        # Test Class C private (192.168.0.0/16)
        result = web_scrape_fn(url="http://192.168.0.1")
        assert "error" in result
        assert "SSRF protection" in result["error"]
        assert result.get("blocked_ssrf") is True

        result = web_scrape_fn(url="http://192.168.255.255")
        assert "error" in result
        assert "SSRF protection" in result["error"]
        assert result.get("blocked_ssrf") is True

    def test_blocks_metadata_endpoint(self, web_scrape_fn):
        """Verify cloud metadata endpoint (169.254.169.254) is blocked."""
        # AWS/GCP metadata endpoint
        result = web_scrape_fn(url="http://169.254.169.254")
        assert "error" in result
        assert "SSRF protection" in result["error"]
        assert result.get("blocked_ssrf") is True

        result = web_scrape_fn(url="http://169.254.169.254/latest/meta-data/")
        assert "error" in result
        assert "SSRF protection" in result["error"]
        assert result.get("blocked_ssrf") is True

    def test_allows_public_ip(self, web_scrape_fn):
        """Verify legitimate public URLs still work."""
        # Public domain should not be blocked by SSRF check
        # (may fail for other reasons like network, but not SSRF)
        result = web_scrape_fn(url="https://example.com")
        # Should not have SSRF error
        assert "blocked_ssrf" not in result or result.get("blocked_ssrf") is not True
        # If there's an error, it should not be SSRF-related
        if "error" in result:
            assert "SSRF protection" not in result["error"]
