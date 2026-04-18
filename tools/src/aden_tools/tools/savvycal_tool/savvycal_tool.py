"""
SavvyCal Tool - Smart, link-based scheduling for agents.

Supports:
- Scheduling link management (list, get, create, update, delete)
- Booking management (list, get, cancel)

API Reference: https://savvycal.com/docs/api
"""

from __future__ import annotations

import asyncio
import atexit
import functools
import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

_logger = logging.getLogger(__name__)

SAVVYCAL_API_BASE = "https://api.savvycal.com/v1"
DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0


def with_retry(max_retries: int = _MAX_RETRIES, base_delay: float = _RETRY_BASE_DELAY) -> Callable:
    """Decorator for exponential backoff on 429 errors."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            retries = 0
            while retries < max_retries:
                try:
                    return await func(*args, **kwargs)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        retries += 1
                        if retries == max_retries:
                            return {
                                "success": False,
                                "error": "Rate limit exceeded after retries.",
                                "status_code": 429,
                            }
                        # Add some jitter intentionally left out or simple exponential backoff
                        delay = base_delay * (2 ** (retries - 1))
                        _logger.warning("SavvyCal API rate limit hit. Retrying in %.1fs...", delay)
                        await asyncio.sleep(delay)
                    else:
                        # Handle other HTTP errors
                        if e.response.status_code == 401:
                            return {
                                "success": False,
                                "error": "Invalid or expired SavvyCal API key",
                                "status_code": 401,
                            }
                        if e.response.status_code == 403:
                            return {
                                "success": False,
                                "error": "Access forbidden. Check API key permissions.",
                                "status_code": 403,
                            }
                        if e.response.status_code == 404:
                            return {"success": False, "error": "Resource not found", "status_code": 404}

                        try:
                            detail = e.response.json().get("message", e.response.text[:500])
                        except Exception:
                            detail = e.response.text[:500]
                        return {
                            "success": False,
                            "error": f"SavvyCal API error: {detail}",
                            "status_code": e.response.status_code,
                        }
                except httpx.TimeoutException:
                    return {"success": False, "error": "Request timed out"}
                except httpx.RequestError as e:
                    return {"success": False, "error": f"Network error: {e}"}
            return {"success": False, "error": "Unknown error", "status_code": 500}
        return wrapper
    return decorator


class _SavvyCalClient:
    """Internal async client wrapping SavvyCal API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        # Truncate sensitive value for logs securely
        self._sanitized_key = f"...{api_key[-4:]}" if len(api_key) > 4 else "***"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)

    @with_retry()
    async def request(self, method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        """Make an HTTP request."""
        _logger.debug(f"SavvyCal request: {method} {endpoint} key={self._sanitized_key}")
        response = await self._client.request(
            method,
            f"{SAVVYCAL_API_BASE}{endpoint}",
            headers=self.headers,
            **kwargs,
        )
        response.raise_for_status()

        try:
            data = response.json()
            return {"success": True, "data": data}
        except Exception:
            return {"success": False, "error": "Malformed JSON in test response", "raw": response.text[:500]}

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


# Module-level cache to ensure TRUE connection pooling
_client_cache: dict[str, _SavvyCalClient] = {}

def _cleanup_clients() -> None:
    """Close all pooled clients on shutdown."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()

    for client in _client_cache.values():
        loop.run_until_complete(client.aclose())

atexit.register(_cleanup_clients)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register SavvyCal tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get SavvyCal API key from credential manager or environment."""
        if credentials is not None:
            try:
                api_key = credentials.get("savvycal")
                if api_key is not None and not isinstance(api_key, str):
                    return None
                return api_key
            except KeyError:
                pass
        return os.getenv("SAVVYCAL_API_KEY")

    def _get_client() -> _SavvyCalClient | dict[str, str]:
        """Return an authenticated client, or an error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "success": False,
                "error": "SavvyCal API key not configured",
                "help": (
                    "Set SAVVYCAL_API_KEY environment variable or configure "
                    "via the credential store"
                ),
            }

        # Reuse the existing client if we already have one for these credentials
        if api_key not in _client_cache:
            _client_cache[api_key] = _SavvyCalClient(api_key)

        return _client_cache[api_key]

    # --- Links ---

    @mcp.tool()
    async def savvycal_list_links() -> dict:
        """
        List all SavvyCal scheduling links for the authenticated user.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return await client.request("GET", "/links")

    @mcp.tool()
    async def savvycal_get_link(slug: str) -> dict:
        """
        Get a specific SavvyCal scheduling link by its slug.

        Args:
            slug: URL slug of the scheduling link (e.g., "intro-call")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not slug:
            return {"success": False, "error": "slug is required"}
        return await client.request("GET", f"/links/{slug}")

    @mcp.tool()
    async def savvycal_create_link(
        name: str,
        duration: int,
        event_type: str,
    ) -> dict:
        """
        Create a new SavvyCal scheduling link.

        Args:
            name: Human-readable name for the link (e.g., "30-min Intro Call")
            duration: Meeting duration in minutes (e.g., 30)
            event_type: SavvyCal event type slug (e.g., "one-on-one")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not name:
            return {"success": False, "error": "name is required"}
        if not duration or duration <= 0:
            return {"success": False, "error": "duration must be a positive integer"}
        if not event_type:
            return {"success": False, "error": "event_type is required"}

        return await client.request(
            "POST",
            "/links",
            json={"name": name, "duration": duration, "event_type": event_type},
        )

    @mcp.tool()
    async def savvycal_update_link(
        slug: str,
        name: str | None = None,
        duration: int | None = None,
        event_type: str | None = None,
    ) -> dict:
        """
        Update an existing SavvyCal scheduling link.

        Args:
            slug: URL slug of the link to update (required)
            name: New display name (optional)
            duration: New duration in minutes (optional)
            event_type: New event type slug (optional)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not slug:
            return {"success": False, "error": "slug is required"}

        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if duration is not None:
            updates["duration"] = duration
        if event_type is not None:
            updates["event_type"] = event_type

        if not updates:
            return {"success": False, "error": "At least one update field must be provided"}

        return await client.request("PATCH", f"/links/{slug}", json=updates)

    @mcp.tool()
    async def savvycal_delete_link(slug: str) -> dict:
        """
        Delete a SavvyCal scheduling link.

        Args:
            slug: URL slug of the link to delete
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not slug:
            return {"success": False, "error": "slug is required"}
        return await client.request("DELETE", f"/links/{slug}")

    # --- Bookings ---

    @mcp.tool()
    async def savvycal_list_bookings(
        start_date: str | None = None,
        end_date: str | None = None,
        status: str | None = None,
    ) -> dict:
        """
        List SavvyCal bookings with optional filters.

        Args:
            start_date: Filter bookings starting on or after this date (ISO 8601, e.g., "2024-01-01")
            end_date: Filter bookings ending on or before this date (ISO 8601, e.g., "2024-01-31")
            status: Filter by status — "scheduled", "cancelled", or "completed"
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if status:
            params["status"] = status

        return await client.request("GET", "/bookings", params=params if params else None)

    @mcp.tool()
    async def savvycal_get_booking(booking_id: str) -> dict:
        """
        Get detailed information about a specific SavvyCal booking.

        Args:
            booking_id: Unique booking ID (e.g., "bkg_01h8zq...")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not booking_id:
            return {"success": False, "error": "booking_id is required"}
        return await client.request("GET", f"/bookings/{booking_id}")

    @mcp.tool()
    async def savvycal_cancel_booking(
        booking_id: str,
        reason: str | None = None,
    ) -> dict:
        """
        Cancel a SavvyCal booking.

        Args:
            booking_id: Unique booking ID to cancel
            reason: Optional plain-text cancellation message sent to the attendee
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not booking_id:
            return {"success": False, "error": "booking_id is required"}

        data: dict[str, Any] = {}
        if reason:
            data["cancellation_reason"] = reason

        return await client.request("DELETE", f"/bookings/{booking_id}", json=data if data else None)
