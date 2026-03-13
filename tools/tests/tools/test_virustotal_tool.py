"""
Tests for VirusTotal threat intelligence tool.

Covers:
- _VirusTotalClient methods (scan_ip, scan_domain, scan_hash)
- Error handling (invalid API key, rate limiting, not found)
- Input validation (IPv4, domain, hash format)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 3 MCP tool functions
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.virustotal_tool.virustotal_tool import (
    _VirusTotalClient,
    register_tools,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp():
    return FastMCP("test-server")


@pytest.fixture
def vt_client():
    return _VirusTotalClient("test-api-key")


# ---------------------------------------------------------------------------
# Sample API responses
# ---------------------------------------------------------------------------

SAMPLE_IP_RESPONSE = {
    "data": {
        "id": "8.8.8.8",
        "type": "ip_address",
        "attributes": {
            "reputation": 74,
            "country": "US",
            "as_owner": "GOOGLE",
            "network": "8.8.8.0/24",
            "last_analysis_stats": {
                "malicious": 0,
                "suspicious": 0,
                "harmless": 80,
                "undetected": 10,
            },
            "total_votes": {"malicious": 0, "harmless": 25},
        },
    }
}

SAMPLE_DOMAIN_RESPONSE = {
    "data": {
        "id": "google.com",
        "type": "domain",
        "attributes": {
            "reputation": 211,
            "registrar": "MarkMonitor Inc.",
            "creation_date": 874296000,
            "last_dns_records": [
                {"type": "A", "value": "142.250.80.46"},
                {"type": "AAAA", "value": "2607:f8b0:4004:800::200e"},
            ],
            "categories": {"Forcepoint ThreatSeeker": "search engines and portals"},
            "last_analysis_stats": {
                "malicious": 0,
                "suspicious": 0,
                "harmless": 89,
                "undetected": 4,
            },
            "total_votes": {"malicious": 0, "harmless": 50},
        },
    }
}

SAMPLE_FILE_RESPONSE = {
    "data": {
        "id": "abc123",
        "type": "file",
        "attributes": {
            "sha256": "a" * 64,
            "sha1": "b" * 40,
            "md5": "c" * 32,
            "type_description": "PE32 executable",
            "size": 123456,
            "meaningful_name": "test.exe",
            "reputation": -50,
            "last_analysis_stats": {
                "malicious": 45,
                "suspicious": 3,
                "harmless": 10,
                "undetected": 15,
                "type-unsupported": 2,
            },
            "popular_threat_classification": {
                "suggested_threat_label": "trojan.generic",
            },
            "tags": ["peexe", "overlay", "signed"],
        },
    }
}


# ---------------------------------------------------------------------------
# _VirusTotalClient tests
# ---------------------------------------------------------------------------


class TestVirusTotalClient:
    """Tests for the _VirusTotalClient class."""

    @patch("aden_tools.tools.virustotal_tool.virustotal_tool.urlopen")
    def test_scan_ip_success(self, mock_urlopen, vt_client):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(SAMPLE_IP_RESPONSE).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = vt_client.scan_ip("8.8.8.8")

        assert result["ip"] == "8.8.8.8"
        assert result["reputation"] == 74
        assert result["country"] == "US"
        assert result["as_owner"] == "GOOGLE"
        assert result["analysis_stats"]["malicious"] == 0
        assert result["analysis_stats"]["harmless"] == 80

    @patch("aden_tools.tools.virustotal_tool.virustotal_tool.urlopen")
    def test_scan_domain_success(self, mock_urlopen, vt_client):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(SAMPLE_DOMAIN_RESPONSE).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = vt_client.scan_domain("google.com")

        assert result["domain"] == "google.com"
        assert result["reputation"] == 211
        assert result["registrar"] == "MarkMonitor Inc."
        assert len(result["last_dns_records"]) == 2
        assert result["analysis_stats"]["harmless"] == 89

    @patch("aden_tools.tools.virustotal_tool.virustotal_tool.urlopen")
    def test_scan_hash_success(self, mock_urlopen, vt_client):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(SAMPLE_FILE_RESPONSE).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = vt_client.scan_hash("c" * 32)

        assert result["md5"] == "c" * 32
        assert result["file_type"] == "PE32 executable"
        assert result["analysis_stats"]["malicious"] == 45
        assert result["reputation"] == -50
        assert "trojan.generic" in str(result["popular_threat_classification"])

    @patch("aden_tools.tools.virustotal_tool.virustotal_tool.urlopen")
    def test_http_401_returns_error(self, mock_urlopen, vt_client):
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            url="https://www.virustotal.com/api/v3/ip_addresses/1.1.1.1",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=MagicMock(read=lambda: b"Unauthorized"),
        )

        result = vt_client.scan_ip("1.1.1.1")
        assert "error" in result
        assert "Invalid API key" in result["error"]

    @patch("aden_tools.tools.virustotal_tool.virustotal_tool.urlopen")
    def test_http_429_returns_rate_limit_error(self, mock_urlopen, vt_client):
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            url="https://www.virustotal.com/api/v3/domains/test.com",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=MagicMock(read=lambda: b"Rate limit"),
        )

        result = vt_client.scan_domain("test.com")
        assert "error" in result
        assert "Rate limit" in result["error"]

    @patch("aden_tools.tools.virustotal_tool.virustotal_tool.urlopen")
    def test_http_404_returns_not_found(self, mock_urlopen, vt_client):
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            url="https://www.virustotal.com/api/v3/files/abc",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=MagicMock(read=lambda: b"Not found"),
        )

        result = vt_client.scan_hash("a" * 64)
        assert "error" in result
        assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Tests for input validation in MCP tool functions."""

    def test_invalid_ip_rejected(self, mcp):
        register_tools(mcp)
        tool = mcp._tool_manager._tools["vt_scan_ip"]
        # Call with invalid IP
        result = json.loads(tool.fn(ip="999.999.999.999"))
        assert "error" in result
        assert "Invalid IPv4" in result["error"]

    def test_invalid_domain_rejected(self, mcp):
        register_tools(mcp)
        tool = mcp._tool_manager._tools["vt_scan_domain"]
        result = json.loads(tool.fn(domain="not a domain!!"))
        assert "error" in result
        assert "Invalid domain" in result["error"]

    def test_invalid_hash_rejected(self, mcp):
        register_tools(mcp)
        tool = mcp._tool_manager._tools["vt_scan_hash"]
        result = json.loads(tool.fn(file_hash="xyz-not-a-hash"))
        assert "error" in result
        assert "Invalid hash" in result["error"]

    def test_valid_md5_accepted(self, mcp):
        register_tools(mcp)
        tool = mcp._tool_manager._tools["vt_scan_hash"]
        # Valid MD5 format but no API key
        result = json.loads(tool.fn(file_hash="d" * 32))
        # Should pass validation, fail on missing API key
        assert "VIRUSTOTAL_API_KEY" in result.get("error", "")

    def test_valid_sha1_accepted(self, mcp):
        register_tools(mcp)
        tool = mcp._tool_manager._tools["vt_scan_hash"]
        result = json.loads(tool.fn(file_hash="e" * 40))
        assert "VIRUSTOTAL_API_KEY" in result.get("error", "")

    def test_valid_sha256_accepted(self, mcp):
        register_tools(mcp)
        tool = mcp._tool_manager._tools["vt_scan_hash"]
        result = json.loads(tool.fn(file_hash="f" * 64))
        assert "VIRUSTOTAL_API_KEY" in result.get("error", "")


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Tests for MCP tool registration."""

    def test_all_three_tools_registered(self, mcp):
        register_tools(mcp)
        tools = list(mcp._tool_manager._tools.keys())
        assert "vt_scan_ip" in tools
        assert "vt_scan_domain" in tools
        assert "vt_scan_hash" in tools

    def test_tools_registered_with_credentials(self, mcp):
        from aden_tools.credentials import CredentialStoreAdapter

        creds = CredentialStoreAdapter.for_testing({"virustotal": "test-key"})
        register_tools(mcp, credentials=creds)
        tools = list(mcp._tool_manager._tools.keys())
        assert len(tools) == 3


# ---------------------------------------------------------------------------
# Credential resolution tests
# ---------------------------------------------------------------------------


class TestCredentialResolution:
    """Tests for credential retrieval."""

    def test_missing_credentials_returns_error(self, mcp):
        register_tools(mcp)
        tool = mcp._tool_manager._tools["vt_scan_ip"]
        result = json.loads(tool.fn(ip="8.8.8.8"))
        assert "error" in result
        assert "VIRUSTOTAL_API_KEY" in result["error"]

    @patch("aden_tools.tools.virustotal_tool.virustotal_tool.urlopen")
    def test_env_var_credential(self, mock_urlopen, mcp):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(SAMPLE_IP_RESPONSE).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        register_tools(mcp)
        tool = mcp._tool_manager._tools["vt_scan_ip"]

        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            result = json.loads(tool.fn(ip="8.8.8.8"))
        assert result["ip"] == "8.8.8.8"
        assert "error" not in result

    @patch("aden_tools.tools.virustotal_tool.virustotal_tool.urlopen")
    def test_credential_store_adapter(self, mock_urlopen, mcp):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(SAMPLE_DOMAIN_RESPONSE).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from aden_tools.credentials import CredentialStoreAdapter

        creds = CredentialStoreAdapter.for_testing({"virustotal": "test-key-from-store"})
        register_tools(mcp, credentials=creds)
        tool = mcp._tool_manager._tools["vt_scan_domain"]

        result = json.loads(tool.fn(domain="google.com"))
        assert result["domain"] == "google.com"
        assert "error" not in result
