"""Tests for VirusTotal Tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.virustotal_tool import register_tools


@pytest.fixture
def vt_tools(mcp: FastMCP):
    """Register VirusTotal tools and return tool functions."""
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def scan_ip_fn(vt_tools):
    return vt_tools["vt_scan_ip"]


@pytest.fixture
def scan_domain_fn(vt_tools):
    return vt_tools["vt_scan_domain"]


@pytest.fixture
def scan_hash_fn(vt_tools):
    return vt_tools["vt_scan_hash"]


# ---------------------------------------------------------------------------
# Missing Credentials
# ---------------------------------------------------------------------------


class TestMissingCredentials:
    """Test behavior when API key is not configured."""

    def test_scan_ip_no_key(self, scan_ip_fn):
        with patch.dict("os.environ", {}, clear=True):
            result = scan_ip_fn("8.8.8.8")
            assert "error" in result
            assert "API key" in result["error"]

    def test_scan_domain_no_key(self, scan_domain_fn):
        with patch.dict("os.environ", {}, clear=True):
            result = scan_domain_fn("example.com")
            assert "error" in result
            assert "API key" in result["error"]

    def test_scan_hash_no_key(self, scan_hash_fn):
        with patch.dict("os.environ", {}, clear=True):
            result = scan_hash_fn("d41d8cd98f00b204e9800998ecf8427e")
            assert "error" in result
            assert "API key" in result["error"]


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Test input validation for all three tools."""

    def test_invalid_ip(self, scan_ip_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            result = scan_ip_fn("not-an-ip")
            assert "error" in result
            assert "Invalid IP" in result["error"]

    def test_invalid_ip_octet_range(self, scan_ip_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            result = scan_ip_fn("999.999.999.999")
            assert "error" in result
            assert "Invalid IP" in result["error"]

    def test_invalid_domain(self, scan_domain_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            result = scan_domain_fn("not a domain!")
            assert "error" in result
            assert "Invalid domain" in result["error"]

    def test_invalid_hash_length(self, scan_hash_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            result = scan_hash_fn("abc123")
            assert "error" in result
            assert "Invalid hash" in result["error"]

    def test_invalid_hash_chars(self, scan_hash_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            result = scan_hash_fn("g" * 32)  # 'g' is not valid hex
            assert "error" in result

    def test_domain_strips_protocol(self, scan_domain_fn):
        """Domain should be cleaned before validation."""
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            with patch("aden_tools.tools.virustotal_tool.virustotal_tool.httpx.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "data": {
                        "attributes": {
                            "reputation": 0,
                            "last_analysis_stats": {
                                "malicious": 0,
                                "suspicious": 0,
                                "undetected": 0,
                                "harmless": 70,
                                "timeout": 0,
                            },
                        }
                    }
                }
                mock_get.return_value = mock_resp

                result = scan_domain_fn("https://example.com/path")
                assert "error" not in result
                assert result["domain"] == "example.com"

    def test_hash_whitespace_stripped(self, scan_hash_fn):
        """Hash input should be stripped of whitespace."""
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            with patch("aden_tools.tools.virustotal_tool.virustotal_tool.httpx.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "data": {
                        "attributes": {
                            "md5": "d41d8cd98f00b204e9800998ecf8427e",
                            "sha1": "",
                            "sha256": "",
                            "last_analysis_stats": {
                                "malicious": 0,
                                "suspicious": 0,
                                "undetected": 0,
                                "harmless": 0,
                                "timeout": 0,
                            },
                        }
                    }
                }
                mock_get.return_value = mock_resp

                result = scan_hash_fn("  d41d8cd98f00b204e9800998ecf8427e  ")
                assert "error" not in result


# ---------------------------------------------------------------------------
# API Responses - IP Scan
# ---------------------------------------------------------------------------


class TestScanIp:
    """Test IP scanning with mocked API responses."""

    def test_successful_ip_scan(self, scan_ip_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            with patch("aden_tools.tools.virustotal_tool.virustotal_tool.httpx.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "data": {
                        "attributes": {
                            "as_owner": "GOOGLE",
                            "country": "US",
                            "reputation": 0,
                            "network": "8.8.8.0/24",
                            "last_analysis_stats": {
                                "malicious": 0,
                                "suspicious": 0,
                                "undetected": 5,
                                "harmless": 65,
                                "timeout": 0,
                            },
                            "last_analysis_date": 1710000000,
                        }
                    }
                }
                mock_get.return_value = mock_resp

                result = scan_ip_fn("8.8.8.8")
                assert result["ip"] == "8.8.8.8"
                assert result["as_owner"] == "GOOGLE"
                assert result["country"] == "US"
                assert result["analysis_stats"]["malicious"] == 0
                assert result["analysis_stats"]["harmless"] == 65

    def test_ip_401_unauthorized(self, scan_ip_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "bad-key"}):
            with patch("aden_tools.tools.virustotal_tool.virustotal_tool.httpx.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 401
                mock_get.return_value = mock_resp

                result = scan_ip_fn("8.8.8.8")
                assert "error" in result
                assert "Invalid" in result["error"]

    def test_ip_429_rate_limit(self, scan_ip_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            with patch("aden_tools.tools.virustotal_tool.virustotal_tool.httpx.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 429
                mock_get.return_value = mock_resp

                result = scan_ip_fn("8.8.8.8")
                assert "error" in result
                assert "rate limit" in result["error"]


# ---------------------------------------------------------------------------
# API Responses - Domain Scan
# ---------------------------------------------------------------------------


class TestScanDomain:
    """Test domain scanning with mocked API responses."""

    def test_successful_domain_scan(self, scan_domain_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            with patch("aden_tools.tools.virustotal_tool.virustotal_tool.httpx.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "data": {
                        "attributes": {
                            "reputation": 0,
                            "registrar": "MarkMonitor Inc.",
                            "creation_date": 868060800,
                            "categories": {"Webroot": "Internet Services"},
                            "last_analysis_stats": {
                                "malicious": 0,
                                "suspicious": 0,
                                "undetected": 10,
                                "harmless": 60,
                                "timeout": 0,
                            },
                            "last_analysis_date": 1710000000,
                            "last_dns_records": [{"type": "A", "value": "93.184.216.34"}],
                        }
                    }
                }
                mock_get.return_value = mock_resp

                result = scan_domain_fn("example.com")
                assert result["domain"] == "example.com"
                assert result["registrar"] == "MarkMonitor Inc."
                assert result["analysis_stats"]["harmless"] == 60
                assert len(result["last_dns_records"]) == 1

    def test_domain_not_found(self, scan_domain_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            with patch("aden_tools.tools.virustotal_tool.virustotal_tool.httpx.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 404
                mock_get.return_value = mock_resp

                result = scan_domain_fn("nonexistent-domain-xyz.com")
                assert "error" in result
                assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# API Responses - Hash Scan
# ---------------------------------------------------------------------------


class TestScanHash:
    """Test file hash scanning with mocked API responses."""

    def test_successful_md5_scan(self, scan_hash_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            with patch("aden_tools.tools.virustotal_tool.virustotal_tool.httpx.get") as mock_get:
                test_md5 = "d41d8cd98f00b204e9800998ecf8427e"
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "data": {
                        "attributes": {
                            "md5": test_md5,
                            "sha1": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            "sha256": (
                                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                            ),
                            "type_description": "Text",
                            "size": 0,
                            "names": ["empty.txt"],
                            "reputation": 0,
                            "last_analysis_stats": {
                                "malicious": 0,
                                "suspicious": 0,
                                "undetected": 15,
                                "harmless": 55,
                                "timeout": 0,
                            },
                            "last_analysis_date": 1710000000,
                            "tags": ["text"],
                        }
                    }
                }
                mock_get.return_value = mock_resp

                result = scan_hash_fn(test_md5)
                assert result["md5"] == test_md5
                assert result["file_type"] == "Text"
                assert result["analysis_stats"]["malicious"] == 0

    def test_successful_sha256_scan(self, scan_hash_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            with patch("aden_tools.tools.virustotal_tool.virustotal_tool.httpx.get") as mock_get:
                test_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "data": {
                        "attributes": {
                            "md5": "d41d8cd98f00b204e9800998ecf8427e",
                            "sha1": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            "sha256": test_sha256,
                            "type_description": "Text",
                            "size": 0,
                            "reputation": 0,
                            "last_analysis_stats": {
                                "malicious": 0,
                                "suspicious": 0,
                                "undetected": 0,
                                "harmless": 70,
                                "timeout": 0,
                            },
                        }
                    }
                }
                mock_get.return_value = mock_resp

                result = scan_hash_fn(test_sha256)
                assert result["sha256"] == test_sha256

    def test_malicious_file_detected(self, scan_hash_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "test-key"}):
            with patch("aden_tools.tools.virustotal_tool.virustotal_tool.httpx.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "data": {
                        "attributes": {
                            "md5": "a" * 32,
                            "sha1": "b" * 40,
                            "sha256": "c" * 64,
                            "type_description": "Win32 EXE",
                            "size": 1048576,
                            "names": ["malware.exe", "trojan.exe"],
                            "reputation": -100,
                            "last_analysis_stats": {
                                "malicious": 45,
                                "suspicious": 5,
                                "undetected": 10,
                                "harmless": 10,
                                "timeout": 0,
                            },
                            "tags": ["peexe", "trojan"],
                        }
                    }
                }
                mock_get.return_value = mock_resp

                result = scan_hash_fn("a" * 32)
                assert result["analysis_stats"]["malicious"] == 45
                assert result["reputation"] == -100
                assert "malware.exe" in result["names"]


# ---------------------------------------------------------------------------
# Credential Resolution
# ---------------------------------------------------------------------------


class TestCredentialResolution:
    """Test credential resolution via environment and adapter."""

    def test_resolves_from_env(self, scan_ip_fn):
        with patch.dict("os.environ", {"VIRUSTOTAL_API_KEY": "env-key"}):
            with patch("aden_tools.tools.virustotal_tool.virustotal_tool.httpx.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"data": {"attributes": {"last_analysis_stats": {}}}}
                mock_get.return_value = mock_resp

                result = scan_ip_fn("1.1.1.1")
                assert "error" not in result
                mock_get.assert_called_once()
                call_headers = mock_get.call_args.kwargs.get(
                    "headers", mock_get.call_args[1].get("headers", {})
                )
                assert call_headers["x-apikey"] == "env-key"

    def test_resolves_from_credentials_adapter(self, mcp):
        mock_creds = MagicMock()
        mock_creds.get.return_value = "adapter-key"

        register_tools(mcp, credentials=mock_creds)
        tools = mcp._tool_manager._tools
        scan_ip_fn = tools["vt_scan_ip"].fn

        with patch.dict("os.environ", {}, clear=True):
            with patch("aden_tools.tools.virustotal_tool.virustotal_tool.httpx.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"data": {"attributes": {"last_analysis_stats": {}}}}
                mock_get.return_value = mock_resp

                result = scan_ip_fn("1.1.1.1")
                assert "error" not in result
                call_headers = mock_get.call_args.kwargs.get(
                    "headers", mock_get.call_args[1].get("headers", {})
                )
                assert call_headers["x-apikey"] == "adapter-key"
