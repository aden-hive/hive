"""Tests for dns_security_scanner - SPF, DMARC, DKIM, DNSSEC, zone transfer analysis."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP


@pytest.fixture
def tool_fns(mcp: FastMCP):
    # Ensure dnspython is treated as available
    dns_mock = MagicMock()
    dns_mock.resolver = MagicMock()
    dns_mock.exception = MagicMock()
    dns_mock.exception.DNSException = Exception
    dns_mock.resolver.NoAnswer = Exception
    dns_mock.resolver.NXDOMAIN = Exception

    modules = {
        "dns": dns_mock,
        "dns.resolver": dns_mock.resolver,
        "dns.exception": dns_mock.exception,
        "dns.name": MagicMock(),
        "dns.query": MagicMock(),
        "dns.rdatatype": MagicMock(),
        "dns.xfr": MagicMock(),
        "dns.zone": MagicMock(),
    }

    with patch.dict("sys.modules", modules):
        import importlib

        import aden_tools.tools.dns_security_scanner.dns_security_scanner as mod

        importlib.reload(mod)
        mod.register_tools(mcp)

    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


def _patch_helpers(
    tool_fn, spf=None, dmarc=None, dkim=None, dnssec=None, mx=None, caa=None, zone=None
):
    """Patch all dns helper functions via the tool function's __globals__ dict."""
    overrides = {}
    if spf is not None:
        overrides["_check_spf"] = lambda *a, **k: spf
    if dmarc is not None:
        overrides["_check_dmarc"] = lambda *a, **k: dmarc
    if dkim is not None:
        overrides["_check_dkim"] = lambda *a, **k: dkim
    if dnssec is not None:
        overrides["_check_dnssec"] = lambda *a, **k: dnssec
    if mx is not None:
        overrides["_check_mx"] = lambda *a, **k: mx
    if caa is not None:
        overrides["_check_caa"] = lambda *a, **k: caa
    if zone is not None:
        overrides["_check_zone_transfer"] = lambda *a, **k: zone
    return patch.dict(tool_fn.__globals__, overrides)


class TestDnsSecurityScanDnspythonMissing:
    def test_missing_dnspython_returns_error(self, mcp: FastMCP):
        """When dnspython is not installed, tool should return an error."""
        with patch.dict("sys.modules", {"dns": None, "dns.resolver": None}):
            import aden_tools.tools.dns_security_scanner.dns_security_scanner as mod

            original = mod._DNS_AVAILABLE
            mod._DNS_AVAILABLE = False
            mod.register_tools(mcp)
            tools = mcp._tool_manager._tools
            fn = tools["dns_security_scan"].fn
            result = fn(domain="example.com")
            mod._DNS_AVAILABLE = original

        assert "error" in result


class TestDnsSecurityScanResults:
    def test_returns_grade_input(self, tool_fns):
        """A completed scan must include grade_input keys."""
        with _patch_helpers(
            tool_fns["dns_security_scan"],
            spf={"present": True, "policy": "hardfail"},
            dmarc={"present": True, "policy": "reject"},
            dkim={"selectors_found": ["google"]},
            dnssec={"enabled": True, "issues": []},
            mx=["10 mail.example.com"],
            caa=[],
            zone={"vulnerable": False},
        ):
            result = tool_fns["dns_security_scan"](domain="example.com")

        assert "grade_input" in result
        assert result["grade_input"]["spf_present"] is True
        assert result["grade_input"]["dmarc_present"] is True
        assert result["grade_input"]["dkim_found"] is True
        assert result["grade_input"]["dnssec_enabled"] is True
        assert result["grade_input"]["zone_transfer_blocked"] is True

    def test_all_failing_dns_posture(self, tool_fns):
        with _patch_helpers(
            tool_fns["dns_security_scan"],
            spf={"present": False},
            dmarc={"present": False},
            dkim={"selectors_found": []},
            dnssec={"enabled": False, "issues": []},
            mx=[],
            caa=[],
            zone={"vulnerable": True, "nameserver": "ns1.example.com"},
        ):
            result = tool_fns["dns_security_scan"](domain="example.com")

        assert result["grade_input"]["spf_present"] is False
        assert result["grade_input"]["dkim_found"] is False
        assert result["grade_input"]["zone_transfer_blocked"] is False

    def test_domain_strips_protocol(self, tool_fns):
        with _patch_helpers(
            tool_fns["dns_security_scan"],
            spf={"present": False},
            dmarc={"present": False},
            dkim={"selectors_found": []},
            dnssec={"enabled": False, "issues": []},
            mx=[],
            caa=[],
            zone={"vulnerable": False},
        ):
            result = tool_fns["dns_security_scan"](domain="https://example.com")

        assert result["domain"] == "example.com"
