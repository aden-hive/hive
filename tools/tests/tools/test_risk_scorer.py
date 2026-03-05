"""Tests for risk_scorer - weighted letter-grade risk scoring from scan results."""

import json

import pytest
from fastmcp import FastMCP

from aden_tools.tools.risk_scorer.risk_scorer import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestRiskScoreEmpty:
    def test_no_inputs_returns_zero(self, tool_fns):
        result = tool_fns["risk_score"]()
        assert result["overall_score"] == 0
        assert result["overall_grade"] == "F"

    def test_returns_grade_scale(self, tool_fns):
        result = tool_fns["risk_score"]()
        assert "grade_scale" in result
        assert "A" in result["grade_scale"]

    def test_all_categories_skipped(self, tool_fns):
        result = tool_fns["risk_score"]()
        for cat in result["categories"].values():
            assert cat["skipped"] is True


class TestRiskScoreGradeA:
    def test_perfect_ssl_score(self, tool_fns):
        ssl = json.dumps(
            {
                "grade_input": {
                    "tls_version_ok": True,
                    "cert_valid": True,
                    "cert_expiring_soon": False,
                    "strong_cipher": True,
                    "self_signed": False,
                }
            }
        )
        result = tool_fns["risk_score"](ssl_results=ssl)
        assert result["categories"]["ssl_tls"]["score"] == 100
        assert result["categories"]["ssl_tls"]["grade"] == "A"

    def test_perfect_headers_score(self, tool_fns):
        headers = json.dumps(
            {
                "grade_input": {
                    "hsts": True,
                    "csp": True,
                    "x_frame_options": True,
                    "x_content_type_options": True,
                    "referrer_policy": True,
                    "permissions_policy": True,
                    "no_leaky_headers": True,
                }
            }
        )
        result = tool_fns["risk_score"](headers_results=headers)
        assert result["categories"]["http_headers"]["score"] == 100
        assert result["categories"]["http_headers"]["grade"] == "A"


class TestRiskScoreGradeF:
    def test_all_ssl_failing(self, tool_fns):
        ssl = json.dumps(
            {
                "grade_input": {
                    "tls_version_ok": False,
                    "cert_valid": False,
                    "cert_expiring_soon": True,
                    "strong_cipher": False,
                    "self_signed": True,
                }
            }
        )
        result = tool_fns["risk_score"](ssl_results=ssl)
        assert result["categories"]["ssl_tls"]["score"] == 0
        assert result["categories"]["ssl_tls"]["grade"] == "F"

    def test_findings_reported(self, tool_fns):
        ssl = json.dumps(
            {
                "grade_input": {
                    "tls_version_ok": False,
                    "cert_valid": False,
                    "cert_expiring_soon": True,
                    "strong_cipher": False,
                    "self_signed": True,
                }
            }
        )
        result = tool_fns["risk_score"](ssl_results=ssl)
        assert len(result["top_risks"]) > 0


class TestRiskScoreMultiCategory:
    def test_overall_weighted_average(self, tool_fns):
        ssl = json.dumps(
            {
                "grade_input": {
                    "tls_version_ok": True,
                    "cert_valid": True,
                    "cert_expiring_soon": False,
                    "strong_cipher": True,
                    "self_signed": False,
                }
            }
        )
        dns = json.dumps(
            {
                "grade_input": {
                    "spf_present": True,
                    "spf_strict": True,
                    "dmarc_present": True,
                    "dmarc_enforcing": True,
                    "dkim_found": True,
                    "dnssec_enabled": True,
                    "zone_transfer_blocked": True,
                }
            }
        )
        result = tool_fns["risk_score"](ssl_results=ssl, dns_results=dns)
        assert result["overall_score"] == 100
        assert result["overall_grade"] == "A"

    def test_top_risks_capped_at_ten(self, tool_fns):
        # All categories failing
        bad_ssl = json.dumps(
            {
                "grade_input": {
                    "tls_version_ok": False,
                    "cert_valid": False,
                    "cert_expiring_soon": True,
                    "strong_cipher": False,
                    "self_signed": True,
                }
            }
        )
        bad_headers = json.dumps(
            {
                "grade_input": {
                    "hsts": False,
                    "csp": False,
                    "x_frame_options": False,
                    "x_content_type_options": False,
                    "referrer_policy": False,
                    "permissions_policy": False,
                    "no_leaky_headers": False,
                }
            }
        )
        result = tool_fns["risk_score"](ssl_results=bad_ssl, headers_results=bad_headers)
        assert len(result["top_risks"]) <= 10

    def test_invalid_json_input_skips_category(self, tool_fns):
        result = tool_fns["risk_score"](ssl_results="not-valid-json")
        assert result["categories"]["ssl_tls"]["skipped"] is True


class TestRiskScoreGradeInput:
    def test_grade_input_directly_in_root(self, tool_fns):
        # grade_input provided as root keys (not nested)
        ssl = json.dumps(
            {
                "tls_version_ok": True,
                "cert_valid": True,
                "cert_expiring_soon": False,
                "strong_cipher": True,
                "self_signed": False,
            }
        )
        result = tool_fns["risk_score"](ssl_results=ssl)
        assert result["categories"]["ssl_tls"]["score"] == 100
