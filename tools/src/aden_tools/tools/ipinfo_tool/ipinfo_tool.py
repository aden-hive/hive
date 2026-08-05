"""
IP Info Tool - IP geolocation and network intelligence via ipinfo.io.

Free tier: 50,000 requests/month, commercial use allowed (CC BY-SA 4.0).
Requires a free API token from https://ipinfo.io/signup

Supports:
- Get details for any IP address
- Get details for the caller's own IP
- Bulk lookup for multiple IPs

API docs: https://ipinfo.io/developers
"""

from __future__ import annotations

import ipaddress
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

IPINFO_API_BASE = "https://ipinfo.io"


def _validate_ip(ip: str) -> bool:
    """Validate that a string is a valid IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    """Get IPInfo token from credential store or environment."""
    if credentials is not None:
        try:
            token = credentials.get("ipinfo")
            if token:
                return token
        except Exception:
            pass
    return os.getenv("IPINFO_TOKEN")


def _handle_response(response: httpx.Response) -> dict[str, Any]:
    """Handle HTTP response from ipinfo.io API."""
    if response.status_code == 200:
        data = response.json()
        return {"success": True, "data": data}
    elif response.status_code == 401:
        return {"error": "Invalid or expired API token. Check your IPINFO_TOKEN."}
    elif response.status_code == 403:
        return {"error": "Forbidden. Your token may not have access to this endpoint."}
    elif response.status_code == 404:
        return {"error": "IP address not found."}
    elif response.status_code == 429:
        return {"error": "Rate limit exceeded. Free tier allows 50,000 requests/month."}
    else:
        return {
            "error": f"IPInfo API error: HTTP {response.status_code}",
            "details": response.text[:500],
        }


def register_tools(
    mcp: FastMCP, credentials: CredentialStoreAdapter | None = None
) -> None:
    """Register IPInfo tools with the MCP server."""

    @mcp.tool()
    def ipinfo_get_ip_details(ip: str) -> dict[str, Any]:
        """
        Get geolocation and network details for an IP address.

        Args:
            ip: IPv4 or IPv6 address to look up (e.g., "8.8.8.8", "2001:4860:4860::8888")

        Returns:
            Dict with location data (city, region, country, coordinates),
            network info (org, timezone, hostname), and postal code.
        """
        if not ip or not ip.strip():
            return {"error": "IP address is required"}

        ip = ip.strip()

        if not _validate_ip(ip):
            return {
                "error": f"Invalid IP address: {ip}. Must be a valid IPv4 or IPv6 address."
            }

        token = _get_token(credentials)
        url = f"{IPINFO_API_BASE}/{ip}/json"
        if token:
            url += f"?token={token}"

        try:
            response = httpx.get(
                url,
                timeout=10.0,
                headers={"User-Agent": "AdenAgentFramework/1.0 (https://adenhq.com)"},
            )
            result = _handle_response(response)
            if "error" in result:
                return result

            data = result["data"]
            return {
                "ip": data.get("ip", ip),
                "city": data.get("city", ""),
                "region": data.get("region", ""),
                "country": data.get("country", ""),
                "location": data.get("loc", ""),
                "org": data.get("org", ""),
                "timezone": data.get("timezone", ""),
                "hostname": data.get("hostname", ""),
                "postal": data.get("postal", ""),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out. Please try again."}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e!s}"}
        except Exception as e:
            return {"error": f"Unexpected error: {e!s}"}

    @mcp.tool()
    def ipinfo_get_my_ip() -> dict[str, Any]:
        """
        Get geolocation and network details for this machine's public IP address.

        Returns:
            Dict with location data (city, region, country, coordinates),
            network info (org, timezone, hostname), and postal code.
        """
        token = _get_token(credentials)
        url = f"{IPINFO_API_BASE}/json"
        if token:
            url += f"?token={token}"

        try:
            response = httpx.get(
                url,
                timeout=10.0,
                headers={"User-Agent": "AdenAgentFramework/1.0 (https://adenhq.com)"},
            )
            result = _handle_response(response)
            if "error" in result:
                return result

            data = result["data"]
            return {
                "ip": data.get("ip", ""),
                "city": data.get("city", ""),
                "region": data.get("region", ""),
                "country": data.get("country", ""),
                "location": data.get("loc", ""),
                "org": data.get("org", ""),
                "timezone": data.get("timezone", ""),
                "hostname": data.get("hostname", ""),
                "postal": data.get("postal", ""),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out. Please try again."}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e!s}"}
        except Exception as e:
            return {"error": f"Unexpected error: {e!s}"}

    @mcp.tool()
    def ipinfo_bulk_lookup(ips: str) -> dict[str, Any]:
        """
        Look up details for multiple IP addresses in a single request (max 100).

        Args:
            ips: Comma-separated list of IP addresses
                 (e.g., "8.8.8.8,1.1.1.1,208.67.222.222")

        Returns:
            Dict with a list of results for each IP, or an error if validation fails.
        """
        if not ips or not ips.strip():
            return {"error": "IP address list is required"}

        ip_list = [ip.strip() for ip in ips.split(",") if ip.strip()]

        if not ip_list:
            return {"error": "No valid IP addresses provided"}

        if len(ip_list) > 100:
            return {"error": "Maximum 100 IP addresses per request"}

        # Validate all IPs first
        invalid = [ip for ip in ip_list if not _validate_ip(ip)]
        if invalid:
            return {
                "error": f"Invalid IP addresses: {', '.join(invalid)}",
                "valid_count": len(ip_list) - len(invalid),
                "invalid_count": len(invalid),
            }

        token = _get_token(credentials)
        results = []

        for ip in ip_list:
            url = f"{IPINFO_API_BASE}/{ip}/json"
            if token:
                url += f"?token={token}"

            try:
                response = httpx.get(
                    url,
                    timeout=10.0,
                    headers={
                        "User-Agent": "AdenAgentFramework/1.0 (https://adenhq.com)"
                    },
                )
                result = _handle_response(response)
                if "error" in result:
                    results.append({"ip": ip, "error": result["error"]})
                else:
                    data = result["data"]
                    results.append(
                        {
                            "ip": data.get("ip", ip),
                            "city": data.get("city", ""),
                            "region": data.get("region", ""),
                            "country": data.get("country", ""),
                            "location": data.get("loc", ""),
                            "org": data.get("org", ""),
                            "timezone": data.get("timezone", ""),
                        }
                    )
            except httpx.TimeoutException:
                results.append({"ip": ip, "error": "Request timed out"})
            except httpx.RequestError as e:
                results.append({"ip": ip, "error": f"Network error: {e!s}"})
            except Exception as e:
                results.append({"ip": ip, "error": f"Unexpected error: {e!s}"})

        return {
            "results": results,
            "count": len(results),
            "success_count": sum(1 for r in results if "error" not in r),
            "error_count": sum(1 for r in results if "error" in r),
        }
