"""
Tests for IP Info tool.

Covers:
- ipinfo_get_ip_details: success, validation, error handling
- ipinfo_get_my_ip: success, error handling
- ipinfo_bulk_lookup: success, validation, max limit, error handling
- Tool registration
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.ipinfo_tool.ipinfo_tool import register_tools

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_IPINFO_RESPONSE = {
    "ip": "8.8.8.8",
    "city": "Mountain View",
    "region": "California",
    "country": "US",
    "loc": "37.4056,-122.0775",
    "org": "AS15169 Google LLC",
    "timezone": "America/Los_Angeles",
    "hostname": "dns.google",
    "postal": "94043",
}


def _make_mcp() -> FastMCP:
    mcp = FastMCP("test-ipinfo")
    register_tools(mcp)
    return mcp


def _get_tool(mcp: FastMCP, name: str):
    """Return the raw callable for a registered tool by name."""
    return mcp._tool_manager._tools[name].fn


def _mock_response(status_code=200, json_data=None):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.return_value = MOCK_IPINFO_RESPONSE
    resp.text = str(json_data) if json_data else ""
    return resp


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_all_tools_registered(self):
        mcp = _make_mcp()
        registered = set(mcp._tool_manager._tools.keys())
        assert "ipinfo_get_ip_details" in registered
        assert "ipinfo_get_my_ip" in registered
        assert "ipinfo_bulk_lookup" in registered


# ---------------------------------------------------------------------------
# ipinfo_get_ip_details
# ---------------------------------------------------------------------------


class TestGetIPDetails:
    def setup_method(self):
        self.mcp = _make_mcp()
        self.get_details = _get_tool(self.mcp, "ipinfo_get_ip_details")

    def test_empty_ip_returns_error(self):
        result = self.get_details(ip="")
        assert "error" in result
        assert "required" in result["error"]

    def test_whitespace_ip_returns_error(self):
        result = self.get_details(ip="   ")
        assert "error" in result
        assert "required" in result["error"]

    def test_invalid_ip_returns_error(self):
        result = self.get_details(ip="not-an-ip")
        assert "error" in result
        assert "Invalid IP address" in result["error"]

    def test_valid_ipv4_success(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.return_value = _mock_response()
            result = self.get_details(ip="8.8.8.8")
            assert result["ip"] == "8.8.8.8"
            assert result["city"] == "Mountain View"
            assert result["country"] == "US"
            assert result["org"] == "AS15169 Google LLC"
            assert result["timezone"] == "America/Los_Angeles"

    def test_valid_ipv6_success(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.return_value = _mock_response(
                json_data={**MOCK_IPINFO_RESPONSE, "ip": "2001:4860:4860::8888"}
            )
            result = self.get_details(ip="2001:4860:4860::8888")
            assert result["ip"] == "2001:4860:4860::8888"

    def test_strips_whitespace(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.return_value = _mock_response()
            result = self.get_details(ip="  8.8.8.8  ")
            assert result["ip"] == "8.8.8.8"

    def test_401_error(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.return_value = _mock_response(status_code=401)
            result = self.get_details(ip="8.8.8.8")
            assert "error" in result
            assert "Invalid or expired" in result["error"]

    def test_429_rate_limit(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.return_value = _mock_response(status_code=429)
            result = self.get_details(ip="8.8.8.8")
            assert "error" in result
            assert "Rate limit" in result["error"]

    def test_timeout_error(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.side_effect = httpx.TimeoutException("timeout")
            result = self.get_details(ip="8.8.8.8")
            assert "error" in result
            assert "timed out" in result["error"]

    def test_network_error(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.side_effect = httpx.ConnectError("connection refused")
            result = self.get_details(ip="8.8.8.8")
            assert "error" in result
            assert "Network error" in result["error"]

    def test_includes_token_when_provided(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get, patch.dict(
            "os.environ", {"IPINFO_TOKEN": "test-token-123"}
        ):
            mock_get.return_value = _mock_response()
            self.get_details(ip="8.8.8.8")
            call_url = mock_get.call_args[0][0]
            assert "token=test-token-123" in call_url


# ---------------------------------------------------------------------------
# ipinfo_get_my_ip
# ---------------------------------------------------------------------------


class TestGetMyIP:
    def setup_method(self):
        self.mcp = _make_mcp()
        self.get_my_ip = _get_tool(self.mcp, "ipinfo_get_my_ip")

    def test_success(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.return_value = _mock_response()
            result = self.get_my_ip()
            assert result["ip"] == "8.8.8.8"
            assert result["city"] == "Mountain View"

    def test_timeout_error(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.side_effect = httpx.TimeoutException("timeout")
            result = self.get_my_ip()
            assert "error" in result
            assert "timed out" in result["error"]

    def test_network_error(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.side_effect = httpx.ConnectError("connection refused")
            result = self.get_my_ip()
            assert "error" in result
            assert "Network error" in result["error"]

    def test_401_error(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.return_value = _mock_response(status_code=401)
            result = self.get_my_ip()
            assert "error" in result
            assert "Invalid or expired" in result["error"]


# ---------------------------------------------------------------------------
# ipinfo_bulk_lookup
# ---------------------------------------------------------------------------


class TestBulkLookup:
    def setup_method(self):
        self.mcp = _make_mcp()
        self.bulk_lookup = _get_tool(self.mcp, "ipinfo_bulk_lookup")

    def test_empty_input(self):
        result = self.bulk_lookup(ips="")
        assert "error" in result

    def test_invalid_ip_in_list(self):
        result = self.bulk_lookup(ips="8.8.8.8,not-an-ip")
        assert "error" in result
        assert "Invalid" in result["error"]

    def test_exceeds_max_limit(self):
        ips = ",".join([f"10.0.0.{i % 255}" for i in range(101)])
        result = self.bulk_lookup(ips=ips)
        assert "error" in result
        assert "Maximum 100" in result["error"]

    def test_success_multiple_ips(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.return_value = _mock_response()
            result = self.bulk_lookup(ips="8.8.8.8,1.1.1.1")
            assert result["count"] == 2
            assert result["success_count"] == 2
            assert result["error_count"] == 0
            assert len(result["results"]) == 2

    def test_partial_failure(self):
        def side_effect(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "8.8.8.8" in url:
                return _mock_response()
            return _mock_response(status_code=401)

        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get", side_effect=side_effect
        ):
            result = self.bulk_lookup(ips="8.8.8.8,1.1.1.1")
            assert result["count"] == 2
            assert result["success_count"] == 1
            assert result["error_count"] == 1

    def test_single_ip(self):
        with patch(
            "aden_tools.tools.ipinfo_tool.ipinfo_tool.httpx.get"
        ) as mock_get:
            mock_get.return_value = _mock_response()
            result = self.bulk_lookup(ips="8.8.8.8")
            assert result["count"] == 1
            assert result["success_count"] == 1
