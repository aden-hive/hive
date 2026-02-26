"""
Cloudflare Tool - Manage DNS records, zones, and cache via Cloudflare API v4.

Supports:
- API Token authentication (CLOUDFLARE_API_TOKEN)

API Reference: https://developers.cloudflare.com/api
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

CF_API_BASE = "https://api.cloudflare.com/client/v4"


class _CloudflareClient:
    """Internal client wrapping Cloudflare API v4 calls."""

    def __init__(self, token: str):
        self._token = token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle Cloudflare API response format."""
        if response.status_code == 401:
            return {"error": "Invalid or expired Cloudflare API token"}
        if response.status_code == 403:
            return {"error": "Forbidden - token lacks required permissions"}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                data = response.json()
                errors = data.get("errors", [])
                if errors:
                    msg = errors[0].get("message", response.text)
                else:
                    msg = response.text
            except Exception:
                msg = response.text
            return {"error": f"Cloudflare API error (HTTP {response.status_code}): {msg}"}

        try:
            data = response.json()
        except Exception:
            return {"error": "Failed to parse Cloudflare response"}

        if not data.get("success", False):
            errors = data.get("errors", [])
            if errors:
                msg = errors[0].get("message", "Unknown error")
                return {"error": f"Cloudflare API error: {msg}"}
            return {"error": "Cloudflare API returned an unsuccessful response"}

        return {"success": True, "data": data.get("result")}

    # --- Zones ---

    def list_zones(
        self,
        name: str | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """List zones (domains) on the account."""
        params: dict[str, Any] = {
            "page": max(1, page),
            "per_page": min(per_page, 50),
        }
        if name:
            params["name"] = name
        if status:
            params["status"] = status

        response = httpx.get(
            f"{CF_API_BASE}/zones",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_zone(self, zone_id: str) -> dict[str, Any]:
        """Get details about a specific zone."""
        response = httpx.get(
            f"{CF_API_BASE}/zones/{zone_id}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    # --- DNS Records ---

    def list_dns_records(
        self,
        zone_id: str,
        record_type: str | None = None,
        name: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """List DNS records for a zone."""
        params: dict[str, Any] = {
            "page": max(1, page),
            "per_page": min(per_page, 100),
        }
        if record_type:
            params["type"] = record_type
        if name:
            params["name"] = name

        response = httpx.get(
            f"{CF_API_BASE}/zones/{zone_id}/dns_records",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_dns_record(
        self,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        ttl: int = 1,
        proxied: bool = False,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """Create a new DNS record."""
        payload: dict[str, Any] = {
            "type": record_type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied,
        }
        if priority is not None:
            payload["priority"] = priority

        response = httpx.post(
            f"{CF_API_BASE}/zones/{zone_id}/dns_records",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_dns_record(
        self,
        zone_id: str,
        record_id: str,
        record_type: str,
        name: str,
        content: str,
        ttl: int = 1,
        proxied: bool = False,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """Update an existing DNS record."""
        payload: dict[str, Any] = {
            "type": record_type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied,
        }
        if priority is not None:
            payload["priority"] = priority

        response = httpx.patch(
            f"{CF_API_BASE}/zones/{zone_id}/dns_records/{record_id}",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def delete_dns_record(
        self,
        zone_id: str,
        record_id: str,
    ) -> dict[str, Any]:
        """Delete a DNS record."""
        response = httpx.delete(
            f"{CF_API_BASE}/zones/{zone_id}/dns_records/{record_id}",
            headers=self._headers,
            timeout=30.0,
        )
        # Cloudflare returns {"result": {"id": "..."}} on delete
        if response.status_code == 200:
            return {"success": True}
        return self._handle_response(response)

    # --- Cache ---

    def purge_cache(
        self,
        zone_id: str,
        purge_everything: bool = False,
        files: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Purge cached content for a zone."""
        payload: dict[str, Any] = {}
        if purge_everything:
            payload["purge_everything"] = True
        elif files:
            payload["files"] = files
        elif tags:
            payload["tags"] = tags
        else:
            return {"error": "Specify purge_everything=True, files, or tags"}

        response = httpx.post(
            f"{CF_API_BASE}/zones/{zone_id}/purge_cache",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Cloudflare tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Cloudflare API token from credentials or environment."""
        if credentials is not None:
            token = credentials.get("cloudflare")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('cloudflare'), got {type(token).__name__}"
                )
            return token
        return os.getenv("CLOUDFLARE_API_TOKEN")

    def _get_client() -> _CloudflareClient | dict[str, str]:
        """Get a Cloudflare client, or return an error dict if no credentials."""
        token = _get_token()
        if not token:
            return {
                "error": "Cloudflare credentials not configured",
                "help": (
                    "Set CLOUDFLARE_API_TOKEN environment variable "
                    "or configure via credential store. "
                    "Create a token at https://dash.cloudflare.com/profile/api-tokens"
                ),
            }
        return _CloudflareClient(token)

    # --- Zones ---

    @mcp.tool()
    def cloudflare_list_zones(
        name: str | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """
        List zones (domains) in the Cloudflare account.

        Use this to find zone IDs needed for DNS and cache operations.

        Args:
            name: Filter by domain name (e.g. "example.com")
            status: Filter by status ("active", "pending", "initializing")
            page: Page number for pagination (default 1)
            per_page: Results per page (1-50, default 20)

        Returns:
            Dict with list of zones or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_zones(name=name, status=status, page=page, per_page=per_page)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def cloudflare_get_zone(zone_id: str) -> dict:
        """
        Get details about a specific zone (domain).

        Returns zone status, nameservers, plan, and settings.

        Args:
            zone_id: The zone identifier (use cloudflare_list_zones to find it)

        Returns:
            Dict with zone details or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_zone(zone_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- DNS Records ---

    @mcp.tool()
    def cloudflare_list_dns_records(
        zone_id: str,
        record_type: str | None = None,
        name: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """
        List DNS records for a zone.

        Use this to see all records (A, AAAA, CNAME, MX, TXT, etc.) for a domain.

        Args:
            zone_id: The zone identifier
            record_type: Filter by record type ("A", "AAAA", "CNAME", "MX", "TXT", etc.)
            name: Filter by record name (e.g. "blog.example.com")
            page: Page number for pagination (default 1)
            per_page: Results per page (1-100, default 20)

        Returns:
            Dict with list of DNS records or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_dns_records(
                zone_id, record_type=record_type, name=name, page=page, per_page=per_page
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def cloudflare_create_dns_record(
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        ttl: int = 1,
        proxied: bool = False,
        priority: int | None = None,
    ) -> dict:
        """
        Create a new DNS record for a zone.

        Common record types:
        - A: Points to an IPv4 address (e.g. "192.0.2.1")
        - AAAA: Points to an IPv6 address
        - CNAME: Alias to another domain (e.g. "example.netlify.app")
        - MX: Mail server (requires priority)
        - TXT: Text record (e.g. SPF, DKIM, verification strings)

        Args:
            zone_id: The zone identifier
            record_type: DNS record type ("A", "AAAA", "CNAME", "MX", "TXT")
            name: Record name (e.g. "blog" for blog.example.com, or "@" for root)
            content: Record value (IP address, domain, or text)
            ttl: Time to live in seconds (1 = automatic, default 1)
            proxied: Whether to proxy through Cloudflare (orange cloud, default False)
            priority: Required for MX records (e.g. 10)

        Returns:
            Dict with created record details or error
        """
        valid_types = {"A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA", "PTR"}
        if record_type.upper() not in valid_types:
            return {
                "error": f"Invalid record type '{record_type}'",
                "valid_types": sorted(valid_types),
            }

        if record_type.upper() == "MX" and priority is None:
            return {"error": "MX records require a priority value (e.g. 10)"}

        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_dns_record(
                zone_id,
                record_type=record_type.upper(),
                name=name,
                content=content,
                ttl=ttl,
                proxied=proxied,
                priority=priority,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def cloudflare_update_dns_record(
        zone_id: str,
        record_id: str,
        record_type: str,
        name: str,
        content: str,
        ttl: int = 1,
        proxied: bool = False,
        priority: int | None = None,
    ) -> dict:
        """
        Update an existing DNS record.

        All fields are required since Cloudflare replaces the entire record.
        Use cloudflare_list_dns_records to find the record_id.

        Args:
            zone_id: The zone identifier
            record_id: The DNS record identifier
            record_type: DNS record type ("A", "AAAA", "CNAME", "MX", "TXT")
            name: Record name (e.g. "blog.example.com")
            content: New record value
            ttl: Time to live in seconds (1 = automatic)
            proxied: Whether to proxy through Cloudflare (default False)
            priority: Required for MX records

        Returns:
            Dict with updated record details or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.update_dns_record(
                zone_id,
                record_id=record_id,
                record_type=record_type.upper(),
                name=name,
                content=content,
                ttl=ttl,
                proxied=proxied,
                priority=priority,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def cloudflare_delete_dns_record(
        zone_id: str,
        record_id: str,
    ) -> dict:
        """
        Delete a DNS record from a zone.

        Use cloudflare_list_dns_records to find the record_id.

        Args:
            zone_id: The zone identifier
            record_id: The DNS record identifier to delete

        Returns:
            Dict with success status or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.delete_dns_record(zone_id, record_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Cache ---

    @mcp.tool()
    def cloudflare_purge_cache(
        zone_id: str,
        purge_everything: bool = False,
        files: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """
        Purge cached content for a zone.

        Use after deploying a new version of your site to ensure fresh content.
        Choose one of: purge_everything, files, or tags.

        Args:
            zone_id: The zone identifier
            purge_everything: If True, purge all cached files (use sparingly)
            files: List of URLs to purge (e.g. ["https://example.com/style.css"])
            tags: List of cache tags to purge (Enterprise only)

        Returns:
            Dict with purge result or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.purge_cache(
                zone_id,
                purge_everything=purge_everything,
                files=files,
                tags=tags,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
