"""
Risk Scorer - Produce weighted letter-grade risk scores from scan results.

Consumes grade_input dicts from the 6 scanning tools and produces a weighted
overall score (0-100) with letter grades (A-F) per category and overall.
Pure Python — no external dependencies.
"""

from __future__ import annotations

import json

from fastmcp import FastMCP

# Grade scale definition
GRADE_SCALE = {
    "A": "90-100: Excellent security posture",
    "B": "75-89: Good, minor improvements needed",
    "C": "60-74: Fair, notable security gaps",
    "D": "40-59: Poor, significant vulnerabilities",
    "F": "0-39: Critical, immediate action required",
}

# Category weights (must sum to 1.0)
CATEGORY_WEIGHTS = {
    "ssl_tls": 0.20,
    "http_headers": 0.20,
    "dns_security": 0.15,
    "network_exposure": 0.15,
    "technology": 0.15,
    "attack_surface": 0.15,
}

# Scoring rules per category — each check is worth equal points within its category
SSL_CHECKS = {
    "tls_version_ok": {"points": 25, "finding": "Insecure TLS version in use"},
    "cert_valid": {"points": 30, "finding": "SSL certificate is invalid or untrusted"},
    "cert_expiring_soon": {
        "points": 10,
        "finding": "SSL certificate expiring soon",
        "invert": True,  # True = bad
    },
    "strong_cipher": {"points": 20, "finding": "Weak cipher suite in use"},
    "self_signed": {
        "points": 15,
        "finding": "Self-signed certificate detected",
        "invert": True,
    },
}

HEADERS_CHECKS = {
    "hsts": {"points": 20, "finding": "Missing Strict-Transport-Security header"},
    "csp": {"points": 20, "finding": "Missing Content-Security-Policy header"},
    "x_frame_options": {"points": 15, "finding": "Missing X-Frame-Options header"},
    "x_content_type_options": {"points": 15, "finding": "Missing X-Content-Type-Options header"},
    "referrer_policy": {"points": 10, "finding": "Missing Referrer-Policy header"},
    "permissions_policy": {"points": 10, "finding": "Missing Permissions-Policy header"},
    "no_leaky_headers": {"points": 10, "finding": "Server information leaked via headers"},
}

DNS_CHECKS = {
    "spf_present": {"points": 15, "finding": "No SPF record found"},
    "spf_strict": {"points": 10, "finding": "SPF policy is not strict (hardfail)"},
    "dmarc_present": {"points": 20, "finding": "No DMARC record found"},
    "dmarc_enforcing": {"points": 15, "finding": "DMARC policy is not enforcing"},
    "dkim_found": {"points": 15, "finding": "No DKIM selector found"},
    "dnssec_enabled": {"points": 15, "finding": "DNSSEC not enabled"},
    "zone_transfer_blocked": {"points": 10, "finding": "DNS zone transfer allowed"},
}

NETWORK_CHECKS = {
    "no_database_ports_exposed": {
        "points": 35,
        "finding": "Database port(s) exposed to internet",
    },
    "no_admin_ports_exposed": {
        "points": 30,
        "finding": "Admin/remote access port(s) exposed to internet",
    },
    "no_legacy_ports_exposed": {
        "points": 20,
        "finding": "Legacy protocol port(s) still active",
    },
    "only_web_ports": {"points": 15, "finding": "Non-web ports open"},
}

TECH_CHECKS = {
    "server_version_hidden": {"points": 25, "finding": "Server version disclosed in headers"},
    "framework_version_hidden": {
        "points": 20,
        "finding": "Framework/runtime version disclosed",
    },
    "security_txt_present": {"points": 20, "finding": "No security.txt file found"},
    "cookies_secure": {"points": 20, "finding": "Cookies missing Secure flag"},
    "cookies_httponly": {"points": 15, "finding": "Cookies missing HttpOnly flag"},
}

SURFACE_CHECKS = {
    "no_dev_staging_exposed": {
        "points": 40,
        "finding": "Dev/staging environment subdomains exposed",
    },
    "no_admin_exposed": {
        "points": 35,
        "finding": "Admin/backup subdomains exposed",
    },
    "reasonable_surface_area": {
        "points": 25,
        "finding": "Large attack surface (many subdomains)",
    },
}

ALL_CHECKS = {
    "ssl_tls": SSL_CHECKS,
    "http_headers": HEADERS_CHECKS,
    "dns_security": DNS_CHECKS,
    "network_exposure": NETWORK_CHECKS,
    "technology": TECH_CHECKS,
    "attack_surface": SURFACE_CHECKS,
}


def _score_to_grade(score: int) -> str:
    """Convert a numeric score (0-100) to a letter grade."""
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _parse_json(data: str) -> dict | None:
    """Safely parse a JSON string, returning None on failure."""
    if not data or not data.strip():
        return None
    try:
        parsed = json.loads(data)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _score_category(grade_input: dict, checks: dict) -> tuple[int, list[str]]:
    """Score a category based on its grade_input and check definitions.

    Returns (score 0-100, list of finding strings).
    """
    total_possible = sum(c["points"] for c in checks.values())
    earned = 0
    findings = []

    for check_key, check_def in checks.items():
        value = grade_input.get(check_key)
        invert = check_def.get("invert", False)

        if value is None:
            # Missing data — give half credit (don't penalize for missing scans)
            earned += check_def["points"] // 2
            continue

        # For "invert" checks, True = bad (e.g., self_signed=True is bad)
        passed = (not value) if invert else bool(value)

        if passed:
            earned += check_def["points"]
        else:
            findings.append(check_def["finding"])

    score = round((earned / total_possible) * 100) if total_possible > 0 else 50
    return score, findings


def register_tools(mcp: FastMCP) -> None:
    """Register risk scoring tools with the MCP server."""

    @mcp.tool()
    def risk_score(
        ssl_results: str = "",
        headers_results: str = "",
        dns_results: str = "",
        ports_results: str = "",
        tech_results: str = "",
        subdomain_results: str = "",
    ) -> dict:
        """
        Calculate a weighted risk score from scan results.

        Consumes the JSON output from the 6 scanning tools (ssl_tls_scan,
        http_headers_scan, dns_security_scan, port_scan, tech_stack_detect,
        subdomain_enumerate) and produces letter grades (A-F) per category
        plus an overall weighted score.

        Args:
            ssl_results: JSON string from ssl_tls_scan output. Empty string to skip.
            headers_results: JSON string from http_headers_scan output. Empty string to skip.
            dns_results: JSON string from dns_security_scan output. Empty string to skip.
            ports_results: JSON string from port_scan output. Empty string to skip.
            tech_results: JSON string from tech_stack_detect output. Empty string to skip.
            subdomain_results: JSON string from subdomain_enumerate output. Empty string to skip.

        Returns:
            Dict with overall_score, overall_grade, per-category scores/grades,
            top_risks list, and grade_scale reference.
        """
        # Parse inputs and extract grade_input dicts
        inputs = {
            "ssl_tls": _parse_json(ssl_results),
            "http_headers": _parse_json(headers_results),
            "dns_security": _parse_json(dns_results),
            "network_exposure": _parse_json(ports_results),
            "technology": _parse_json(tech_results),
            "attack_surface": _parse_json(subdomain_results),
        }

        categories = {}
        all_findings: list[tuple[str, str, int]] = []  # (category, finding, category_score)
        weighted_sum = 0.0
        total_weight = 0.0

        for category, checks in ALL_CHECKS.items():
            raw = inputs[category]
            weight = CATEGORY_WEIGHTS[category]

            if raw is None:
                # Category not scanned — skip it and redistribute weight
                categories[category] = {
                    "score": None,
                    "grade": "N/A",
                    "weight": weight,
                    "findings_count": 0,
                    "skipped": True,
                }
                continue

            # Extract grade_input from the tool output
            grade_input = raw.get("grade_input", raw)

            score, findings = _score_category(grade_input, checks)
            grade = _score_to_grade(score)

            categories[category] = {
                "score": score,
                "grade": grade,
                "weight": weight,
                "findings_count": len(findings),
                "skipped": False,
            }

            weighted_sum += score * weight
            total_weight += weight

            for f in findings:
                all_findings.append((category, f, score))

        # Calculate overall score (normalize if some categories were skipped)
        if total_weight > 0:
            overall_score = round(weighted_sum / total_weight)
        else:
            overall_score = 0

        overall_grade = _score_to_grade(overall_score)

        # Build top risks — sorted by category score (worst first), then by finding
        all_findings.sort(key=lambda x: (x[2], x[0]))
        top_risks = []
        for category, finding, _cat_score in all_findings[:10]:
            cat_grade = categories[category]["grade"]
            cat_label = category.replace("_", " ").title()
            top_risks.append(f"{finding} ({cat_label}: {cat_grade})")

        return {
            "overall_score": overall_score,
            "overall_grade": overall_grade,
            "categories": categories,
            "top_risks": top_risks,
            "grade_scale": GRADE_SCALE,
        }
