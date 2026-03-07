from __future__ import annotations

import httpx
from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register IP Geolocation tools with the MCP server."""

    @mcp.tool()
    def ip_geolocation_lookup(ip: str) -> dict:
        """Get geolocation data for any IP address.

        Args:
            ip: IP address to look up (e.g. 8.8.8.8)

        Returns:
            Dictionary with country, city, region, timezone, ISP, lat, lon
        """
        try:
            url = f"http://ip-api.com/json/{ip}"
            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "fail":
                return {"error": data.get("message", "Lookup failed")}
            return data
        except httpx.HTTPStatusError as e:
            return {"error": f"API request failed: {e.response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def ip_geolocation_get_my_ip() -> dict:
        """Get geolocation data for the current machine IP address.

        Returns:
            Dictionary with country, city, region, timezone, ISP, lat, lon
        """
        try:
            url = "http://ip-api.com/json"
            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "fail":
                return {"error": data.get("message", "Lookup failed")}
            return data
        except httpx.HTTPStatusError as e:
            return {"error": f"API request failed: {e.response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
