"""Tests for DNS Security Scanner tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.dns_security_scanner import register_tools


@pytest.fixture
def dns_tools(mcp: FastMCP):
    """Register DNS security tools and return tool functions."""
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def scan_fn(dns_tools):
    return dns_tools["dns_security_scan"]


# ---------------------------------------------------------------------------
# Input Validation & Cleaning
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Test domain input cleaning and validation."""

    def test_strips_https_prefix(self, scan_fn):
        with patch(
            "aden_tools.tools.dns_security_scanner.dns_security_scanner._DNS_AVAILABLE", True
        ):
            with patch(
                "aden_tools.tools.dns_security_scanner.dns_security_scanner.dns.resolver.Resolver"
            ) as MockResolver:
                import dns.resolver

                mock = MagicMock()
                mock.resolve.side_effect = dns.resolver.NXDOMAIN()
                mock.timeout = 10
                mock.lifetime = 10
                MockResolver.return_value = mock

                result = scan_fn("https://example.com")
                assert result["domain"] == "example.com"

    def test_strips_http_prefix(self, scan_fn):
        with patch(
            "aden_tools.tools.dns_security_scanner.dns_security_scanner._DNS_AVAILABLE", True
        ):
            with patch(
                "aden_tools.tools.dns_security_scanner.dns_security_scanner.dns.resolver.Resolver"
            ) as MockResolver:
                import dns.resolver

                mock = MagicMock()
                mock.resolve.side_effect = dns.resolver.NXDOMAIN()
                mock.timeout = 10
                mock.lifetime = 10
                MockResolver.return_value = mock

                result = scan_fn("http://example.com")
                assert result["domain"] == "example.com"

    def test_strips_trailing_slash(self, scan_fn):
        with patch(
            "aden_tools.tools.dns_security_scanner.dns_security_scanner._DNS_AVAILABLE", True
        ):
            with patch(
                "aden_tools.tools.dns_security_scanner.dns_security_scanner.dns.resolver.Resolver"
            ) as MockResolver:
                import dns.resolver

                mock = MagicMock()
                mock.resolve.side_effect = dns.resolver.NXDOMAIN()
                mock.timeout = 10
                mock.lifetime = 10
                MockResolver.return_value = mock

                result = scan_fn("example.com/")
                assert result["domain"] == "example.com"

    def test_strips_path(self, scan_fn):
        with patch(
            "aden_tools.tools.dns_security_scanner.dns_security_scanner._DNS_AVAILABLE", True
        ):
            with patch(
                "aden_tools.tools.dns_security_scanner.dns_security_scanner.dns.resolver.Resolver"
            ) as MockResolver:
                import dns.resolver

                mock = MagicMock()
                mock.resolve.side_effect = dns.resolver.NXDOMAIN()
                mock.timeout = 10
                mock.lifetime = 10
                MockResolver.return_value = mock

                result = scan_fn("example.com/path/to/page")
                assert result["domain"] == "example.com"

    def test_strips_port(self, scan_fn):
        with patch(
            "aden_tools.tools.dns_security_scanner.dns_security_scanner._DNS_AVAILABLE", True
        ):
            with patch(
                "aden_tools.tools.dns_security_scanner.dns_security_scanner.dns.resolver.Resolver"
            ) as MockResolver:
                import dns.resolver

                mock = MagicMock()
                mock.resolve.side_effect = dns.resolver.NXDOMAIN()
                mock.timeout = 10
                mock.lifetime = 10
                MockResolver.return_value = mock

                result = scan_fn("example.com:8080")
                assert result["domain"] == "example.com"


# ---------------------------------------------------------------------------
# DNS Library Availability
# ---------------------------------------------------------------------------


class TestDnsAvailability:
    """Test behavior when dnspython is not installed."""

    def test_dns_not_available(self, scan_fn):
        with patch(
            "aden_tools.tools.dns_security_scanner.dns_security_scanner._DNS_AVAILABLE", False
        ):
            result = scan_fn("example.com")
            assert "error" in result
            assert "dnspython" in result["error"]


# ---------------------------------------------------------------------------
# SPF Record Checks
# ---------------------------------------------------------------------------


class TestSpfChecks:
    """Test SPF record detection and policy analysis."""

    def test_spf_hardfail_detected(self, scan_fn):
        with patch(
            "aden_tools.tools.dns_security_scanner.dns_security_scanner._DNS_AVAILABLE", True
        ):
            with patch(
                "aden_tools.tools.dns_security_scanner.dns_security_scanner.dns.resolver.Resolver"
            ) as MockResolver:
                mock = MagicMock()
                mock_rdata = MagicMock()
                mock_rdata.to_text.return_value = '"v=spf1 include:_spf.google.com -all"'
                mock.resolve.return_value = [mock_rdata]
                mock.timeout = 10
                mock.lifetime = 10
                MockResolver.return_value = mock

                result = scan_fn("example.com")
                assert result["spf"]["present"] is True
                assert result["spf"]["policy"] == "hardfail"
                assert result["grade_input"]["spf_strict"] is True

    def test_spf_softfail_detected(self, scan_fn):
        with patch(
            "aden_tools.tools.dns_security_scanner.dns_security_scanner._DNS_AVAILABLE", True
        ):
            with patch(
                "aden_tools.tools.dns_security_scanner.dns_security_scanner.dns.resolver.Resolver"
            ) as MockResolver:
                mock = MagicMock()
                mock_rdata = MagicMock()
                mock_rdata.to_text.return_value = '"v=spf1 include:_spf.google.com ~all"'
                mock.resolve.return_value = [mock_rdata]
                mock.timeout = 10
                mock.lifetime = 10
                MockResolver.return_value = mock

                result = scan_fn("example.com")
                assert result["spf"]["present"] is True
                assert result["spf"]["policy"] == "softfail"
                assert result["grade_input"]["spf_strict"] is False

    def test_spf_pass_all_dangerous(self, scan_fn):
        with patch(
            "aden_tools.tools.dns_security_scanner.dns_security_scanner._DNS_AVAILABLE", True
        ):
            with patch(
                "aden_tools.tools.dns_security_scanner.dns_security_scanner.dns.resolver.Resolver"
            ) as MockResolver:
                mock = MagicMock()
                mock_rdata = MagicMock()
                mock_rdata.to_text.return_value = '"v=spf1 +all"'
                mock.resolve.return_value = [mock_rdata]
                mock.timeout = 10
                mock.lifetime = 10
                MockResolver.return_value = mock

                result = scan_fn("example.com")
                assert result["spf"]["policy"] == "pass_all"
                assert len(result["spf"]["issues"]) > 0


# ---------------------------------------------------------------------------
# DMARC Record Checks
# ---------------------------------------------------------------------------


class TestDmarcChecks:
    """Test DMARC record detection and policy analysis."""

    def test_dmarc_reject_policy(self, scan_fn):
        with patch(
            "aden_tools.tools.dns_security_scanner.dns_security_scanner._DNS_AVAILABLE", True
        ):
            with patch(
                "aden_tools.tools.dns_security_scanner.dns_security_scanner.dns.resolver.Resolver"
            ) as MockResolver:
                mock = MagicMock()

                def mock_resolve(domain, record_type):
                    import dns.resolver

                    if record_type == "TXT" and "_dmarc" in domain:
                        rdata = MagicMock()
                        rdata.to_text.return_value = '"v=DMARC1; p=reject"'
                        return [rdata]
                    raise dns.resolver.NXDOMAIN()

                mock.resolve = mock_resolve
                mock.timeout = 10
                mock.lifetime = 10
                MockResolver.return_value = mock

                result = scan_fn("example.com")
                assert result["dmarc"]["present"] is True
                assert result["dmarc"]["policy"] == "reject"
                assert result["grade_input"]["dmarc_enforcing"] is True

    def test_dmarc_none_policy(self, scan_fn):
        with patch(
            "aden_tools.tools.dns_security_scanner.dns_security_scanner._DNS_AVAILABLE", True
        ):
            with patch(
                "aden_tools.tools.dns_security_scanner.dns_security_scanner.dns.resolver.Resolver"
            ) as MockResolver:
                mock = MagicMock()

                def mock_resolve(domain, record_type):
                    if record_type == "TXT" and "_dmarc" in domain:
                        rdata = MagicMock()
                        rdata.to_text.return_value = '"v=DMARC1; p=none"'
                        return [rdata]
                    import dns.resolver

                    raise dns.resolver.NXDOMAIN()

                mock.resolve = mock_resolve
                mock.timeout = 10
                mock.lifetime = 10
                MockResolver.return_value = mock

                result = scan_fn("example.com")
                assert result["dmarc"]["policy"] == "none"
                assert result["grade_input"]["dmarc_enforcing"] is False


# ---------------------------------------------------------------------------
# Grade Input
# ---------------------------------------------------------------------------


class TestGradeInput:
    """Test grade_input dict is properly constructed."""

    def test_grade_input_keys_present(self, scan_fn):
        with patch(
            "aden_tools.tools.dns_security_scanner.dns_security_scanner._DNS_AVAILABLE", True
        ):
            with patch(
                "aden_tools.tools.dns_security_scanner.dns_security_scanner.dns.resolver.Resolver"
            ) as MockResolver:
                mock = MagicMock()
                import dns.resolver

                mock.resolve.side_effect = dns.resolver.NXDOMAIN()
                mock.timeout = 10
                mock.lifetime = 10
                MockResolver.return_value = mock

                result = scan_fn("example.com")
                assert "grade_input" in result
                grade = result["grade_input"]
                assert "spf_present" in grade
                assert "spf_strict" in grade
                assert "dmarc_present" in grade
                assert "dmarc_enforcing" in grade
                assert "dkim_found" in grade
                assert "dnssec_enabled" in grade
                assert "zone_transfer_blocked" in grade
