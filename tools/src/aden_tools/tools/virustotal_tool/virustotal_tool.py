"""
VirusTotal Tool - Threat intelligence and security scanning via VirusTotal API.

Supports:
- API key authentication (VIRUSTOTAL_API_KEY)

Use Cases:
- Scan IP addresses for malicious activity reports
- Check domain reputation and threat categorization
- Look up file hashes (MD5, SHA-1, SHA-256) against 70+ antivirus engines

API Reference: https://docs.virustotal.com/reference/overview
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

VT_API_BASE = "https://www.virustotal.com/api/v3"


class _VirusTotalClient:
    """Internal client wrapping VirusTotal API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-apikey": self._api_key}

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid VirusTotal API key"}
        if response.status_code == 403:
            return {"error": "Forbidden. Check your API key permissions."}
        if response.status_code == 404:
            return {"error": "Resource not found on VirusTotal"}
        if response.status_code == 429:
            return {
                "error": (
                    "VirusTotal rate limit exceeded. Free tier allows 4 requests/minute, 500/day."
                )
            }
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"VirusTotal API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def _extract_stats(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract analysis stats from a VT response object."""
        attrs = data.get("data", {}).get("attributes", {})
        stats = attrs.get("last_analysis_stats", {})
        return {
            "malicious": stats.get("malicious", 0),
            "suspicious": stats.get("suspicious", 0),
            "undetected": stats.get("undetected", 0),
            "harmless": stats.get("harmless", 0),
            "timeout": stats.get("timeout", 0),
        }

    def scan_ip(self, ip: str) -> dict[str, Any]:
        """Get IP address report from VirusTotal."""
        response = httpx.get(
            f"{VT_API_BASE}/ip_addresses/{ip}",
            headers=self._headers,
            timeout=30.0,
        )
        result = self._handle_response(response)
        if "error" in result:
            return result

        attrs = result.get("data", {}).get("attributes", {})
        stats = self._extract_stats(result)
        return {
            "ip": ip,
            "as_owner": attrs.get("as_owner", ""),
            "country": attrs.get("country", ""),
            "reputation": attrs.get("reputation", 0),
            "analysis_stats": stats,
            "last_analysis_date": attrs.get("last_analysis_date"),
            "network": attrs.get("network", ""),
            "whois": attrs.get("whois", "")[:500] if attrs.get("whois") else None,
        }

    def scan_domain(self, domain: str) -> dict[str, Any]:
        """Get domain report from VirusTotal."""
        response = httpx.get(
            f"{VT_API_BASE}/domains/{domain}",
            headers=self._headers,
            timeout=30.0,
        )
        result = self._handle_response(response)
        if "error" in result:
            return result

        attrs = result.get("data", {}).get("attributes", {})
        stats = self._extract_stats(result)
        categories = attrs.get("categories", {})
        return {
            "domain": domain,
            "reputation": attrs.get("reputation", 0),
            "registrar": attrs.get("registrar", ""),
            "creation_date": attrs.get("creation_date"),
            "categories": categories,
            "analysis_stats": stats,
            "last_analysis_date": attrs.get("last_analysis_date"),
            "last_dns_records": attrs.get("last_dns_records", [])[:10],
            "whois": attrs.get("whois", "")[:500] if attrs.get("whois") else None,
        }

    def scan_hash(self, file_hash: str) -> dict[str, Any]:
        """Get file report by hash (MD5, SHA-1, or SHA-256)."""
        response = httpx.get(
            f"{VT_API_BASE}/files/{file_hash}",
            headers=self._headers,
            timeout=30.0,
        )
        result = self._handle_response(response)
        if "error" in result:
            return result

        attrs = result.get("data", {}).get("attributes", {})
        stats = self._extract_stats(result)
        names = attrs.get("names", [])
        return {
            "hash": file_hash,
            "md5": attrs.get("md5", ""),
            "sha1": attrs.get("sha1", ""),
            "sha256": attrs.get("sha256", ""),
            "file_type": attrs.get("type_description", ""),
            "size": attrs.get("size", 0),
            "names": names[:10] if names else [],
            "reputation": attrs.get("reputation", 0),
            "analysis_stats": stats,
            "last_analysis_date": attrs.get("last_analysis_date"),
            "signature_info": attrs.get("signature_info", {}),
            "tags": attrs.get("tags", [])[:20],
        }


def _resolve_api_key(credentials: CredentialStoreAdapter | None) -> str | None:
    """Resolve VirusTotal API key from credentials or environment."""
    if credentials is not None:
        try:
            key = credentials.get("virustotal")
            if key:
                return key
        except Exception:
            pass
    return os.environ.get("VIRUSTOTAL_API_KEY")


def _validate_ip(ip: str) -> bool:
    """Basic IPv4/IPv6 validation."""
    ipv4 = re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip)
    if ipv4:
        return all(0 <= int(octet) <= 255 for octet in ip.split("."))
    # Simple IPv6 check
    return ":" in ip and all(c in "0123456789abcdefABCDEF:" for c in ip)


def _validate_domain(domain: str) -> bool:
    """Basic domain validation."""
    return bool(
        re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$", domain)
    )


def _validate_hash(file_hash: str) -> bool:
    """Validate MD5, SHA-1, or SHA-256 hash."""
    return bool(re.match(r"^[a-fA-F0-9]{32}$|^[a-fA-F0-9]{40}$|^[a-fA-F0-9]{64}$", file_hash))


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register VirusTotal tools with the MCP server."""

    @mcp.tool()
    def vt_scan_ip(ip: str) -> dict[str, Any]:
        """
        Scan an IP address using VirusTotal threat intelligence.

        Retrieves aggregate anti-virus vendor reports and reputation scores
        for the given IP address. Useful for investigating suspicious network
        activity or validating IP addresses in security workflows.

        Args:
            ip: IPv4 or IPv6 address to scan (e.g., "8.8.8.8").

        Returns:
            Dict with IP reputation, analysis stats (malicious/suspicious/harmless
            counts from 70+ AV engines), AS owner, country, and WHOIS excerpt.
        """
        api_key = _resolve_api_key(credentials)
        if not api_key:
            return {
                "error": (
                    "VirusTotal API key not configured. "
                    "Set VIRUSTOTAL_API_KEY or add 'virustotal' to the credential store."
                )
            }
        if not _validate_ip(ip):
            return {"error": f"Invalid IP address format: {ip}"}
        client = _VirusTotalClient(api_key)
        return client.scan_ip(ip)

    @mcp.tool()
    def vt_scan_domain(domain: str) -> dict[str, Any]:
        """
        Scan a domain using VirusTotal threat intelligence.

        Retrieves aggregate anti-virus vendor reports, reputation scores,
        and categorization for the given domain. Useful for investigating
        phishing, malware distribution, or suspicious domains.

        Args:
            domain: Domain name to scan (e.g., "example.com"). Do not include
                    protocol or path.

        Returns:
            Dict with domain reputation, analysis stats (malicious/suspicious/harmless
            counts), registrar, categories, DNS records, and WHOIS excerpt.
        """
        api_key = _resolve_api_key(credentials)
        if not api_key:
            return {
                "error": (
                    "VirusTotal API key not configured. "
                    "Set VIRUSTOTAL_API_KEY or add 'virustotal' to the credential store."
                )
            }
        # Clean domain input
        domain = domain.replace("https://", "").replace("http://", "").strip("/")
        domain = domain.split("/")[0]
        if ":" in domain:
            domain = domain.split(":")[0]
        if not _validate_domain(domain):
            return {"error": f"Invalid domain format: {domain}"}
        client = _VirusTotalClient(api_key)
        return client.scan_domain(domain)

    @mcp.tool()
    def vt_scan_hash(file_hash: str) -> dict[str, Any]:
        """
        Look up a file hash using VirusTotal threat intelligence.

        Retrieves aggregate anti-virus scan results for a file identified
        by its MD5, SHA-1, or SHA-256 hash. Useful for checking if a file
        is known malware or has been flagged by security vendors.

        Args:
            file_hash: MD5 (32 chars), SHA-1 (40 chars), or SHA-256 (64 chars)
                       hash of the file to look up.

        Returns:
            Dict with file metadata, analysis stats (malicious/suspicious/harmless
            counts from 70+ AV engines), file type, size, known names, and tags.
        """
        api_key = _resolve_api_key(credentials)
        if not api_key:
            return {
                "error": (
                    "VirusTotal API key not configured. "
                    "Set VIRUSTOTAL_API_KEY or add 'virustotal' to the credential store."
                )
            }
        file_hash = file_hash.strip()
        if not _validate_hash(file_hash):
            return {
                "error": (
                    f"Invalid hash format: {file_hash}. "
                    "Provide an MD5 (32), SHA-1 (40), or SHA-256 (64) hex string."
                )
            }
        client = _VirusTotalClient(api_key)
        return client.scan_hash(file_hash)
