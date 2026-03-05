"""Tests for ssl_tls_scanner - SSL/TLS configuration and certificate analysis."""

import ssl as _ssl
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


def _make_ssl_conn(
    version="TLSv1.3",
    cipher=("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256),
    cert_dict=None,
    cert_der=b"fakecert",
):
    """Build a mock SSL connection object."""
    conn = MagicMock()
    conn.version.return_value = version
    conn.cipher.return_value = cipher

    now = datetime.now(UTC)
    not_after = now + timedelta(days=180)
    default_cert = {
        "subject": ((("commonName", "example.com"),),),
        "issuer": ((("commonName", "Let's Encrypt"),),),
        "notBefore": "Jan  1 00:00:00 2025 GMT",
        "notAfter": not_after.strftime("%b %d %H:%M:%S %Y GMT"),
        "subjectAltName": (("DNS", "example.com"),),
    }
    conn.getpeercert.side_effect = lambda binary_form=False: (
        cert_der if binary_form else (cert_dict or default_cert)
    )
    return conn


class TestSslTlsScanConnectionErrors:
    def test_timeout_returns_error(self, tool_fns):
        with patch("aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner.ssl") as mock_ssl:
            mock_ssl.SSLCertVerificationError = _ssl.SSLCertVerificationError
            mock_ctx = MagicMock()
            mock_ssl.create_default_context.return_value = mock_ctx
            conn = MagicMock()
            conn.connect.side_effect = TimeoutError()
            mock_ctx.wrap_socket.return_value = conn
            result = tool_fns["ssl_tls_scan"](hostname="example.com")
        assert "error" in result

    def test_connection_refused_returns_error(self, tool_fns):
        with patch("aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner.ssl") as mock_ssl:
            mock_ssl.SSLCertVerificationError = _ssl.SSLCertVerificationError
            mock_ctx = MagicMock()
            mock_ssl.create_default_context.return_value = mock_ctx
            conn = MagicMock()
            conn.connect.side_effect = ConnectionRefusedError()
            mock_ctx.wrap_socket.return_value = conn
            result = tool_fns["ssl_tls_scan"](hostname="example.com")
        assert "error" in result


class TestSslTlsScanSuccessful:
    def test_secure_tls13_returns_grade_input(self, tool_fns):
        conn = _make_ssl_conn(version="TLSv1.3")
        with (
            patch("aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner.ssl") as mock_ssl,
            patch("aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner.socket") as mock_socket,
        ):
            mock_socket.socket.return_value = MagicMock()
            mock_ssl.SSLCertVerificationError = Exception
            mock_ctx = MagicMock()
            mock_ssl.create_default_context.return_value = mock_ctx
            mock_ctx.wrap_socket.return_value = conn
            result = tool_fns["ssl_tls_scan"](hostname="example.com")

        assert "grade_input" in result
        assert result["grade_input"]["tls_version_ok"] is True
        assert result["tls_version"] == "TLSv1.3"

    def test_insecure_tls10_flagged(self, tool_fns):
        conn = _make_ssl_conn(version="TLSv1.0")
        with (
            patch("aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner.ssl") as mock_ssl,
            patch("aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner.socket") as mock_socket,
        ):
            mock_socket.socket.return_value = MagicMock()
            mock_ssl.SSLCertVerificationError = Exception
            mock_ctx = MagicMock()
            mock_ssl.create_default_context.return_value = mock_ctx
            mock_ctx.wrap_socket.return_value = conn
            result = tool_fns["ssl_tls_scan"](hostname="example.com")

        assert result["grade_input"]["tls_version_ok"] is False
        assert any("Insecure TLS" in issue["finding"] for issue in result["issues"])

    def test_hostname_strips_protocol_prefix(self, tool_fns):
        conn = _make_ssl_conn()
        with (
            patch("aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner.ssl") as mock_ssl,
            patch("aden_tools.tools.ssl_tls_scanner.ssl_tls_scanner.socket") as mock_socket,
        ):
            mock_socket.socket.return_value = MagicMock()
            mock_ssl.SSLCertVerificationError = Exception
            mock_ctx = MagicMock()
            mock_ssl.create_default_context.return_value = mock_ctx
            mock_ctx.wrap_socket.return_value = conn
            result = tool_fns["ssl_tls_scan"](hostname="https://example.com")

        assert "error" not in result
        assert result["hostname"] == "example.com"
