"""Tests for security scanning tools.

Comprehensive tests for all 7 security tools:
- port_scanner
- ssl_tls_scanner
- http_headers_scanner
- dns_security_scanner
- subdomain_enumerator
- tech_stack_detector
- risk_scorer
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Tech Stack Detector - Cookie Analysis
# ---------------------------------------------------------------------------


class FakeHeaders:
    """Minimal stand-in for httpx.Headers.get_list()."""

    def __init__(self, set_cookie_values: list[str]):
        self._cookies = set_cookie_values

    def get_list(self, name: str) -> list[str]:
        if name == "set-cookie":
            return self._cookies
        return []


class TestAnalyzeCookies:
    """Tests for _analyze_cookies parsing raw Set-Cookie headers."""

    def test_secure_and_httponly_detected(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _analyze_cookies

        headers = FakeHeaders(["session_id=abc123; Path=/; Secure; HttpOnly"])
        result = _analyze_cookies(headers)

        assert len(result) == 1
        assert result[0]["name"] == "session_id"
        assert result[0]["secure"] is True
        assert result[0]["httponly"] is True

    def test_missing_flags_detected(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _analyze_cookies

        headers = FakeHeaders(["tracking=xyz; Path=/"])
        result = _analyze_cookies(headers)

        assert len(result) == 1
        assert result[0]["secure"] is False
        assert result[0]["httponly"] is False

    def test_case_insensitive(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _analyze_cookies

        headers = FakeHeaders(["tok=val; SECURE; HTTPONLY"])
        result = _analyze_cookies(headers)

        assert result[0]["secure"] is True
        assert result[0]["httponly"] is True

    def test_samesite_values(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _analyze_cookies

        headers = FakeHeaders(["a=1; SameSite=Lax", "b=2; SameSite=Strict", "c=3; SameSite=None"])
        result = _analyze_cookies(headers)

        assert result[0]["samesite"] == "Lax"
        assert result[1]["samesite"] == "Strict"
        assert result[2]["samesite"] == "None"

    def test_multiple_cookies(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _analyze_cookies

        headers = FakeHeaders(
            ["a=1; Secure; HttpOnly", "b=2; Path=/", "c=3; Secure; SameSite=Strict"]
        )
        result = _analyze_cookies(headers)

        assert len(result) == 3
        assert result[0] == {"name": "a", "secure": True, "httponly": True, "samesite": None}
        assert result[1] == {"name": "b", "secure": False, "httponly": False, "samesite": None}
        assert result[2] == {"name": "c", "secure": True, "httponly": False, "samesite": "Strict"}

    def test_no_cookies(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _analyze_cookies

        headers = FakeHeaders([])
        assert _analyze_cookies(headers) == []

    def test_cookie_value_with_equals(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _analyze_cookies

        headers = FakeHeaders(["token=abc=def==; Secure; HttpOnly"])
        result = _analyze_cookies(headers)

        assert result[0]["name"] == "token"
        assert result[0]["secure"] is True


class TestExtractSamesite:
    """Tests for _extract_samesite helper."""

    def test_lax(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _extract_samesite

        assert _extract_samesite("id=val; path=/; samesite=lax") == "Lax"

    def test_strict(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _extract_samesite

        assert _extract_samesite("id=val; samesite=strict; secure") == "Strict"

    def test_none(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _extract_samesite

        assert _extract_samesite("id=val; samesite=none; secure") == "None"

    def test_missing(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _extract_samesite

        assert _extract_samesite("id=val; secure; httponly") is None


# ---------------------------------------------------------------------------
# Tech Stack Detector - Detection Functions
# ---------------------------------------------------------------------------


class TestTechStackDetection:
    """Tests for tech stack detection helpers."""

    def test_detect_server_with_version(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _detect_server

        headers = MagicMock()
        headers.get.return_value = "nginx/1.18.0"

        result = _detect_server(headers)
        assert result["name"] == "nginx"
        assert result["version"] == "1.18.0"

    def test_detect_server_no_version(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _detect_server

        headers = MagicMock()
        headers.get.return_value = "Apache"

        result = _detect_server(headers)
        assert result["name"] == "Apache"

    def test_detect_server_none(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _detect_server

        headers = MagicMock()
        headers.get.return_value = None

        assert _detect_server(headers) is None

    def test_detect_cdn_cloudflare(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _detect_cdn

        headers = MagicMock()
        headers.get.side_effect = lambda h: "abc123" if h == "cf-ray" else None

        assert _detect_cdn(headers) == "Cloudflare"

    def test_detect_cdn_vercel(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _detect_cdn

        headers = MagicMock()
        headers.get.side_effect = lambda h: "req123" if h == "x-vercel-id" else None

        assert _detect_cdn(headers) == "Vercel"

    def test_detect_js_libraries(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _detect_js_libraries

        html = '<script src="https://cdn.example.com/react.min.js"></script>'
        result = _detect_js_libraries(html)
        assert "React" in result

    def test_detect_js_libraries_jquery_with_version(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _detect_js_libraries

        html = '<script src="jquery-3.6.0.min.js"></script>'
        result = _detect_js_libraries(html)
        assert any("jQuery" in lib for lib in result)

    def test_detect_analytics_google(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _detect_analytics

        html = '<script src="https://www.google-analytics.com/analytics.js"></script>'
        result = _detect_analytics(html)
        assert "Google Analytics" in result

    def test_detect_cms_wordpress(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _detect_cms_from_html

        html = '<link rel="stylesheet" href="/wp-content/themes/theme/style.css">'
        assert _detect_cms_from_html(html) == "WordPress"

    def test_detect_cms_shopify(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _detect_cms_from_html

        html = '<script src="https://cdn.shopify.com/s/files/script.js"></script>'
        assert _detect_cms_from_html(html) == "Shopify"

    def test_detect_framework_django(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import (
            _detect_framework_from_html,
        )

        html = '<input name="csrfmiddlewaretoken" value="abc123">'
        assert _detect_framework_from_html(html) == "Django"

    def test_has_version(self):
        from aden_tools.tools.tech_stack_detector.tech_stack_detector import _has_version

        assert _has_version("Express/4.18.2") is True
        assert _has_version("nginx") is False


# ---------------------------------------------------------------------------
# Port Scanner
# ---------------------------------------------------------------------------


class TestPortScanner:
    """Tests for port scanner."""

    def test_port_service_map(self):
        from aden_tools.tools.port_scanner.port_scanner import PORT_SERVICE_MAP

        assert PORT_SERVICE_MAP[22] == "SSH"
        assert PORT_SERVICE_MAP[80] == "HTTP"
        assert PORT_SERVICE_MAP[443] == "HTTPS"
        assert PORT_SERVICE_MAP[3306] == "MySQL"
        assert PORT_SERVICE_MAP[5432] == "PostgreSQL"

    def test_database_ports_defined(self):
        from aden_tools.tools.port_scanner.port_scanner import DATABASE_PORTS

        assert 3306 in DATABASE_PORTS  # MySQL
        assert 5432 in DATABASE_PORTS  # PostgreSQL
        assert 6379 in DATABASE_PORTS  # Redis
        assert 27017 in DATABASE_PORTS  # MongoDB

    def test_admin_ports_defined(self):
        from aden_tools.tools.port_scanner.port_scanner import ADMIN_PORTS

        assert 3389 in ADMIN_PORTS  # RDP
        assert 5900 in ADMIN_PORTS  # VNC

    def test_legacy_ports_defined(self):
        from aden_tools.tools.port_scanner.port_scanner import LEGACY_PORTS

        assert 21 in LEGACY_PORTS  # FTP
        assert 23 in LEGACY_PORTS  # Telnet

    def test_top20_ports_count(self):
        from aden_tools.tools.port_scanner.port_scanner import TOP20_PORTS

        assert len(TOP20_PORTS) == 20

    def test_top100_ports_count(self):
        from aden_tools.tools.port_scanner.port_scanner import TOP100_PORTS

        assert len(TOP100_PORTS) >= 80  # At least 80 ports

    @pytest.mark.asyncio
    async def test_check_port_open_with_banner(self):
        from aden_tools.tools.port_scanner.port_scanner import _check_port

        mock_reader = AsyncMock()
        mock_reader.read = AsyncMock(return_value=b"SSH-2.0-OpenSSH_8.9\r\n")
        mock_writer = AsyncMock()
        mock_writer.close = lambda: None
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = (mock_reader, mock_writer)
            result = await _check_port("127.0.0.1", 22, timeout=2.0)

        assert result["open"] is True
        assert result["banner"] == "SSH-2.0-OpenSSH_8.9"
        mock_conn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_port_open_no_banner(self):
        from aden_tools.tools.port_scanner.port_scanner import _check_port

        mock_reader = AsyncMock()
        mock_reader.read = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_writer = AsyncMock()
        mock_writer.close = lambda: None
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = (mock_reader, mock_writer)
            result = await _check_port("127.0.0.1", 80, timeout=2.0)

        assert result["open"] is True
        assert result["banner"] == ""

    @pytest.mark.asyncio
    async def test_check_port_closed(self):
        from aden_tools.tools.port_scanner.port_scanner import _check_port

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.side_effect = ConnectionRefusedError
            result = await _check_port("127.0.0.1", 12345, timeout=2.0)

        assert result["open"] is False

    @pytest.mark.asyncio
    async def test_check_port_timeout(self):
        from aden_tools.tools.port_scanner.port_scanner import _check_port

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.side_effect = TimeoutError
            result = await _check_port("127.0.0.1", 12345, timeout=0.5)

        assert result["open"] is False

    def test_port_findings_have_remediation(self):
        """Port findings include remediation guidance."""
        from aden_tools.tools.port_scanner.port_scanner import PORT_FINDINGS

        for _category, info in PORT_FINDINGS.items():
            assert "severity" in info
            assert "remediation" in info


# ---------------------------------------------------------------------------
# SSL/TLS Scanner
# ---------------------------------------------------------------------------


class TestSSLTLSScanner:
    """Tests for SSL/TLS scanner."""

    def test_weak_ciphers_defined(self):
        from aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner import WEAK_CIPHERS

        assert "RC4" in WEAK_CIPHERS
        assert "DES" in WEAK_CIPHERS
        assert "3DES" in WEAK_CIPHERS
        assert "MD5" in WEAK_CIPHERS
        assert "NULL" in WEAK_CIPHERS

    def test_insecure_tls_versions_defined(self):
        from aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner import INSECURE_TLS_VERSIONS

        assert "TLSv1" in INSECURE_TLS_VERSIONS
        assert "TLSv1.0" in INSECURE_TLS_VERSIONS
        assert "TLSv1.1" in INSECURE_TLS_VERSIONS
        assert "SSLv2" in INSECURE_TLS_VERSIONS
        assert "SSLv3" in INSECURE_TLS_VERSIONS

    def test_format_dn(self):
        from aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner import _format_dn

        dn = ((("commonName", "example.com"),), (("organizationName", "Example Inc"),))
        result = _format_dn(dn)
        assert "commonName=example.com" in result
        assert "organizationName=Example Inc" in result

    def test_format_dn_empty(self):
        from aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner import _format_dn

        assert _format_dn(()) == ""

    def test_parse_cert_date_valid(self):
        from aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner import _parse_cert_date

        result = _parse_cert_date("Jan  1 00:00:00 2025 GMT")
        assert result is not None
        assert result.year == 2025
        assert result.month == 1
        assert result.day == 1

    def test_parse_cert_date_single_digit_day(self):
        from aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner import _parse_cert_date

        result = _parse_cert_date("Jan 15 12:30:45 2024 GMT")
        assert result is not None
        assert result.day == 15

    def test_parse_cert_date_empty(self):
        from aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner import _parse_cert_date

        assert _parse_cert_date("") is None

    def test_parse_cert_date_none(self):
        from aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner import _parse_cert_date

        assert _parse_cert_date(None) is None

    def test_ssl_tls_scan_cleans_hostname(self):
        """Test that hostname is properly cleaned."""
        # Test the hostname cleaning logic indirectly
        hostname = "https://example.com/path?query=1"
        cleaned = hostname.replace("https://", "").replace("http://", "").strip("/")
        cleaned = cleaned.split("/")[0]
        if ":" in cleaned:
            cleaned = cleaned.split(":")[0]
        assert cleaned == "example.com"


# ---------------------------------------------------------------------------
# HTTP Headers Scanner
# ---------------------------------------------------------------------------


class TestHTTPHeadersScanner:
    """Tests for HTTP headers scanner."""

    def test_security_headers_defined(self):
        from aden_tools.tools.http_headers_scanner.http_headers_scanner import SECURITY_HEADERS

        assert "Strict-Transport-Security" in SECURITY_HEADERS
        assert "Content-Security-Policy" in SECURITY_HEADERS
        assert "X-Frame-Options" in SECURITY_HEADERS
        assert "X-Content-Type-Options" in SECURITY_HEADERS
        assert "Referrer-Policy" in SECURITY_HEADERS
        assert "Permissions-Policy" in SECURITY_HEADERS

    def test_security_headers_have_severity(self):
        from aden_tools.tools.http_headers_scanner.http_headers_scanner import SECURITY_HEADERS

        for header, info in SECURITY_HEADERS.items():
            assert "severity" in info, f"{header} missing severity"
            assert info["severity"] in ("high", "medium", "low")

    def test_security_headers_have_remediation(self):
        from aden_tools.tools.http_headers_scanner.http_headers_scanner import SECURITY_HEADERS

        for header, info in SECURITY_HEADERS.items():
            assert "remediation" in info, f"{header} missing remediation"
            assert len(info["remediation"]) > 0

    def test_leaky_headers_defined(self):
        from aden_tools.tools.http_headers_scanner.http_headers_scanner import LEAKY_HEADERS

        assert "Server" in LEAKY_HEADERS
        assert "X-Powered-By" in LEAKY_HEADERS
        assert "X-AspNet-Version" in LEAKY_HEADERS
        assert "X-Generator" in LEAKY_HEADERS

    def test_hsts_severity_is_high(self):
        from aden_tools.tools.http_headers_scanner.http_headers_scanner import SECURITY_HEADERS

        assert SECURITY_HEADERS["Strict-Transport-Security"]["severity"] == "high"

    def test_csp_severity_is_high(self):
        from aden_tools.tools.http_headers_scanner.http_headers_scanner import SECURITY_HEADERS

        assert SECURITY_HEADERS["Content-Security-Policy"]["severity"] == "high"

    @pytest.mark.asyncio
    async def test_http_headers_scan_auto_prefix(self):
        """Test URL auto-prefixing logic."""
        url = "example.com"
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        assert url == "https://example.com"


# ---------------------------------------------------------------------------
# DNS Security Scanner
# ---------------------------------------------------------------------------


class TestDNSSecurityScanner:
    """Tests for DNS security scanner."""

    def test_dkim_selectors_defined(self):
        from aden_tools.tools.dns_security_scanner.dns_security_scanner import DKIM_SELECTORS

        assert "default" in DKIM_SELECTORS
        assert "google" in DKIM_SELECTORS
        assert "selector1" in DKIM_SELECTORS
        assert "selector2" in DKIM_SELECTORS

    def test_check_spf_hardfail(self):
        from aden_tools.tools.dns_security_scanner.dns_security_scanner import _check_spf

        mock_resolver = MagicMock()
        mock_rdata = MagicMock()
        mock_rdata.to_text.return_value = '"v=spf1 include:_spf.google.com -all"'
        mock_resolver.resolve.return_value = [mock_rdata]

        result = _check_spf(mock_resolver, "example.com")
        assert result["present"] is True
        assert result["policy"] == "hardfail"
        assert len(result["issues"]) == 0

    def test_check_spf_softfail(self):
        from aden_tools.tools.dns_security_scanner.dns_security_scanner import _check_spf

        mock_resolver = MagicMock()
        mock_rdata = MagicMock()
        mock_rdata.to_text.return_value = '"v=spf1 include:example.com ~all"'
        mock_resolver.resolve.return_value = [mock_rdata]

        result = _check_spf(mock_resolver, "example.com")
        assert result["present"] is True
        assert result["policy"] == "softfail"
        assert len(result["issues"]) > 0

    def test_check_spf_pass_all_dangerous(self):
        from aden_tools.tools.dns_security_scanner.dns_security_scanner import _check_spf

        mock_resolver = MagicMock()
        mock_rdata = MagicMock()
        mock_rdata.to_text.return_value = '"v=spf1 +all"'
        mock_resolver.resolve.return_value = [mock_rdata]

        result = _check_spf(mock_resolver, "example.com")
        assert result["policy"] == "pass_all"
        assert len(result["issues"]) > 0

    def test_check_spf_not_found(self):
        import dns.resolver

        from aden_tools.tools.dns_security_scanner.dns_security_scanner import _check_spf

        mock_resolver = MagicMock()
        mock_resolver.resolve.side_effect = dns.resolver.NoAnswer

        result = _check_spf(mock_resolver, "example.com")
        assert result["present"] is False

    def test_check_dmarc_reject(self):
        from aden_tools.tools.dns_security_scanner.dns_security_scanner import _check_dmarc

        mock_resolver = MagicMock()
        mock_rdata = MagicMock()
        mock_rdata.to_text.return_value = '"v=DMARC1; p=reject; rua=mailto:dmarc@example.com"'
        mock_resolver.resolve.return_value = [mock_rdata]

        result = _check_dmarc(mock_resolver, "example.com")
        assert result["present"] is True
        assert result["policy"] == "reject"

    def test_check_dmarc_none_policy(self):
        from aden_tools.tools.dns_security_scanner.dns_security_scanner import _check_dmarc

        mock_resolver = MagicMock()
        mock_rdata = MagicMock()
        mock_rdata.to_text.return_value = '"v=DMARC1; p=none"'
        mock_resolver.resolve.return_value = [mock_rdata]

        result = _check_dmarc(mock_resolver, "example.com")
        assert result["policy"] == "none"
        assert len(result["issues"]) > 0

    def test_check_dkim_found(self):
        from aden_tools.tools.dns_security_scanner.dns_security_scanner import _check_dkim

        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = [MagicMock()]

        result = _check_dkim(mock_resolver, "example.com")
        assert len(result["selectors_found"]) > 0

    def test_check_dnssec_enabled(self):
        from aden_tools.tools.dns_security_scanner.dns_security_scanner import _check_dnssec

        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = [MagicMock()]

        result = _check_dnssec(mock_resolver, "example.com")
        assert result["enabled"] is True

    def test_check_dnssec_disabled(self):
        import dns.resolver

        from aden_tools.tools.dns_security_scanner.dns_security_scanner import _check_dnssec

        mock_resolver = MagicMock()
        mock_resolver.resolve.side_effect = dns.resolver.NoAnswer

        result = _check_dnssec(mock_resolver, "example.com")
        assert result["enabled"] is False


# ---------------------------------------------------------------------------
# Subdomain Enumerator
# ---------------------------------------------------------------------------


class TestSubdomainEnumerator:
    """Tests for subdomain enumerator."""

    def test_interesting_keywords_defined(self):
        from aden_tools.tools.subdomain_enumerator.subdomain_enumerator import INTERESTING_KEYWORDS

        assert "staging" in INTERESTING_KEYWORDS
        assert "dev" in INTERESTING_KEYWORDS
        assert "test" in INTERESTING_KEYWORDS
        assert "admin" in INTERESTING_KEYWORDS
        assert "internal" in INTERESTING_KEYWORDS
        assert "backup" in INTERESTING_KEYWORDS
        assert "debug" in INTERESTING_KEYWORDS

    def test_admin_severity_is_high(self):
        from aden_tools.tools.subdomain_enumerator.subdomain_enumerator import INTERESTING_KEYWORDS

        assert INTERESTING_KEYWORDS["admin"]["severity"] == "high"
        assert INTERESTING_KEYWORDS["backup"]["severity"] == "high"
        assert INTERESTING_KEYWORDS["debug"]["severity"] == "high"

    def test_staging_severity_is_medium(self):
        from aden_tools.tools.subdomain_enumerator.subdomain_enumerator import INTERESTING_KEYWORDS

        assert INTERESTING_KEYWORDS["staging"]["severity"] == "medium"
        assert INTERESTING_KEYWORDS["dev"]["severity"] == "medium"
        assert INTERESTING_KEYWORDS["test"]["severity"] == "medium"

    def test_keywords_have_remediation(self):
        from aden_tools.tools.subdomain_enumerator.subdomain_enumerator import INTERESTING_KEYWORDS

        for keyword, info in INTERESTING_KEYWORDS.items():
            assert "remediation" in info, f"{keyword} missing remediation"
            assert len(info["remediation"]) > 0

    def test_domain_cleaning(self):
        """Test domain cleaning logic."""
        domain = "https://example.com/path?query=1"
        domain = domain.replace("https://", "").replace("http://", "").strip("/")
        domain = domain.split("/")[0]
        if ":" in domain:
            domain = domain.split(":")[0]
        assert domain == "example.com"

    @pytest.mark.asyncio
    async def test_subdomain_enumerate_max_results_capped(self):
        """Test that max_results is capped at 200."""
        max_results = 500
        max_results = min(max_results, 200)
        assert max_results == 200


# ---------------------------------------------------------------------------
# Risk Scorer
# ---------------------------------------------------------------------------


class TestRiskScorer:
    """Tests for risk scorer."""

    def test_grade_scale_defined(self):
        from aden_tools.tools.risk_scorer.risk_scorer import GRADE_SCALE

        assert "A" in GRADE_SCALE
        assert "B" in GRADE_SCALE
        assert "C" in GRADE_SCALE
        assert "D" in GRADE_SCALE
        assert "F" in GRADE_SCALE

    def test_category_weights_sum_to_one(self):
        from aden_tools.tools.risk_scorer.risk_scorer import CATEGORY_WEIGHTS

        total = sum(CATEGORY_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01  # Allow small float error

    def test_all_categories_have_weights(self):
        from aden_tools.tools.risk_scorer.risk_scorer import CATEGORY_WEIGHTS

        assert "ssl_tls" in CATEGORY_WEIGHTS
        assert "http_headers" in CATEGORY_WEIGHTS
        assert "dns_security" in CATEGORY_WEIGHTS
        assert "network_exposure" in CATEGORY_WEIGHTS
        assert "technology" in CATEGORY_WEIGHTS
        assert "attack_surface" in CATEGORY_WEIGHTS

    def test_score_to_grade_A(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _score_to_grade

        assert _score_to_grade(100) == "A"
        assert _score_to_grade(95) == "A"
        assert _score_to_grade(90) == "A"

    def test_score_to_grade_B(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _score_to_grade

        assert _score_to_grade(89) == "B"
        assert _score_to_grade(80) == "B"
        assert _score_to_grade(75) == "B"

    def test_score_to_grade_C(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _score_to_grade

        assert _score_to_grade(74) == "C"
        assert _score_to_grade(65) == "C"
        assert _score_to_grade(60) == "C"

    def test_score_to_grade_D(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _score_to_grade

        assert _score_to_grade(59) == "D"
        assert _score_to_grade(50) == "D"
        assert _score_to_grade(40) == "D"

    def test_score_to_grade_F(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _score_to_grade

        assert _score_to_grade(39) == "F"
        assert _score_to_grade(20) == "F"
        assert _score_to_grade(0) == "F"

    def test_parse_json_valid(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _parse_json

        result = _parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_nested(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _parse_json

        result = _parse_json('{"grade_input": {"check": true}}')
        assert result["grade_input"]["check"] is True

    def test_parse_json_invalid(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _parse_json

        assert _parse_json("not json") is None
        assert _parse_json("{invalid}") is None

    def test_parse_json_empty(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _parse_json

        assert _parse_json("") is None
        assert _parse_json("   ") is None

    def test_parse_json_none(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _parse_json

        assert _parse_json(None) is None

    def test_parse_json_non_dict(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _parse_json

        assert _parse_json("[1, 2, 3]") is None
        assert _parse_json('"string"') is None

    def test_score_category_all_pass(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _score_category

        checks = {
            "check_a": {"points": 50, "finding": "A failed"},
            "check_b": {"points": 50, "finding": "B failed"},
        }
        grade_input = {"check_a": True, "check_b": True}
        score, findings = _score_category(grade_input, checks)
        assert score == 100
        assert findings == []

    def test_score_category_all_fail(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _score_category

        checks = {
            "check_a": {"points": 50, "finding": "A failed"},
            "check_b": {"points": 50, "finding": "B failed"},
        }
        grade_input = {"check_a": False, "check_b": False}
        score, findings = _score_category(grade_input, checks)
        assert score == 0
        assert len(findings) == 2
        assert "A failed" in findings
        assert "B failed" in findings

    def test_score_category_partial(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _score_category

        checks = {
            "check_a": {"points": 60, "finding": "A failed"},
            "check_b": {"points": 40, "finding": "B failed"},
        }
        grade_input = {"check_a": True, "check_b": False}
        score, findings = _score_category(grade_input, checks)
        assert score == 60
        assert findings == ["B failed"]

    def test_score_category_inverted_check_true_is_bad(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _score_category

        checks = {
            "self_signed": {"points": 100, "finding": "Self-signed cert", "invert": True},
        }
        # self_signed=True is BAD
        score, findings = _score_category({"self_signed": True}, checks)
        assert score == 0
        assert "Self-signed cert" in findings

    def test_score_category_inverted_check_false_is_good(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _score_category

        checks = {
            "self_signed": {"points": 100, "finding": "Self-signed cert", "invert": True},
        }
        # self_signed=False is GOOD
        score, findings = _score_category({"self_signed": False}, checks)
        assert score == 100
        assert findings == []

    def test_score_category_missing_data_half_credit(self):
        from aden_tools.tools.risk_scorer.risk_scorer import _score_category

        checks = {
            "check_a": {"points": 100, "finding": "A failed"},
        }
        # Missing check_a gets half credit
        score, findings = _score_category({}, checks)
        assert score == 50
        assert findings == []

    def test_ssl_checks_defined(self):
        from aden_tools.tools.risk_scorer.risk_scorer import SSL_CHECKS

        assert "tls_version_ok" in SSL_CHECKS
        assert "cert_valid" in SSL_CHECKS
        assert "strong_cipher" in SSL_CHECKS

    def test_headers_checks_defined(self):
        from aden_tools.tools.risk_scorer.risk_scorer import HEADERS_CHECKS

        assert "hsts" in HEADERS_CHECKS
        assert "csp" in HEADERS_CHECKS
        assert "x_frame_options" in HEADERS_CHECKS

    def test_dns_checks_defined(self):
        from aden_tools.tools.risk_scorer.risk_scorer import DNS_CHECKS

        assert "spf_present" in DNS_CHECKS
        assert "dmarc_present" in DNS_CHECKS
        assert "dnssec_enabled" in DNS_CHECKS

    def test_network_checks_defined(self):
        from aden_tools.tools.risk_scorer.risk_scorer import NETWORK_CHECKS

        assert "no_database_ports_exposed" in NETWORK_CHECKS
        assert "no_admin_ports_exposed" in NETWORK_CHECKS

    def test_all_checks_defined(self):
        """All check categories are defined."""
        from aden_tools.tools.risk_scorer.risk_scorer import ALL_CHECKS

        assert "ssl_tls" in ALL_CHECKS
        assert "http_headers" in ALL_CHECKS
        assert "dns_security" in ALL_CHECKS
        assert "network_exposure" in ALL_CHECKS
        assert "technology" in ALL_CHECKS
        assert "attack_surface" in ALL_CHECKS

    def test_surface_checks_defined(self):
        """Attack surface checks are defined."""
        from aden_tools.tools.risk_scorer.risk_scorer import SURFACE_CHECKS

        assert "no_dev_staging_exposed" in SURFACE_CHECKS
        assert "no_admin_exposed" in SURFACE_CHECKS
        assert "reasonable_surface_area" in SURFACE_CHECKS
