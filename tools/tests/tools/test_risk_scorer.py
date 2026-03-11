"""Tests for Risk Scorer tool."""

from __future__ import annotations

import json

import pytest
from fastmcp import FastMCP

from aden_tools.tools.risk_scorer import register_tools
from aden_tools.tools.risk_scorer.risk_scorer import (
    SSL_CHECKS,
    _parse_json,
    _score_category,
    _score_to_grade,
)


@pytest.fixture
def risk_tools(mcp: FastMCP):
    """Register risk scorer tools and return tool functions."""
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def score_fn(risk_tools):
    return risk_tools["risk_score"]


# ---------------------------------------------------------------------------
# Helper Function Tests
# ---------------------------------------------------------------------------


class TestScoreToGrade:
    """Test _score_to_grade helper."""

    def test_grade_a(self):
        assert _score_to_grade(95) == "A"
        assert _score_to_grade(90) == "A"

    def test_grade_b(self):
        assert _score_to_grade(85) == "B"
        assert _score_to_grade(75) == "B"

    def test_grade_c(self):
        assert _score_to_grade(70) == "C"
        assert _score_to_grade(60) == "C"

    def test_grade_d(self):
        assert _score_to_grade(55) == "D"
        assert _score_to_grade(40) == "D"

    def test_grade_f(self):
        assert _score_to_grade(39) == "F"
        assert _score_to_grade(0) == "F"


class TestParseJson:
    """Test _parse_json helper."""

    def test_valid_json(self):
        result = _parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_invalid_json(self):
        result = _parse_json("not json")
        assert result is None

    def test_empty_string(self):
        result = _parse_json("")
        assert result is None

    def test_whitespace_only(self):
        result = _parse_json("   ")
        assert result is None

    def test_non_dict_json(self):
        result = _parse_json("[1, 2, 3]")
        assert result is None


class TestScoreCategory:
    """Test _score_category helper."""

    def test_perfect_ssl_score(self):
        grade_input = {
            "tls_version_ok": True,
            "cert_valid": True,
            "cert_expiring_soon": False,  # inverted - False is good
            "strong_cipher": True,
            "self_signed": False,  # inverted - False is good
        }
        score, findings = _score_category(grade_input, SSL_CHECKS)
        assert score == 100
        assert len(findings) == 0

    def test_failing_ssl_score(self):
        grade_input = {
            "tls_version_ok": False,
            "cert_valid": False,
            "cert_expiring_soon": True,  # inverted - True is bad
            "strong_cipher": False,
            "self_signed": True,  # inverted - True is bad
        }
        score, findings = _score_category(grade_input, SSL_CHECKS)
        assert score == 0
        assert len(findings) == 5

    def test_missing_values_half_credit(self):
        grade_input = {}  # All values missing
        score, findings = _score_category(grade_input, SSL_CHECKS)
        # Should get half credit for missing values
        assert 45 <= score <= 55


# ---------------------------------------------------------------------------
# Full Scoring Flow
# ---------------------------------------------------------------------------


class TestFullScoring:
    """Test full risk scoring."""

    def test_empty_inputs_returns_zero(self, score_fn):
        result = score_fn()
        assert result["overall_score"] == 0
        assert result["overall_grade"] == "F"

    def test_all_categories_skipped(self, score_fn):
        result = score_fn()
        for cat in result["categories"].values():
            assert cat["skipped"] is True

    def test_ssl_results_only(self, score_fn):
        ssl_data = {
            "grade_input": {
                "tls_version_ok": True,
                "cert_valid": True,
                "cert_expiring_soon": False,
                "strong_cipher": True,
                "self_signed": False,
            }
        }
        result = score_fn(ssl_results=json.dumps(ssl_data))
        assert result["categories"]["ssl_tls"]["score"] == 100
        assert result["categories"]["ssl_tls"]["grade"] == "A"
        assert result["categories"]["ssl_tls"]["skipped"] is False

    def test_headers_results_only(self, score_fn):
        headers_data = {
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
        result = score_fn(headers_results=json.dumps(headers_data))
        assert result["categories"]["http_headers"]["score"] == 100
        assert result["categories"]["http_headers"]["grade"] == "A"

    def test_combined_results(self, score_fn):
        ssl_data = {
            "grade_input": {
                "tls_version_ok": True,
                "cert_valid": True,
                "cert_expiring_soon": False,
                "strong_cipher": True,
                "self_signed": False,
            }
        }
        headers_data = {
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
        result = score_fn(
            ssl_results=json.dumps(ssl_data),
            headers_results=json.dumps(headers_data),
        )
        # Both categories have perfect scores
        assert result["categories"]["ssl_tls"]["score"] == 100
        assert result["categories"]["http_headers"]["score"] == 100
        # Overall should be 100 (weighted average of two 100s)
        assert result["overall_score"] == 100
        assert result["overall_grade"] == "A"


# ---------------------------------------------------------------------------
# Top Risks
# ---------------------------------------------------------------------------


class TestTopRisks:
    """Test top_risks list generation."""

    def test_top_risks_generated(self, score_fn):
        ssl_data = {
            "grade_input": {
                "tls_version_ok": False,  # Failing
                "cert_valid": True,
                "cert_expiring_soon": False,
                "strong_cipher": False,  # Failing
                "self_signed": False,
            }
        }
        result = score_fn(ssl_results=json.dumps(ssl_data))
        assert len(result["top_risks"]) > 0
        # Should mention TLS version and cipher issues
        risks_text = " ".join(result["top_risks"])
        assert "TLS" in risks_text or "cipher" in risks_text.lower()

    def test_top_risks_limited_to_10(self, score_fn):
        # Create data with many failures
        ssl_data = {
            "grade_input": {
                "tls_version_ok": False,
                "cert_valid": False,
                "cert_expiring_soon": True,
                "strong_cipher": False,
                "self_signed": True,
            }
        }
        headers_data = {
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
        dns_data = {
            "grade_input": {
                "spf_present": False,
                "spf_strict": False,
                "dmarc_present": False,
                "dmarc_enforcing": False,
                "dkim_found": False,
                "dnssec_enabled": False,
                "zone_transfer_blocked": False,
            }
        }
        result = score_fn(
            ssl_results=json.dumps(ssl_data),
            headers_results=json.dumps(headers_data),
            dns_results=json.dumps(dns_data),
        )
        # Should be capped at 10
        assert len(result["top_risks"]) <= 10


# ---------------------------------------------------------------------------
# Grade Scale
# ---------------------------------------------------------------------------


class TestGradeScale:
    """Test grade_scale is included in output."""

    def test_grade_scale_present(self, score_fn):
        result = score_fn()
        assert "grade_scale" in result
        assert "A" in result["grade_scale"]
        assert "B" in result["grade_scale"]
        assert "C" in result["grade_scale"]
        assert "D" in result["grade_scale"]
        assert "F" in result["grade_scale"]


# ---------------------------------------------------------------------------
# Category Weights
# ---------------------------------------------------------------------------


class TestCategoryWeights:
    """Test category weights are applied correctly."""

    def test_weights_included_in_output(self, score_fn):
        ssl_data = {"grade_input": {"tls_version_ok": True}}
        result = score_fn(ssl_results=json.dumps(ssl_data))
        assert result["categories"]["ssl_tls"]["weight"] == 0.20


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_json_ignored(self, score_fn):
        result = score_fn(ssl_results="not valid json")
        assert result["categories"]["ssl_tls"]["skipped"] is True

    def test_missing_grade_input_key(self, score_fn):
        # JSON without grade_input - should use the dict itself
        data = {"tls_version_ok": True}
        result = score_fn(ssl_results=json.dumps(data))
        # Should not error
        assert "overall_score" in result
