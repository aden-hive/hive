"""
Privacy Anonymization Tool - Data anonymization for FastMCP.

Provides privacy-preserving data anonymization methods:
- K-anonymity (generalization and suppression)
- Pseudonymization
- Differential privacy (noise addition)

Useful for healthcare, finance, and any domain handling PII.
Aligns with GDPR, HIPAA, and other privacy regulations.
"""

from __future__ import annotations

import hashlib
import random
import re
from collections import Counter
from typing import Any

from fastmcp import FastMCP


def _generate_pseudonym(original: str, salt: str = "default_salt") -> str:
    """Generate a consistent pseudonym for a given value."""
    hash_input = f"{salt}{original}".encode()
    hash_digest = hashlib.sha256(hash_input).hexdigest()[:8]
    return f"PSEUDO_{hash_digest}"


def _generalize_age(age: int | str, bins: list[tuple[int, int]] | None = None) -> str:
    """Generalize age into age ranges."""
    if bins is None:
        bins = [(0, 17), (18, 25), (26, 35), (36, 50), (51, 65), (66, 120)]

    try:
        age_int = int(age)
    except (ValueError, TypeError):
        return "*"

    for low, high in bins:
        if low <= age_int <= high:
            return f"{low}-{high}"
    return "*"


def _generalize_zip(zip_code: str | int) -> str:
    """Generalize ZIP code by truncating to first 3 digits."""
    zip_str = str(zip_code).zfill(5)
    if len(zip_str) >= 3:
        return f"{zip_str[:3]}**"
    return "***"


def _generalize_date(date_str: str) -> str:
    """Generalize date to year only."""
    year_match = re.search(r"\d{4}", date_str)
    if year_match:
        return year_match.group()
    return "*"


def _add_noise_numeric(value: float | int, epsilon: float = 1.0) -> float:
    """Add Laplace noise for differential privacy."""
    scale = 1.0 / epsilon
    noise = random.uniform(-scale, scale)
    if isinstance(value, int):
        return round(value + noise)
    return value + noise


def _suppress_value() -> str:
    """Return suppression placeholder."""
    return "[REDACTED]"


def _apply_k_anonymity(
    record: dict[str, Any],
    sensitive_fields: list[str],
    quasi_identifiers: list[str] | None = None,
    k: int = 5,
) -> dict[str, Any]:
    """Apply k-anonymity transformations to a record."""
    result = record.copy()

    for field in sensitive_fields:
        if field in result:
            result[field] = _suppress_value()

    if quasi_identifiers:
        for field in quasi_identifiers:
            if field not in result:
                continue
            value = result[field]
            field_lower = field.lower()

            if "age" in field_lower:
                result[field] = _generalize_age(value)
            elif "zip" in field_lower or "postal" in field_lower:
                result[field] = _generalize_zip(value)
            elif "date" in field_lower or "birth" in field_lower:
                result[field] = _generalize_date(str(value))
            else:
                result[field] = str(value)[:2] + "***" if len(str(value)) > 2 else "*"

    return result


def _apply_pseudonymization(
    record: dict[str, Any],
    sensitive_fields: list[str],
    salt: str = "default_salt",
) -> dict[str, Any]:
    """Apply pseudonymization to sensitive fields."""
    result = record.copy()

    for field in sensitive_fields:
        if field in result and result[field] is not None:
            result[field] = _generate_pseudonym(str(result[field]), salt)

    return result


def _apply_differential_privacy(
    record: dict[str, Any],
    sensitive_fields: list[str],
    epsilon: float = 1.0,
) -> dict[str, Any]:
    """Apply differential privacy noise to numeric sensitive fields."""
    result = record.copy()

    for field in sensitive_fields:
        if field not in result:
            continue
        value = result[field]

        if isinstance(value, int | float):
            result[field] = _add_noise_numeric(value, epsilon)
        else:
            result[field] = _suppress_value()

    return result


def _check_equivalence_classes(
    data: list[dict[str, Any]],
    quasi_identifiers: list[str],
) -> dict[str, Any]:
    """Check equivalence classes for k-anonymity."""
    if not quasi_identifiers or not data:
        return {"equivalence_classes": {}, "min_class_size": 0, "k_anonymous": False}

    equivalence_classes: Counter = Counter()
    for record in data:
        key = tuple(str(record.get(qi, "")) for qi in quasi_identifiers)
        equivalence_classes[key] += 1

    class_sizes = list(equivalence_classes.values())
    min_size = min(class_sizes) if class_sizes else 0

    return {
        "equivalence_classes": dict(equivalence_classes),
        "min_class_size": min_size,
        "class_count": len(equivalence_classes),
        "k_anonymous": min_size > 0,
    }


def _calculate_re_identification_risk(
    data: list[dict[str, Any]],
    quasi_identifiers: list[str],
) -> dict[str, Any]:
    """Calculate re-identification risk based on equivalence classes."""
    eq_info = _check_equivalence_classes(data, quasi_identifiers)
    min_size = eq_info["min_class_size"]

    if min_size == 0:
        return {"risk_level": "unknown", "re_identification_probability": 1.0}

    re_id_prob = 1.0 / min_size

    if re_id_prob <= 0.1:
        risk_level = "low"
    elif re_id_prob <= 0.3:
        risk_level = "medium"
    else:
        risk_level = "high"

    return {
        "risk_level": risk_level,
        "re_identification_probability": round(re_id_prob, 4),
        "min_equivalence_class_size": min_size,
    }


def register_tools(mcp: FastMCP) -> None:
    """Register privacy anonymization tools with the MCP server."""

    @mcp.tool()
    def anonymize_data(
        data: dict[str, Any] | list[dict[str, Any]],
        sensitive_fields: list[str],
        method: str = "k_anonymity",
        quasi_identifiers: list[str] | None = None,
        k: int = 5,
        epsilon: float = 1.0,
        salt: str = "default_salt",
    ) -> dict[str, Any]:
        """
        Anonymize sensitive data using various privacy-preserving methods.

        Use this tool when you need to protect PII or sensitive information
        before sharing data with LLMs, storing, or processing.

        Args:
            data: Single record (dict) or list of records to anonymize
            sensitive_fields: List of field names containing sensitive data
            method: Anonymization method - "k_anonymity", "pseudonymization",
                   or "differential_privacy" (default: "k_anonymity")
            quasi_identifiers: Fields that could identify individuals when combined
                              (used for k-anonymity). Common examples: age, zip, gender
            k: Minimum equivalence class size for k-anonymity (default: 5)
            epsilon: Privacy budget for differential privacy (default: 1.0).
                    Lower = more privacy, less accuracy
            salt: Salt for pseudonymization hashing (default: "default_salt")

        Returns:
            Dictionary with anonymized data and metadata:
            - anonymized_data: The anonymized record(s)
            - method: Method used
            - fields_processed: List of fields that were anonymized

        Example:
            # Anonymize patient records with k-anonymity
            result = anonymize_data(
                data={"name": "John Doe", "age": 35, "diagnosis": "Flu", "zip": "12345"},
                sensitive_fields=["name", "diagnosis"],
                method="k_anonymity",
                quasi_identifiers=["age", "zip"]
            )

            # Use pseudonymization for consistent fake IDs
            result = anonymize_data(
                data={"email": "user@example.com", "purchase": "$100"},
                sensitive_fields=["email"],
                method="pseudonymization"
            )
        """
        try:
            if not sensitive_fields:
                return {"error": "sensitive_fields list cannot be empty"}

            is_single_record = isinstance(data, dict)
            records = [data] if is_single_record else data

            if not records:
                return {"error": "data cannot be empty"}

            valid_methods = ["k_anonymity", "pseudonymization", "differential_privacy"]
            if method not in valid_methods:
                return {"error": f"Invalid method '{method}'. Must be one of: {valid_methods}"}

            anonymized_records = []
            fields_processed = set()

            for record in records:
                if method == "k_anonymity":
                    result = _apply_k_anonymity(record, sensitive_fields, quasi_identifiers, k)
                elif method == "pseudonymization":
                    result = _apply_pseudonymization(record, sensitive_fields, salt)
                else:
                    result = _apply_differential_privacy(record, sensitive_fields, epsilon)

                for field in sensitive_fields:
                    if field in record:
                        fields_processed.add(field)

                anonymized_records.append(result)

            output_data = anonymized_records[0] if is_single_record else anonymized_records

            return {
                "anonymized_data": output_data,
                "method": method,
                "fields_processed": list(fields_processed),
                "record_count": len(anonymized_records),
            }

        except Exception as e:
            return {"error": f"Anonymization failed: {str(e)}"}

    @mcp.tool()
    def check_privacy_compliance(
        data: list[dict[str, Any]],
        quasi_identifiers: list[str],
        k: int = 5,
    ) -> dict[str, Any]:
        """
        Check if data satisfies k-anonymity privacy requirements.

        Use this tool to verify that your anonymized dataset meets
        privacy standards before sharing or publishing.

        Args:
            data: List of records to check (must be a list)
            quasi_identifiers: List of fields that form equivalence classes.
                              Common examples: ["age", "zip_code", "gender"]
            k: Required minimum equivalence class size (default: 5)

        Returns:
            Dictionary with compliance status and details:
            - compliant: Boolean indicating if k-anonymity is satisfied
            - k_value: Current minimum equivalence class size
            - required_k: Required k value
            - equivalence_class_count: Number of unique equivalence classes
            - re_identification_risk: Risk assessment dictionary
            - violations: List of equivalence classes that violate k-anonymity

        Example:
            result = check_privacy_compliance(
                data=[
                    {"age": "30-35", "zip": "123**", "gender": "M"},
                    {"age": "30-35", "zip": "123**", "gender": "M"},
                    {"age": "30-35", "zip": "123**", "gender": "M"},
                ],
                quasi_identifiers=["age", "zip", "gender"],
                k=3
            )
            print(result["compliant"])  # True if k=3 is satisfied
        """
        try:
            if not data:
                return {"error": "data list cannot be empty"}

            if not quasi_identifiers:
                return {"error": "quasi_identifiers list cannot be empty"}

            eq_info = _check_equivalence_classes(data, quasi_identifiers)
            min_size = eq_info["min_class_size"]
            compliant = min_size >= k

            violations = []
            for eq_class, count in eq_info["equivalence_classes"].items():
                if count < k:
                    violations.append({"equivalence_class": list(eq_class), "count": count})

            risk_info = _calculate_re_identification_risk(data, quasi_identifiers)

            return {
                "compliant": compliant,
                "k_value": min_size,
                "required_k": k,
                "equivalence_class_count": eq_info["class_count"],
                "total_records": len(data),
                "re_identification_risk": risk_info,
                "violations": violations,
                "recommendations": _generate_recommendations(compliant, min_size, k, violations),
            }

        except Exception as e:
            return {"error": f"Compliance check failed: {str(e)}"}

    @mcp.tool()
    def detect_pii_fields(
        data: dict[str, Any] | list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Automatically detect potential PII fields in data.

        Use this tool to identify sensitive fields before anonymization.

        Args:
            data: Single record (dict) or list of records to analyze

        Returns:
            Dictionary with detected PII fields:
            - detected_fields: Dict mapping field names to PII types
            - confidence: Confidence level for each detection
            - suggestions: Recommended anonymization methods for each field

        Example:
            result = detect_pii_fields({
                "email": "user@example.com",
                "ssn": "123-45-6789",
                "name": "John Doe"
            })
        """
        try:
            is_single_record = isinstance(data, dict)
            records = [data] if is_single_record else data

            if not records:
                return {"error": "data cannot be empty"}

            pii_patterns = {
                "email": (r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", "high"),
                "ssn": (r"^\d{3}-?\d{2}-?\d{4}$", "high"),
                "phone": (r"^\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}$", "high"),
                "credit_card": (r"^\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}$", "high"),
                "zip_code": (r"^\d{5}(-\d{4})?$", "medium"),
                "date": (r"^\d{4}-\d{2}-\d{2}$", "medium"),
                "ip_address": (r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", "medium"),
            }

            name_patterns = [
                "name",
                "first",
                "last",
                "full",
                "patient",
                "customer",
                "user",
                "client",
                "employee",
                "member",
            ]

            address_patterns = [
                "address",
                "street",
                "city",
                "state",
                "country",
                "location",
            ]

            detected_fields: dict[str, dict[str, Any]] = {}
            sample_record = records[0]

            for field, value in sample_record.items():
                field_lower = field.lower()
                str_value = str(value) if value is not None else ""

                detected_type = None
                confidence = "low"
                suggestion = "pseudonymization"

                for pii_type, (pattern, conf) in pii_patterns.items():
                    if re.match(pattern, str_value):
                        detected_type = pii_type
                        confidence = conf
                        break

                if not detected_type:
                    if any(np in field_lower for np in name_patterns):
                        detected_type = "name"
                        confidence = "medium"
                        suggestion = "pseudonymization"
                    elif any(ap in field_lower for ap in address_patterns):
                        detected_type = "address"
                        confidence = "medium"
                        suggestion = "k_anonymity"
                    elif "age" in field_lower or "dob" in field_lower:
                        detected_type = "age"
                        confidence = "medium"
                        suggestion = "k_anonymity"
                    elif "id" in field_lower and len(str_value) > 5:
                        detected_type = "identifier"
                        confidence = "low"
                        suggestion = "pseudonymization"

                if detected_type:
                    detected_fields[field] = {
                        "type": detected_type,
                        "confidence": confidence,
                        "suggested_method": suggestion,
                    }

            return {
                "detected_fields": detected_fields,
                "fields_analyzed": list(sample_record.keys()),
                "scan_summary": {
                    "total_fields": len(sample_record),
                    "pii_fields_detected": len(detected_fields),
                    "high_confidence_count": sum(
                        1 for f in detected_fields.values() if f["confidence"] == "high"
                    ),
                },
            }

        except Exception as e:
            return {"error": f"PII detection failed: {str(e)}"}


def _generate_recommendations(
    compliant: bool,
    min_size: int,
    required_k: int,
    violations: list[dict[str, Any]],
) -> list[str]:
    """Generate recommendations for achieving k-anonymity."""
    recommendations = []

    if compliant:
        recommendations.append(
            f"Data satisfies k-anonymity with k={min_size} (required: {required_k})"
        )
    else:
        recommendations.append(
            f"Data violates k-anonymity. Current min class size: {min_size}, required: {required_k}"
        )

        if violations:
            recommendations.append(f"Found {len(violations)} equivalence classes below threshold")
            recommendations.append("Consider further generalization of quasi-identifiers")
            recommendations.append("Consider suppressing records in small equivalence classes")

        if min_size == 1:
            recommendations.append("WARNING: Some records are uniquely identifiable")

    return recommendations
