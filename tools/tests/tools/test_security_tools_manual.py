#!/usr/bin/env python3
"""
Manual test script for security scanning tools.

Calls each tool against example.com with real network requests,
validates response structure, and feeds all results into the risk_scorer.

Usage:
    python tests/tools/test_security_tools_manual.py
    python tests/tools/test_security_tools_manual.py --no-verify   # skip SSL verification
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import sys
import time
from unittest.mock import patch

from fastmcp import FastMCP

from aden_tools.tools.dns_security_scanner import register_tools as register_dns
from aden_tools.tools.http_headers_scanner import register_tools as register_headers
from aden_tools.tools.port_scanner import register_tools as register_ports
from aden_tools.tools.risk_scorer import register_tools as register_scorer

# Import each tool's register function
from aden_tools.tools.ssl_tls_scanner import register_tools as register_ssl
from aden_tools.tools.subdomain_enumerator import register_tools as register_subdomains
from aden_tools.tools.tech_stack_detector import register_tools as register_tech

TARGET_DOMAIN = "example.com"
TARGET_URL = "https://example.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_tool_fn(mcp: FastMCP, name: str):
    """Extract raw function from MCP tool manager."""
    return mcp._tool_manager._tools[name].fn


def call_tool(fn, *args, **kwargs):
    """Call a tool function, handling async transparently."""
    if inspect.iscoroutinefunction(fn):
        return asyncio.run(fn(*args, **kwargs))
    return fn(*args, **kwargs)


def validate_keys(result: dict, required_keys: list[str], tool_name: str) -> list[str]:
    """Check that required keys exist in the result dict. Returns list of errors."""
    errors = []
    for key in required_keys:
        if key not in result:
            errors.append(f"  Missing key: '{key}'")
    return errors


def validate_grade_input(result: dict, expected_keys: list[str], tool_name: str) -> list[str]:
    """Check that grade_input exists and has expected boolean keys."""
    errors = []
    gi = result.get("grade_input")
    if gi is None:
        errors.append("  Missing 'grade_input'")
        return errors
    if not isinstance(gi, dict):
        errors.append(f"  'grade_input' is {type(gi).__name__}, expected dict")
        return errors
    for key in expected_keys:
        if key not in gi:
            errors.append(f"  grade_input missing key: '{key}'")
        elif not isinstance(gi[key], bool):
            errors.append(f"  grade_input['{key}'] is {type(gi[key]).__name__}, expected bool")
    return errors


def print_section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_result_summary(result: dict, max_lines: int = 15):
    """Pretty-print a result dict, truncated."""
    formatted = json.dumps(result, indent=2, default=str)
    lines = formatted.split("\n")
    for line in lines[:max_lines]:
        print(f"  {line}")
    if len(lines) > max_lines:
        print(f"  ... ({len(lines) - max_lines} more lines)")


# ---------------------------------------------------------------------------
# Individual tool tests
# ---------------------------------------------------------------------------

def test_ssl_tls_scan(mcp: FastMCP) -> tuple[dict | None, list[str]]:
    fn = get_tool_fn(mcp, "ssl_tls_scan")
    result = call_tool(fn, hostname=TARGET_DOMAIN)

    if not isinstance(result, dict):
        return None, [f"  Result is {type(result).__name__}, expected dict"]
    if "error" in result:
        return result, [f"  Tool returned error: {result['error']}"]

    errors = validate_keys(result, ["hostname", "tls_version", "cipher", "certificate", "issues", "grade_input"], "ssl_tls_scan")
    errors += validate_grade_input(result, ["tls_version_ok", "cert_valid", "cert_expiring_soon", "strong_cipher", "self_signed"], "ssl_tls_scan")
    return result, errors


def test_http_headers_scan(mcp: FastMCP) -> tuple[dict | None, list[str]]:
    fn = get_tool_fn(mcp, "http_headers_scan")
    result = call_tool(fn, url=TARGET_URL)

    if not isinstance(result, dict):
        return None, [f"  Result is {type(result).__name__}, expected dict"]
    if "error" in result:
        return result, [f"  Tool returned error: {result['error']}"]

    errors = validate_keys(result, ["url", "status_code", "headers_present", "headers_missing", "leaky_headers", "grade_input"], "http_headers_scan")
    errors += validate_grade_input(result, ["hsts", "csp", "x_frame_options", "x_content_type_options", "referrer_policy", "permissions_policy", "no_leaky_headers"], "http_headers_scan")
    return result, errors


def test_dns_security_scan(mcp: FastMCP) -> tuple[dict | None, list[str]]:
    fn = get_tool_fn(mcp, "dns_security_scan")
    result = call_tool(fn, domain=TARGET_DOMAIN)

    if not isinstance(result, dict):
        return None, [f"  Result is {type(result).__name__}, expected dict"]
    if "error" in result:
        return result, [f"  Tool returned error: {result['error']}"]

    errors = validate_keys(result, ["domain", "spf", "dmarc", "dkim", "dnssec", "mx_records", "caa_records", "zone_transfer", "grade_input"], "dns_security_scan")
    errors += validate_grade_input(result, ["spf_present", "spf_strict", "dmarc_present", "dmarc_enforcing", "dkim_found", "dnssec_enabled", "zone_transfer_blocked"], "dns_security_scan")
    return result, errors


def test_port_scan(mcp: FastMCP) -> tuple[dict | None, list[str]]:
    fn = get_tool_fn(mcp, "port_scan")
    # Only scan 80 and 443 to keep it fast
    result = call_tool(fn, hostname=TARGET_DOMAIN, ports="80,443")

    if not isinstance(result, dict):
        return None, [f"  Result is {type(result).__name__}, expected dict"]
    if "error" in result:
        return result, [f"  Tool returned error: {result['error']}"]

    errors = validate_keys(result, ["hostname", "ip", "ports_scanned", "open_ports", "closed_ports", "grade_input"], "port_scan")
    errors += validate_grade_input(result, ["no_database_ports_exposed", "no_admin_ports_exposed", "no_legacy_ports_exposed", "only_web_ports"], "port_scan")
    return result, errors


def test_tech_stack_detect(mcp: FastMCP) -> tuple[dict | None, list[str]]:
    fn = get_tool_fn(mcp, "tech_stack_detect")
    result = call_tool(fn, url=TARGET_URL)

    if not isinstance(result, dict):
        return None, [f"  Result is {type(result).__name__}, expected dict"]
    if "error" in result:
        return result, [f"  Tool returned error: {result['error']}"]

    errors = validate_keys(result, ["url", "server", "framework", "language", "cms", "javascript_libraries", "cdn", "analytics", "security_txt", "robots_txt", "interesting_paths", "cookies", "grade_input"], "tech_stack_detect")
    errors += validate_grade_input(result, ["server_version_hidden", "framework_version_hidden", "security_txt_present", "cookies_secure", "cookies_httponly"], "tech_stack_detect")
    return result, errors


def test_subdomain_enumerate(mcp: FastMCP) -> tuple[dict | None, list[str]]:
    fn = get_tool_fn(mcp, "subdomain_enumerate")
    result = call_tool(fn, domain=TARGET_DOMAIN, max_results=10)

    if not isinstance(result, dict):
        return None, [f"  Result is {type(result).__name__}, expected dict"]
    if "error" in result:
        return result, [f"  Tool returned error: {result['error']}"]

    errors = validate_keys(result, ["domain", "source", "total_found", "subdomains", "interesting", "grade_input"], "subdomain_enumerate")
    errors += validate_grade_input(result, ["no_dev_staging_exposed", "no_admin_exposed", "reasonable_surface_area"], "subdomain_enumerate")
    return result, errors


def test_risk_score(mcp: FastMCP, scan_results: dict[str, dict | None]) -> tuple[dict | None, list[str]]:
    fn = get_tool_fn(mcp, "risk_score")

    # Build JSON string arguments from collected scan results
    kwargs = {}
    param_map = {
        "ssl_tls_scan": "ssl_results",
        "http_headers_scan": "headers_results",
        "dns_security_scan": "dns_results",
        "port_scan": "ports_results",
        "tech_stack_detect": "tech_results",
        "subdomain_enumerate": "subdomain_results",
    }
    for tool_name, param_name in param_map.items():
        data = scan_results.get(tool_name)
        kwargs[param_name] = json.dumps(data) if data else ""

    result = call_tool(fn, **kwargs)

    if not isinstance(result, dict):
        return None, [f"  Result is {type(result).__name__}, expected dict"]
    if "error" in result:
        return result, [f"  Tool returned error: {result['error']}"]

    errors = validate_keys(result, ["overall_score", "overall_grade", "categories", "top_risks", "grade_scale"], "risk_score")

    # Validate score is in range
    score = result.get("overall_score")
    if score is not None and not (0 <= score <= 100):
        errors.append(f"  overall_score={score} is out of range [0, 100]")

    # Validate grade is valid
    grade = result.get("overall_grade")
    if grade not in ("A", "B", "C", "D", "F"):
        errors.append(f"  overall_grade='{grade}' is not a valid grade")

    # Validate categories dict has expected keys
    cats = result.get("categories", {})
    for cat in ["ssl_tls", "http_headers", "dns_security", "network_exposure", "technology", "attack_surface"]:
        if cat not in cats:
            errors.append(f"  categories missing '{cat}'")

    return result, errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _patch_httpx_verify():
    """Monkeypatch httpx.AsyncClient to disable SSL verification.

    Useful when the local Python SSL store is missing intermediate CAs.
    Only affects this test run — not the tool source code.
    """
    _orig_init = __import__("httpx").AsyncClient.__init__

    def _patched_init(self, *args, **kwargs):
        kwargs["verify"] = False
        return _orig_init(self, *args, **kwargs)

    return patch.object(__import__("httpx").AsyncClient, "__init__", _patched_init)


def main():
    no_verify = "--no-verify" in sys.argv

    print("Security Tools Manual Test")
    print(f"Target: {TARGET_DOMAIN}")
    print(f"Time:   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if no_verify:
        print("Mode:   --no-verify (SSL verification disabled for httpx)")

    # Register all security tools on a single MCP instance
    mcp = FastMCP("security-test")

    # Apply SSL verification patch before registering tools that use httpx.
    # The patch must be active when the tool functions are *called*, not just
    # when they are registered, so we keep the context manager open.
    ctx = _patch_httpx_verify() if no_verify else contextlib.nullcontext()
    ctx.__enter__()

    register_ssl(mcp)
    register_headers(mcp)
    register_dns(mcp)
    register_ports(mcp)
    register_tech(mcp)
    register_subdomains(mcp)
    register_scorer(mcp)

    # Run each scanner and collect results
    tests = [
        ("ssl_tls_scan", test_ssl_tls_scan),
        ("http_headers_scan", test_http_headers_scan),
        ("dns_security_scan", test_dns_security_scan),
        ("port_scan", test_port_scan),
        ("tech_stack_detect", test_tech_stack_detect),
        ("subdomain_enumerate", test_subdomain_enumerate),
    ]

    scan_results: dict[str, dict | None] = {}
    summary: list[tuple[str, bool, float, list[str]]] = []  # (name, passed, duration, errors)

    for tool_name, test_fn in tests:
        print_section(tool_name)
        start = time.time()
        try:
            result, errors = test_fn(mcp)
            duration = time.time() - start
            passed = len(errors) == 0 and result is not None and "error" not in (result or {})
            scan_results[tool_name] = result if passed else None

            if result:
                print_result_summary(result)
            if errors:
                print("\n  Validation errors:")
                for e in errors:
                    print(e)
            print(f"\n  Duration: {duration:.2f}s  |  {'PASS' if passed else 'FAIL'}")
            summary.append((tool_name, passed, duration, errors))
        except Exception as exc:
            duration = time.time() - start
            print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
            scan_results[tool_name] = None
            summary.append((tool_name, False, duration, [f"  Exception: {exc}"]))

    # Risk scorer (pipeline test)
    print_section("risk_score (pipeline)")
    start = time.time()
    try:
        result, errors = test_risk_score(mcp, scan_results)
        duration = time.time() - start
        passed = len(errors) == 0 and result is not None
        if result:
            print_result_summary(result, max_lines=25)
        if errors:
            print("\n  Validation errors:")
            for e in errors:
                print(e)
        print(f"\n  Duration: {duration:.2f}s  |  {'PASS' if passed else 'FAIL'}")
        summary.append(("risk_score", passed, duration, errors))
    except Exception as exc:
        duration = time.time() - start
        print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
        summary.append(("risk_score", False, duration, [f"  Exception: {exc}"]))

    # Final summary table
    print(f"\n{'=' * 60}")
    print("  SUMMARY")
    print(f"{'=' * 60}")
    print(f"  {'Tool':<25} {'Status':<8} {'Time':>6}")
    print(f"  {'-' * 25} {'-' * 8} {'-' * 6}")

    total_pass = 0
    total_time = 0.0
    for name, passed, duration, _ in summary:
        status = "PASS" if passed else "FAIL"
        print(f"  {name:<25} {status:<8} {duration:>5.2f}s")
        total_pass += int(passed)
        total_time += duration

    print(f"  {'-' * 25} {'-' * 8} {'-' * 6}")
    print(f"  {'Total':<25} {total_pass}/{len(summary):<5} {total_time:>5.2f}s")

    # Clean up SSL patch
    ctx.__exit__(None, None, None)

    # Exit code
    if total_pass == len(summary):
        print("\n  All tools passed!")
        sys.exit(0)
    else:
        failed = [name for name, passed, _, _ in summary if not passed]
        print(f"\n  Failed tools: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
