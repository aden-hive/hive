"""
VirusTotal Tool - Threat intelligence & security scanning via VirusTotal API.

Supports:
- API key authentication (VIRUSTOTAL_API_KEY)

Use Cases:
- Scan IP addresses for malicious activity and reputation
- Analyze domains for security threats and DNS records
- Look up file hashes (MD5/SHA1/SHA256) for malware detection

API Reference: https://docs.virustotal.com/reference/overview
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

_VT_BASE = "https://www.virustotal.com/api/v3"


class _VirusTotalClient:
    """Internal client wrapping VirusTotal API v3 calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    def _request(self, path: str) -> dict[str, Any]:
        """Make an authenticated GET request to VT API."""
        url = f"{_VT_BASE}{path}"
        req = Request(url, headers={"x-apikey": self._api_key})
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as exc:
            body = exc.read().decode() if exc.fp else ""
            if exc.code == 401:
                return {"error": "Invalid API key. Check your VIRUSTOTAL_API_KEY."}
            if exc.code == 404:
                return {"error": f"Resource not found: {path}"}
            if exc.code == 429:
                return {"error": "Rate limit exceeded. Free tier: 4 req/min, 500 req/day."}
            return {"error": f"HTTP {exc.code}: {body[:500]}"}
        except URLError as exc:
            return {"error": f"Connection error: {exc.reason}"}

    # --- IP Address ---

    def scan_ip(self, ip: str) -> dict[str, Any]:
        """Get IP address report including reputation and analysis stats."""
        data = self._request(f"/ip_addresses/{ip}")
        if "error" in data:
            return data
        return self._format_ip(data)

    def _format_ip(self, raw: dict[str, Any]) -> dict[str, Any]:
        attrs = raw.get("data", {}).get("attributes", {})
        stats = attrs.get("last_analysis_stats", {})
        return {
            "ip": raw.get("data", {}).get("id", ""),
            "reputation": attrs.get("reputation", 0),
            "country": attrs.get("country", "unknown"),
            "as_owner": attrs.get("as_owner", "unknown"),
            "network": attrs.get("network", ""),
            "analysis_stats": {
                "malicious": stats.get("malicious", 0),
                "suspicious": stats.get("suspicious", 0),
                "harmless": stats.get("harmless", 0),
                "undetected": stats.get("undetected", 0),
            },
            "total_votes": {
                "malicious": attrs.get("total_votes", {}).get("malicious", 0),
                "harmless": attrs.get("total_votes", {}).get("harmless", 0),
            },
        }

    # --- Domain ---

    def scan_domain(self, domain: str) -> dict[str, Any]:
        """Get domain report including reputation, DNS records, and analysis."""
        data = self._request(f"/domains/{domain}")
        if "error" in data:
            return data
        return self._format_domain(data)

    def _format_domain(self, raw: dict[str, Any]) -> dict[str, Any]:
        attrs = raw.get("data", {}).get("attributes", {})
        stats = attrs.get("last_analysis_stats", {})
        return {
            "domain": raw.get("data", {}).get("id", ""),
            "reputation": attrs.get("reputation", 0),
            "registrar": attrs.get("registrar", "unknown"),
            "creation_date": attrs.get("creation_date", 0),
            "last_dns_records": [
                {"type": r.get("type", ""), "value": r.get("value", "")}
                for r in attrs.get("last_dns_records", [])[:10]
            ],
            "categories": attrs.get("categories", {}),
            "analysis_stats": {
                "malicious": stats.get("malicious", 0),
                "suspicious": stats.get("suspicious", 0),
                "harmless": stats.get("harmless", 0),
                "undetected": stats.get("undetected", 0),
            },
            "total_votes": {
                "malicious": attrs.get("total_votes", {}).get("malicious", 0),
                "harmless": attrs.get("total_votes", {}).get("harmless", 0),
            },
        }

    # --- File Hash ---

    def scan_hash(self, file_hash: str) -> dict[str, Any]:
        """Get file report by hash (MD5, SHA1, or SHA256)."""
        data = self._request(f"/files/{file_hash}")
        if "error" in data:
            return data
        return self._format_file(data)

    def _format_file(self, raw: dict[str, Any]) -> dict[str, Any]:
        attrs = raw.get("data", {}).get("attributes", {})
        stats = attrs.get("last_analysis_stats", {})
        return {
            "sha256": attrs.get("sha256", ""),
            "sha1": attrs.get("sha1", ""),
            "md5": attrs.get("md5", ""),
            "file_type": attrs.get("type_description", "unknown"),
            "file_size": attrs.get("size", 0),
            "meaningful_name": attrs.get("meaningful_name", ""),
            "reputation": attrs.get("reputation", 0),
            "analysis_stats": {
                "malicious": stats.get("malicious", 0),
                "suspicious": stats.get("suspicious", 0),
                "harmless": stats.get("harmless", 0),
                "undetected": stats.get("undetected", 0),
                "failure": stats.get("type-unsupported", 0),
            },
            "popular_threat_classification": attrs.get("popular_threat_classification", {}),
            "tags": attrs.get("tags", [])[:20],
        }


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

_IP_RE = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$")
_DOMAIN_RE = re.compile(r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$")
_HASH_RE = re.compile(r"^[a-fA-F0-9]{32}$|^[a-fA-F0-9]{40}$|^[a-fA-F0-9]{64}$")


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tools(
    mcp: FastMCP,
    *,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register VirusTotal tools with the MCP server."""

    def _get_api_key() -> str | None:
        if credentials is not None:
            key = credentials.get("virustotal")
            if key:
                return key
        return os.getenv("VIRUSTOTAL_API_KEY")

    @mcp.tool()
    def vt_scan_ip(ip: str) -> str:
        """
        Scan an IP address using VirusTotal for threat intelligence.

        Returns reputation score, geolocation, network owner, and
        aggregated anti-virus vendor analysis results.

        Args:
            ip: IPv4 address to scan (e.g., "8.8.8.8")

        Returns:
            JSON string with IP reputation data and analysis statistics
        """
        if not _IP_RE.match(ip):
            return json.dumps({"error": f"Invalid IPv4 address: {ip}"})

        api_key = _get_api_key()
        if not api_key:
            return json.dumps(
                {
                    "error": "VIRUSTOTAL_API_KEY not set. Get one at https://www.virustotal.com/gui/join-us"
                }
            )

        client = _VirusTotalClient(api_key)
        result = client.scan_ip(ip)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def vt_scan_domain(domain: str) -> str:
        """
        Scan a domain using VirusTotal for threat intelligence.

        Returns reputation score, registrar, DNS records, category
        classifications, and aggregated analysis results.

        Args:
            domain: Domain name to scan (e.g., "example.com")

        Returns:
            JSON string with domain reputation data and analysis statistics
        """
        if not _DOMAIN_RE.match(domain):
            return json.dumps({"error": f"Invalid domain format: {domain}"})

        api_key = _get_api_key()
        if not api_key:
            return json.dumps(
                {
                    "error": "VIRUSTOTAL_API_KEY not set. Get one at https://www.virustotal.com/gui/join-us"
                }
            )

        client = _VirusTotalClient(api_key)
        result = client.scan_domain(domain)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def vt_scan_hash(file_hash: str) -> str:
        """
        Look up a file hash on VirusTotal for malware detection.

        Accepts MD5 (32 chars), SHA1 (40 chars), or SHA256 (64 chars)
        hashes. Returns file metadata, threat classification, and
        aggregated anti-virus vendor scan results.

        Args:
            file_hash: MD5, SHA1, or SHA256 hash of the file

        Returns:
            JSON string with file analysis data and threat classification
        """
        if not _HASH_RE.match(file_hash):
            return json.dumps(
                {
                    "error": f"Invalid hash format. Expected MD5 (32), SHA1 (40), "
                    f"or SHA256 (64) hex chars, got: {file_hash}"
                }
            )

        api_key = _get_api_key()
        if not api_key:
            return json.dumps(
                {
                    "error": "VIRUSTOTAL_API_KEY not set. Get one at https://www.virustotal.com/gui/join-us"
                }
            )

        client = _VirusTotalClient(api_key)
        result = client.scan_hash(file_hash)
        return json.dumps(result, indent=2)
