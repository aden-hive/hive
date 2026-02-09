"""
Calendly Tool - Scheduling and availability via Calendly API v2.

Supports:
- List event types (with booking/scheduling URLs)
- Get available times for an event type
- Cancel scheduled event (optional)

API Reference: https://developer.calendly.com/api-docs
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

CALENDLY_API_BASE = "https://api.calendly.com"
MAX_RETRIES = 2
MAX_RETRY_WAIT = 60
MAX_AVAILABILITY_DAYS = 7


class _CalendlyClient:
    """Internal client wrapping Calendly API v2 calls."""

    def __init__(self, token: str) -> None:
        self._token = token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make HTTP request with retry on 429 rate limit."""
        request_kwargs = {"headers": self._headers, "timeout": 30.0, **kwargs}
        for attempt in range(MAX_RETRIES + 1):
            response = httpx.request(method, url, **request_kwargs)
            if response.status_code == 429 and attempt < MAX_RETRIES:
                try:
                    wait = min(float(response.headers.get("Retry-After", 1)), MAX_RETRY_WAIT)
                except (ValueError, TypeError):
                    wait = min(2**attempt, MAX_RETRY_WAIT)
                time.sleep(wait)
                continue
            return self._handle_response(response)
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle Calendly API response."""
        if response.status_code == 401:
            return {"error": "Invalid or expired Calendly token"}
        if response.status_code == 403:
            return {"error": "Access forbidden. Check token permissions."}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            return {
                "error": f"Calendly rate limit exceeded. Retry after {retry_after}s",
                "retry_after": retry_after,
            }
        if response.status_code >= 400:
            return {"error": f"Calendly API error (HTTP {response.status_code}): {response.text}"}

        try:
            return response.json()
        except Exception as e:
            return {"error": f"Failed to parse response: {e}"}

    def get_current_user(self) -> dict[str, Any]:
        """Get current authenticated user (for user URI)."""
        return self._request_with_retry("GET", f"{CALENDLY_API_BASE}/users/me")

    def list_event_types(self, user_uri: str | None = None) -> dict[str, Any]:
        """List event types for a user."""
        if not user_uri:
            me = self.get_current_user()
            if "error" in me:
                return me
            user_uri = me.get("resource", {}).get("uri")
            if not user_uri:
                return {"error": "Could not get user URI from /users/me"}

        result = self._request_with_retry(
            "GET",
            f"{CALENDLY_API_BASE}/event_types",
            params={"user": user_uri},
        )
        if "error" in result:
            return result

        # Flatten for easier consumption
        collection = result.get("collection", [])
        events = []
        for item in collection:
            resource = item.get("resource", {})
            events.append(
                {
                    "uri": resource.get("uri"),
                    "name": resource.get("name"),
                    "slug": resource.get("slug"),
                    "active": resource.get("active", True),
                    "scheduling_url": resource.get("scheduling_url"),
                    "duration": resource.get("duration"),
                    "kind": resource.get("kind"),
                }
            )

        return {
            "success": True,
            "event_types": events,
            "count": len(events),
        }

    def get_event_type(self, event_type_uri: str) -> dict[str, Any]:
        """Get a single event type by URI (includes scheduling_url)."""
        result = self._request_with_retry("GET", event_type_uri)
        if "error" in result:
            return result
        resource = result.get("resource", {})
        return {
            "success": True,
            "uri": resource.get("uri"),
            "name": resource.get("name"),
            "slug": resource.get("slug"),
            "scheduling_url": resource.get("scheduling_url"),
            "duration": resource.get("duration"),
            "active": resource.get("active", True),
        }

    def get_availability(
        self,
        event_type_uri: str,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict[str, Any]:
        """Get available times for an event type. Max 7-day range."""
        if not start_time or not end_time:
            now = datetime.now(UTC)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=MAX_AVAILABILITY_DAYS)
            start_time = start.isoformat().replace("+00:00", "Z")
            end_time = end.isoformat().replace("+00:00", "Z")
        else:
            try:
                start_dt = datetime.fromisoformat(
                    start_time.replace("Z", "+00:00").replace("z", "+00:00")
                )
                end_dt = datetime.fromisoformat(
                    end_time.replace("Z", "+00:00").replace("z", "+00:00")
                )
                if (end_dt - start_dt).days > MAX_AVAILABILITY_DAYS:
                    return {
                        "error": f"Date range exceeds {MAX_AVAILABILITY_DAYS} day limit",
                        "max_days": MAX_AVAILABILITY_DAYS,
                    }
            except (ValueError, TypeError):
                pass

        result = self._request_with_retry(
            "GET",
            f"{CALENDLY_API_BASE}/event_type_available_times",
            params={
                "event_type": event_type_uri,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        if "error" in result:
            return result

        collection = result.get("collection", [])
        slots = []
        for item in collection:
            resource = item.get("resource", {})
            slots.append(
                {
                    "start_time": resource.get("start_time"),
                    "invitees_remaining": resource.get("invitees_remaining", 1),
                }
            )

        return {
            "success": True,
            "event_type_uri": event_type_uri,
            "start_time": start_time,
            "end_time": end_time,
            "available_times": slots,
            "count": len(slots),
        }

    def cancel_event(self, event_uri: str, reason: str | None = None) -> dict[str, Any]:
        """Cancel a scheduled event."""
        body: dict[str, Any] = {}
        if reason:
            body["reason"] = reason

        result = self._request_with_retry(
            "POST",
            f"{event_uri}/cancellation",
            json=body,
        )
        if "error" in result:
            return result
        return {"success": True, "message": "Event cancelled"}


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Calendly tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Calendly token from credential manager or environment."""
        if credentials is not None:
            token = credentials.get("calendly")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('calendly'), got {type(token).__name__}"
                )
            return token
        return os.getenv("CALENDLY_API_TOKEN") or os.getenv("CALENDLY_ACCESS_TOKEN")

    def _get_client() -> _CalendlyClient | dict[str, str]:
        """Get a Calendly client or return an error dict."""
        token = _get_token()
        if not token:
            return {
                "error": "Calendly credentials not configured",
                "help": (
                    "Set CALENDLY_API_TOKEN env var or configure via credential store. "
                    "Get token from https://calendly.com/integrations/api_webhooks"
                ),
            }
        return _CalendlyClient(token)

    @mcp.tool()
    def calendly_list_event_types() -> dict:
        """
        List all Calendly event types for the authenticated user.

        Returns event types with their names, URIs, scheduling URLs (booking links),
        and duration. Use the scheduling_url to share a booking link with invitees.

        Returns:
            Dict with event_types list and count, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_event_types()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def calendly_get_availability(
        event_type_uri: str,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict:
        """
        Get available booking times for a Calendly event type.

        Args:
            event_type_uri: Full URI of the event type (from calendly_list_event_types)
            start_time: ISO8601 start of range (default: now, 7 days ahead)
            end_time: ISO8601 end of range (max 7 days from start_time)

        Returns:
            Dict with available_times list and count, or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_availability(event_type_uri, start_time, end_time)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def calendly_get_booking_link(event_type_uri: str) -> dict:
        """
        Get the scheduling/booking URL for a Calendly event type.

        Use this when you have an event type URI and need the shareable link
        (e.g. to include in an email or message). If you already have the URL
        from calendly_list_event_types, you can use it directly.

        Args:
            event_type_uri: Full URI of the event type
                (e.g. https://api.calendly.com/event_types/XXXXX)

        Returns:
            Dict with scheduling_url or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_event_type(event_type_uri)
            if "error" in result:
                return result
            return {
                "success": True,
                "event_type_uri": event_type_uri,
                "name": result.get("name"),
                "scheduling_url": result.get("scheduling_url"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def calendly_cancel_event(event_uri: str, reason: str | None = None) -> dict:
        """
        Cancel a scheduled Calendly event.

        Args:
            event_uri: Full URI of the scheduled event (e.g. from webhook or list)
            reason: Optional cancellation reason (shown to invitee)

        Returns:
            Dict with success or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.cancel_event(event_uri, reason)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
