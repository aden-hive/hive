"""
SSL/TLS Scanner - Analyze SSL/TLS configuration and certificate security.

Performs non-intrusive analysis of a host's TLS setup including protocol version,
cipher suite, certificate validity, and common misconfigurations.
Uses only Python stdlib (ssl + socket) — no external dependencies.
"""

from __future__ import annotations

import hashlib
import socket
import ssl
from datetime import UTC, datetime

from fastmcp import FastMCP

# Weak ciphers that should be flagged
WEAK_CIPHERS = {
    "RC4",
    "DES",
    "3DES",
    "MD5",
    "NULL",
    "EXPORT",
    "anon",
}

# TLS versions considered insecure
INSECURE_TLS_VERSIONS = {"TLSv1", "TLSv1.0", "TLSv1.1", "SSLv2", "SSLv3"}


def register_tools(mcp: FastMCP) -> None:
    """Register SSL/TLS scanning tools with the MCP server."""

    @mcp.tool()
    def ssl_tls_scan(hostname: str, port: int = 443) -> dict:
        """
        Scan a host's SSL/TLS configuration and certificate.

        Performs a non-intrusive check of TLS version, cipher suite, certificate
        validity, expiry, chain details, and common misconfigurations.
        Uses only Python stdlib — no external tools required.

        Args:
            hostname: Domain name to scan (e.g., "example.com"). Do not include protocol.
            port: Port to connect to (default 443).

        Returns:
            Dict with TLS version, cipher, certificate details, issues found,
            and grade_input for the risk_scorer tool.
        """
        # Strip protocol prefix if provided
        hostname = hostname.replace("https://", "").replace("http://", "").strip("/")
        # Strip path
        hostname = hostname.split("/")[0]
        # Strip port from hostname if embedded
        if ":" in hostname:
            hostname = hostname.split(":")[0]

        issues: list[dict] = []

        try:
            # Create SSL context that accepts all certs (we want to inspect, not reject)
            ctx = ssl.create_default_context()
            # We still verify but catch errors to report them as findings
            conn = ctx.wrap_socket(socket.socket(), server_hostname=hostname)
            conn.settimeout(10)

            try:
                conn.connect((hostname, port))
            except ssl.SSLCertVerificationError as e:
                # Still try to gather info with verification disabled
                ctx_noverify = ssl.create_default_context()
                ctx_noverify.check_hostname = False
                ctx_noverify.verify_mode = ssl.CERT_NONE
                conn = ctx_noverify.wrap_socket(socket.socket(), server_hostname=hostname)
                conn.settimeout(10)
                conn.connect((hostname, port))
                issues.append(
                    {
                        "severity": "critical",
                        "finding": f"SSL certificate verification failed: {e}",
                        "remediation": (
                            "Obtain a valid certificate from a trusted CA. "
                            "Let's Encrypt provides free certificates."
                        ),
                    }
                )

            # Gather TLS info
            tls_version = conn.version() or "unknown"
            cipher_info = conn.cipher()
            cipher_name = cipher_info[0] if cipher_info else "unknown"
            cipher_bits = cipher_info[2] if cipher_info else 0

            # Get certificate
            cert_der = conn.getpeercert(binary_form=True)
            cert_dict = conn.getpeercert()
            conn.close()

        except TimeoutError:
            return {"error": f"Connection to {hostname}:{port} timed out"}
        except ConnectionRefusedError:
            return {"error": f"Connection to {hostname}:{port} refused. Port may be closed."}
        except OSError as e:
            return {"error": f"Connection failed: {e}"}

        # Parse certificate details
        subject = _format_dn(cert_dict.get("subject", ()))
        issuer = _format_dn(cert_dict.get("issuer", ()))

        not_before_str = cert_dict.get("notBefore", "")
        not_after_str = cert_dict.get("notAfter", "")

        not_before = _parse_cert_date(not_before_str)
        not_after = _parse_cert_date(not_after_str)
        now = datetime.now(UTC)

        days_until_expiry = (not_after - now).days if not_after else None

        # SAN (Subject Alternative Names)
        san_list = []
        for san_type, san_value in cert_dict.get("subjectAltName", ()):
            if san_type == "DNS":
                san_list.append(san_value)

        # Self-signed check
        self_signed = subject == issuer

        # Certificate fingerprint
        cert_sha256 = hashlib.sha256(cert_der).hexdigest() if cert_der else ""

        # --- Check for issues ---

        # TLS version
        tls_version_ok = tls_version not in INSECURE_TLS_VERSIONS
        if not tls_version_ok:
            issues.append(
                {
                    "severity": "high",
                    "finding": f"Insecure TLS version: {tls_version}",
                    "remediation": (
                        "Disable TLS 1.0 and 1.1 in your server configuration. "
                        "Use TLS 1.2 or 1.3 only."
                    ),
                }
            )

        # Cipher strength
        strong_cipher = True
        if any(weak in cipher_name.upper() for weak in WEAK_CIPHERS):
            strong_cipher = False
            issues.append(
                {
                    "severity": "high",
                    "finding": f"Weak cipher suite: {cipher_name}",
                    "remediation": (
                        "Configure your server to use strong cipher suites only. "
                        "Prefer AES-GCM and ChaCha20-Poly1305."
                    ),
                }
            )
        if cipher_bits and cipher_bits < 128:
            strong_cipher = False
            issues.append(
                {
                    "severity": "high",
                    "finding": f"Cipher key length too short: {cipher_bits} bits",
                    "remediation": "Use cipher suites with at least 128-bit keys.",
                }
            )

        # Certificate validity
        cert_valid = True
        cert_expiring_soon = False

        if not_after and now > not_after:
            cert_valid = False
            issues.append(
                {
                    "severity": "critical",
                    "finding": "SSL certificate has expired",
                    "remediation": "Renew the SSL certificate immediately.",
                }
            )
        elif days_until_expiry is not None and days_until_expiry <= 30:
            cert_expiring_soon = True
            issues.append(
                {
                    "severity": "medium",
                    "finding": f"SSL certificate expires in {days_until_expiry} days",
                    "remediation": "Renew the SSL certificate before it expires.",
                }
            )

        if self_signed:
            cert_valid = False
            issues.append(
                {
                    "severity": "high",
                    "finding": "Self-signed certificate detected",
                    "remediation": (
                        "Replace with a certificate from a trusted CA. "
                        "Let's Encrypt provides free certificates."
                    ),
                }
            )

        return {
            "hostname": hostname,
            "port": port,
            "tls_version": tls_version,
            "cipher": cipher_name,
            "cipher_bits": cipher_bits,
            "certificate": {
                "subject": subject,
                "issuer": issuer,
                "not_before": not_before.isoformat() if not_before else not_before_str,
                "not_after": not_after.isoformat() if not_after else not_after_str,
                "days_until_expiry": days_until_expiry,
                "san": san_list,
                "self_signed": self_signed,
                "sha256_fingerprint": cert_sha256,
            },
            "issues": issues,
            "grade_input": {
                "tls_version_ok": tls_version_ok,
                "cert_valid": cert_valid,
                "cert_expiring_soon": cert_expiring_soon,
                "strong_cipher": strong_cipher,
                "self_signed": self_signed,
            },
        }


def _format_dn(dn_tuple: tuple) -> str:
    """Format a certificate distinguished name tuple into a readable string."""
    parts = []
    for rdn in dn_tuple:
        for attr_type, attr_value in rdn:
            parts.append(f"{attr_type}={attr_value}")
    return ", ".join(parts)


def _parse_cert_date(date_str: str) -> datetime | None:
    """Parse a certificate date string into a datetime object."""
    if not date_str:
        return None
    # OpenSSL format: "Jan  1 00:00:00 2025 GMT"
    for fmt in ("%b %d %H:%M:%S %Y %Z", "%b  %d %H:%M:%S %Y %Z"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
