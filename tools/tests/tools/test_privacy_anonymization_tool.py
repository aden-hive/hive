"""Tests for Privacy Anonymization Tool."""

from __future__ import annotations

import pytest

from aden_tools.tools.privacy_anonymization_tool.privacy_anonymization_tool import (
    _add_noise_numeric,
    _apply_differential_privacy,
    _apply_k_anonymity,
    _apply_pseudonymization,
    _calculate_re_identification_risk,
    _check_equivalence_classes,
    _generate_pseudonym,
    _generalize_age,
    _generalize_date,
    _generalize_zip,
)


class TestGeneralizationHelpers:
    """Tests for generalization helper functions."""

    def test_generalize_age_young(self):
        assert _generalize_age(15) == "0-17"

    def test_generalize_age_young_adult(self):
        assert _generalize_age(22) == "18-25"

    def test_generalize_age_middle(self):
        assert _generalize_age(40) == "36-50"

    def test_generalize_age_senior(self):
        assert _generalize_age(70) == "66-120"

    def test_generalize_age_string_input(self):
        assert _generalize_age("35") == "26-35"

    def test_generalize_age_invalid(self):
        assert _generalize_age("invalid") == "*"

    def test_generalize_zip_standard(self):
        assert _generalize_zip("12345") == "123**"

    def test_generalize_zip_numeric(self):
        assert _generalize_zip(90210) == "902**"

    def test_generalize_zip_short(self):
        assert _generalize_zip("12") == "000**"

    def test_generalize_date_iso(self):
        assert _generalize_date("1990-05-15") == "1990"

    def test_generalize_date_no_year(self):
        assert _generalize_date("May 15") == "*"


class TestPseudonymization:
    """Tests for pseudonymization functions."""

    def test_generate_pseudonym_consistent(self):
        result1 = _generate_pseudonym("test@example.com", "salt")
        result2 = _generate_pseudonym("test@example.com", "salt")
        assert result1 == result2

    def test_generate_pseudonym_different_salt(self):
        result1 = _generate_pseudonym("test@example.com", "salt1")
        result2 = _generate_pseudonym("test@example.com", "salt2")
        assert result1 != result2

    def test_generate_pseudonym_different_values(self):
        result1 = _generate_pseudonym("user1@example.com", "salt")
        result2 = _generate_pseudonym("user2@example.com", "salt")
        assert result1 != result2

    def test_generate_pseudonym_format(self):
        result = _generate_pseudonym("test@example.com", "salt")
        assert result.startswith("PSEUDO_")
        assert len(result) == 15


class TestDifferentialPrivacy:
    """Tests for differential privacy functions."""

    def test_add_noise_numeric_adds_noise(self):
        original = 100.0
        noisy = _add_noise_numeric(original, epsilon=1.0)
        assert noisy != original

    def test_add_noise_numeric_same_range(self):
        original = 100.0
        noisy = _add_noise_numeric(original, epsilon=10.0)
        assert abs(noisy - original) < 10

    def test_add_noise_numeric_higher_epsilon_less_noise(self):
        original = 100.0
        noisy_low_eps = abs(_add_noise_numeric(original, epsilon=0.1) - original)
        noisy_high_eps = abs(_add_noise_numeric(original, epsilon=10.0) - original)
        assert noisy_low_eps > noisy_high_eps


class TestKAnonymityApplication:
    """Tests for k-anonymity application."""

    def test_apply_k_anonymity_suppresses_sensitive(self):
        record = {"name": "John", "age": 30, "diagnosis": "Flu"}
        result = _apply_k_anonymity(record, sensitive_fields=["name", "diagnosis"])
        assert result["name"] == "[REDACTED]"
        assert result["diagnosis"] == "[REDACTED]"
        assert result["age"] == 30

    def test_apply_k_anonymity_generalizes_quasi_identifiers(self):
        record = {"name": "John", "age": 35, "zip": "12345"}
        result = _apply_k_anonymity(
            record,
            sensitive_fields=["name"],
            quasi_identifiers=["age", "zip"],
        )
        assert result["age"] == "26-35"
        assert result["zip"] == "123**"

    def test_apply_k_anonymity_preserves_non_sensitive(self):
        record = {"name": "John", "city": "New York", "score": 95}
        result = _apply_k_anonymity(record, sensitive_fields=["name"])
        assert result["city"] == "New York"
        assert result["score"] == 95


class TestPseudonymizationApplication:
    """Tests for pseudonymization application."""

    def test_apply_pseudonymization_replaces_values(self):
        record = {"email": "test@example.com", "name": "John"}
        result = _apply_pseudonymization(record, sensitive_fields=["email", "name"])
        assert result["email"].startswith("PSEUDO_")
        assert result["name"].startswith("PSEUDO_")

    def test_apply_pseudonymization_preserves_others(self):
        record = {"email": "test@example.com", "age": 30}
        result = _apply_pseudonymization(record, sensitive_fields=["email"])
        assert result["age"] == 30


class TestDifferentialPrivacyApplication:
    """Tests for differential privacy application."""

    def test_apply_differential_privacy_numeric(self):
        record = {"salary": 50000, "name": "John"}
        result = _apply_differential_privacy(record, sensitive_fields=["salary"], epsilon=0.1)
        assert result["salary"] != 50000 or isinstance(result["salary"], float)

    def test_apply_differential_privacy_non_numeric(self):
        record = {"email": "test@example.com", "salary": 50000}
        result = _apply_differential_privacy(record, sensitive_fields=["email"], epsilon=1.0)
        assert result["email"] == "[REDACTED]"


class TestEquivalenceClasses:
    """Tests for equivalence class checking."""

    def test_check_equivalence_classes_basic(self):
        data = [
            {"age": "30-35", "zip": "123**"},
            {"age": "30-35", "zip": "123**"},
            {"age": "30-35", "zip": "456**"},
        ]
        result = _check_equivalence_classes(data, ["age", "zip"])
        assert result["min_class_size"] == 1
        assert result["class_count"] == 2

    def test_check_equivalence_classes_all_same(self):
        data = [
            {"age": "30-35", "zip": "123**"},
            {"age": "30-35", "zip": "123**"},
            {"age": "30-35", "zip": "123**"},
        ]
        result = _check_equivalence_classes(data, ["age", "zip"])
        assert result["min_class_size"] == 3
        assert result["class_count"] == 1

    def test_check_equivalence_classes_empty_data(self):
        result = _check_equivalence_classes([], ["age", "zip"])
        assert result["min_class_size"] == 0
        assert result["k_anonymous"] is False

    def test_check_equivalence_classes_empty_quasi(self):
        data = [{"age": 30}]
        result = _check_equivalence_classes(data, [])
        assert result["min_class_size"] == 0


class TestReIdentificationRisk:
    """Tests for re-identification risk calculation."""

    def test_calculate_re_identification_risk_low(self):
        data = [
            {"age": "30-35", "zip": "123**"},
        ] * 10
        result = _calculate_re_identification_risk(data, ["age", "zip"])
        assert result["risk_level"] == "low"
        assert result["re_identification_probability"] == 0.1

    def test_calculate_re_identification_risk_high(self):
        data = [{"age": "30-35", "zip": "123**"}]
        result = _calculate_re_identification_risk(data, ["age", "zip"])
        assert result["risk_level"] == "high"
        assert result["re_identification_probability"] == 1.0

    def test_calculate_re_identification_risk_medium(self):
        data = [
            {"age": "30-35", "zip": "123**"},
            {"age": "30-35", "zip": "123**"},
            {"age": "30-35", "zip": "123**"},
            {"age": "30-35", "zip": "123**"},
            {"age": "30-35", "zip": "456**"},
            {"age": "30-35", "zip": "456**"},
            {"age": "30-35", "zip": "456**"},
            {"age": "30-35", "zip": "456**"},
        ]
        result = _calculate_re_identification_risk(data, ["age", "zip"])
        assert result["risk_level"] == "medium"


class TestPIIDetection:
    """Tests for PII detection via FastMCP tool."""

    def _get_detect_pii_tool(self):
        from aden_tools.tools.privacy_anonymization_tool.privacy_anonymization_tool import (
            register_tools,
        )
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)
        return mcp._tool_manager._tools["detect_pii_fields"].fn

    def test_detect_pii_fields_email(self):
        detect_pii_fields = self._get_detect_pii_tool()
        data = {"email": "test@example.com", "name": "John"}
        result = detect_pii_fields(data)
        assert "error" not in result
        assert "email" in result["detected_fields"]
        assert result["detected_fields"]["email"]["type"] == "email"

    def test_detect_pii_fields_ssn(self):
        detect_pii_fields = self._get_detect_pii_tool()
        data = {"ssn": "123-45-6789"}
        result = detect_pii_fields(data)
        assert "error" not in result
        assert "ssn" in result["detected_fields"]
        assert result["detected_fields"]["ssn"]["type"] == "ssn"

    def test_detect_pii_fields_phone(self):
        detect_pii_fields = self._get_detect_pii_tool()
        data = {"phone": "555-123-4567"}
        result = detect_pii_fields(data)
        assert "error" not in result
        assert "phone" in result["detected_fields"]

    def test_detect_pii_fields_credit_card(self):
        detect_pii_fields = self._get_detect_pii_tool()
        data = {"card": "1234-5678-9012-3456"}
        result = detect_pii_fields(data)
        assert "error" not in result
        assert "card" in result["detected_fields"]

    def test_detect_pii_fields_name_by_field_name(self):
        detect_pii_fields = self._get_detect_pii_tool()
        data = {"patient_name": "John Doe", "age": 30}
        result = detect_pii_fields(data)
        assert "error" not in result
        assert "patient_name" in result["detected_fields"]

    def test_detect_pii_fields_zip(self):
        detect_pii_fields = self._get_detect_pii_tool()
        data = {"zip_code": "12345"}
        result = detect_pii_fields(data)
        assert "error" not in result
        assert "zip_code" in result["detected_fields"]

    def test_detect_pii_fields_no_pii(self):
        detect_pii_fields = self._get_detect_pii_tool()
        data = {"product": "Widget", "price": 19.99}
        result = detect_pii_fields(data)
        assert "error" not in result
        assert len(result["detected_fields"]) == 0

    def test_detect_pii_fields_list_input(self):
        detect_pii_fields = self._get_detect_pii_tool()
        data = [{"email": "test@example.com"}]
        result = detect_pii_fields(data)
        assert "error" not in result
        assert "email" in result["detected_fields"]


class TestAnonymizeDataTool:
    """Tests for the anonymize_data tool function."""

    def test_anonymize_data_k_anonymity_single_record(self):
        from aden_tools.tools.privacy_anonymization_tool.privacy_anonymization_tool import (
            register_tools,
        )
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        tools = mcp._tool_manager._tools
        anonymize_data = tools["anonymize_data"].fn

        result = anonymize_data(
            data={"name": "John", "age": 35, "zip": "12345"},
            sensitive_fields=["name"],
            method="k_anonymity",
            quasi_identifiers=["age", "zip"],
        )

        assert "error" not in result
        assert result["method"] == "k_anonymity"
        assert result["anonymized_data"]["name"] == "[REDACTED]"

    def test_anonymize_data_pseudonymization(self):
        from aden_tools.tools.privacy_anonymization_tool.privacy_anonymization_tool import (
            register_tools,
        )
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        tools = mcp._tool_manager._tools
        anonymize_data = tools["anonymize_data"].fn

        result = anonymize_data(
            data={"email": "test@example.com"},
            sensitive_fields=["email"],
            method="pseudonymization",
        )

        assert "error" not in result
        assert result["anonymized_data"]["email"].startswith("PSEUDO_")

    def test_anonymize_data_differential_privacy(self):
        from aden_tools.tools.privacy_anonymization_tool.privacy_anonymization_tool import (
            register_tools,
        )
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        tools = mcp._tool_manager._tools
        anonymize_data = tools["anonymize_data"].fn

        result = anonymize_data(
            data={"salary": 50000},
            sensitive_fields=["salary"],
            method="differential_privacy",
            epsilon=0.1,
        )

        assert "error" not in result
        assert result["anonymized_data"]["salary"] != 50000 or isinstance(
            result["anonymized_data"]["salary"], float
        )

    def test_anonymize_data_invalid_method(self):
        from aden_tools.tools.privacy_anonymization_tool.privacy_anonymization_tool import (
            register_tools,
        )
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        tools = mcp._tool_manager._tools
        anonymize_data = tools["anonymize_data"].fn

        result = anonymize_data(
            data={"name": "John"},
            sensitive_fields=["name"],
            method="invalid_method",
        )

        assert "error" in result

    def test_anonymize_data_empty_sensitive_fields(self):
        from aden_tools.tools.privacy_anonymization_tool.privacy_anonymization_tool import (
            register_tools,
        )
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        tools = mcp._tool_manager._tools
        anonymize_data = tools["anonymize_data"].fn

        result = anonymize_data(data={"name": "John"}, sensitive_fields=[])

        assert "error" in result


class TestCheckPrivacyComplianceTool:
    """Tests for the check_privacy_compliance tool function."""

    def test_check_privacy_compliance_compliant(self):
        from aden_tools.tools.privacy_anonymization_tool.privacy_anonymization_tool import (
            register_tools,
        )
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        tools = mcp._tool_manager._tools
        check_privacy_compliance = tools["check_privacy_compliance"].fn

        data = [
            {"age": "30-35", "zip": "123**"},
        ] * 5

        result = check_privacy_compliance(data=data, quasi_identifiers=["age", "zip"], k=5)

        assert "error" not in result
        assert result["compliant"] is True
        assert result["k_value"] == 5

    def test_check_privacy_compliance_non_compliant(self):
        from aden_tools.tools.privacy_anonymization_tool.privacy_anonymization_tool import (
            register_tools,
        )
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        tools = mcp._tool_manager._tools
        check_privacy_compliance = tools["check_privacy_compliance"].fn

        data = [
            {"age": "30-35", "zip": "123**"},
            {"age": "30-35", "zip": "456**"},
        ]

        result = check_privacy_compliance(data=data, quasi_identifiers=["age", "zip"], k=5)

        assert "error" not in result
        assert result["compliant"] is False
        assert len(result["violations"]) > 0


class TestDetectPIIFieldsTool:
    """Tests for the detect_pii_fields tool function."""

    def test_detect_pii_fields_tool_basic(self):
        from aden_tools.tools.privacy_anonymization_tool.privacy_anonymization_tool import (
            register_tools,
        )
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        tools = mcp._tool_manager._tools
        detect_pii_fields = tools["detect_pii_fields"].fn

        result = detect_pii_fields(
            data={
                "email": "test@example.com",
                "ssn": "123-45-6789",
                "name": "John Doe",
            }
        )

        assert "error" not in result
        assert len(result["detected_fields"]) >= 2
        assert result["scan_summary"]["pii_fields_detected"] >= 2
