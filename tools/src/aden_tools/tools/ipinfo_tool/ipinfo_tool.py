from __future__ import annotations

import httpx
from fastmcp import FastMCP


def register_tools(mcp: FastMCP, credentials: dict | None = None) -> None:
    """Register IPInfo tools with the MCP server."""

    token = (credentials or {}).get("ipinfo", "")

    @mcp.tool()
    def ipinfo_get_ip_details(ip: str) -> dict:
        """Get geolocation and network details for any IP address.

        Args:
            ip: IP address to look up (e.g. 8.8.8.8)

        Returns:
            Dictionary with ip, city, region, country, org, timezone, loc
        """
        try:
            url = f"https://ipinfo.io/{ip}"
            params = {"token": token} if token else {}
            response = httpx.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"API request failed: {e.response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def ipinfo_get_my_ip() -> dict:
        """Get geolocation and network details for the current machine's IP address.

        Returns:
            Dictionary with ip, city, region, country, org, timezone, loc
        """
        try:
            url = "https://ipinfo.io/json"
            params = {"token": token} if token else {}
            response = httpx.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"API request failed: {e.response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
