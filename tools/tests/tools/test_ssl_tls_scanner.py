"""Tests for SSL/TLS Scanner tool."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.ssl_tls_scanner import register_tools


@pytest.fixture
def ssl_tools(mcp: FastMCP):
    """Register SSL/TLS tools and return tool functions."""
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def scan_fn(ssl_tools):
    return ssl_tools["ssl_tls_scan"]


def _mock_cert_dict(
    days_until_expiry: int = 365,
    subject: str = "example.com",
    issuer: str = "Let's Encrypt",
    san: list[str] | None = None,
):
    """Create a mock certificate dict."""
    now = datetime.now(UTC)
    not_before = now - timedelta(days=30)
    not_after = now + timedelta(days=days_until_expiry)

    return {
        "subject": ((("commonName", subject),),),
        "issuer": ((("commonName", issuer),),),
        "notBefore": not_before.strftime("%b %d %H:%M:%S %Y GMT"),
        "notAfter": not_after.strftime("%b %d %H:%M:%S %Y GMT"),
        "subjectAltName": tuple(("DNS", s) for s in (san or [subject])),
    }


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Test hostname input cleaning."""

    def test_strips_https_prefix(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_ctx.return_value.wrap_socket.side_effect = TimeoutError()
            result = scan_fn("https://example.com")
            assert "example.com" in result["error"]
            assert "https://" not in result["error"]

    def test_strips_http_prefix(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_ctx.return_value.wrap_socket.side_effect = TimeoutError()
            result = scan_fn("http://example.com")
            assert "example.com" in result["error"]
            assert "http://" not in result["error"]

    def test_strips_path(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_ctx.return_value.wrap_socket.side_effect = TimeoutError()
            result = scan_fn("example.com/path/to/page")
            assert "example.com" in result["error"]
            assert "/path" not in result["error"]

    def test_strips_port_from_hostname(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_ctx.return_value.wrap_socket.side_effect = TimeoutError()
            result = scan_fn("example.com:8443")
            assert "example.com:443" in result["error"]


# ---------------------------------------------------------------------------
# Connection Errors
# ---------------------------------------------------------------------------


class TestConnectionErrors:
    """Test error handling for connection failures."""

    def test_timeout_error(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_conn = MagicMock()
            mock_conn.connect.side_effect = TimeoutError()
            mock_ctx.return_value.wrap_socket.return_value = mock_conn

            result = scan_fn("example.com")
            assert "error" in result
            assert "timed out" in result["error"]

    def test_connection_refused(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_conn = MagicMock()
            mock_conn.connect.side_effect = ConnectionRefusedError()
            mock_ctx.return_value.wrap_socket.return_value = mock_conn

            result = scan_fn("example.com")
            assert "error" in result
            assert "refused" in result["error"]


# ---------------------------------------------------------------------------
# TLS Version Detection
# ---------------------------------------------------------------------------


class TestTlsVersion:
    """Test TLS version detection and validation."""

    def test_tls13_ok(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_conn = MagicMock()
            mock_conn.version.return_value = "TLSv1.3"
            mock_conn.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
            mock_conn.getpeercert.return_value = _mock_cert_dict()
            mock_conn.getpeercert.side_effect = [
                b"fake_der_cert",
                _mock_cert_dict(),
            ]
            mock_ctx.return_value.wrap_socket.return_value = mock_conn

            result = scan_fn("example.com")
            assert result["tls_version"] == "TLSv1.3"
            assert result["grade_input"]["tls_version_ok"] is True

    def test_tls10_insecure(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_conn = MagicMock()
            mock_conn.version.return_value = "TLSv1"
            mock_conn.cipher.return_value = ("AES256-SHA", "TLSv1", 256)
            mock_conn.getpeercert.return_value = _mock_cert_dict()
            mock_conn.getpeercert.side_effect = [
                b"fake_der_cert",
                _mock_cert_dict(),
            ]
            mock_ctx.return_value.wrap_socket.return_value = mock_conn

            result = scan_fn("example.com")
            assert result["grade_input"]["tls_version_ok"] is False
            issues = [i["finding"] for i in result.get("issues", [])]
            assert any("TLS version" in i for i in issues)


# ---------------------------------------------------------------------------
# Cipher Suite Detection
# ---------------------------------------------------------------------------


class TestCipherSuite:
    """Test cipher suite detection and validation."""

    def test_strong_cipher(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_conn = MagicMock()
            mock_conn.version.return_value = "TLSv1.3"
            mock_conn.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
            mock_conn.getpeercert.return_value = _mock_cert_dict()
            mock_conn.getpeercert.side_effect = [
                b"fake_der_cert",
                _mock_cert_dict(),
            ]
            mock_ctx.return_value.wrap_socket.return_value = mock_conn

            result = scan_fn("example.com")
            assert result["grade_input"]["strong_cipher"] is True

    def test_weak_cipher_rc4(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_conn = MagicMock()
            mock_conn.version.return_value = "TLSv1.2"
            mock_conn.cipher.return_value = ("RC4-SHA", "TLSv1.2", 128)
            mock_conn.getpeercert.return_value = _mock_cert_dict()
            mock_conn.getpeercert.side_effect = [
                b"fake_der_cert",
                _mock_cert_dict(),
            ]
            mock_ctx.return_value.wrap_socket.return_value = mock_conn

            result = scan_fn("example.com")
            assert result["grade_input"]["strong_cipher"] is False


# ---------------------------------------------------------------------------
# Certificate Validation
# ---------------------------------------------------------------------------


class TestCertificateValidation:
    """Test certificate validation checks."""

    def test_valid_certificate(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_conn = MagicMock()
            mock_conn.version.return_value = "TLSv1.3"
            mock_conn.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
            mock_conn.getpeercert.return_value = _mock_cert_dict(days_until_expiry=365)
            mock_conn.getpeercert.side_effect = [
                b"fake_der_cert",
                _mock_cert_dict(days_until_expiry=365),
            ]
            mock_ctx.return_value.wrap_socket.return_value = mock_conn

            result = scan_fn("example.com")
            assert result["grade_input"]["cert_valid"] is True

    def test_expiring_soon(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_conn = MagicMock()
            mock_conn.version.return_value = "TLSv1.3"
            mock_conn.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
            mock_conn.getpeercert.return_value = _mock_cert_dict(days_until_expiry=15)
            mock_conn.getpeercert.side_effect = [
                b"fake_der_cert",
                _mock_cert_dict(days_until_expiry=15),
            ]
            mock_ctx.return_value.wrap_socket.return_value = mock_conn

            result = scan_fn("example.com")
            assert result["grade_input"]["cert_expiring_soon"] is True

    def test_self_signed_detected(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_conn = MagicMock()
            mock_conn.version.return_value = "TLSv1.3"
            mock_conn.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
            # Self-signed: subject == issuer
            mock_conn.getpeercert.return_value = _mock_cert_dict(
                subject="example.com", issuer="example.com"
            )
            mock_conn.getpeercert.side_effect = [
                b"fake_der_cert",
                _mock_cert_dict(subject="example.com", issuer="example.com"),
            ]
            mock_ctx.return_value.wrap_socket.return_value = mock_conn

            result = scan_fn("example.com")
            assert result["grade_input"]["self_signed"] is True


# ---------------------------------------------------------------------------
# Grade Input
# ---------------------------------------------------------------------------


class TestGradeInput:
    """Test grade_input dict is properly constructed."""

    def test_grade_input_keys_present(self, scan_fn):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_conn = MagicMock()
            mock_conn.version.return_value = "TLSv1.3"
            mock_conn.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
            mock_conn.getpeercert.return_value = _mock_cert_dict()
            mock_conn.getpeercert.side_effect = [
                b"fake_der_cert",
                _mock_cert_dict(),
            ]
            mock_ctx.return_value.wrap_socket.return_value = mock_conn

            result = scan_fn("example.com")
            assert "grade_input" in result
            grade = result["grade_input"]
            assert "tls_version_ok" in grade
            assert "cert_valid" in grade
            assert "cert_expiring_soon" in grade
            assert "strong_cipher" in grade
            assert "self_signed" in grade
