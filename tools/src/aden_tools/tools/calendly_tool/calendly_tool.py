"""Calendly API v2 integration.

Provides scheduling event management via the Calendly REST API.
Requires CALENDLY_PAT (Personal Access Token).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

BASE_URL = "https://api.calendly.com"


def _get_headers() -> dict | None:
    """Return auth headers or None if credentials missing."""
    token = os.getenv("CALENDLY_PAT", "")
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _get(path: str, headers: dict, params: dict | None = None) -> dict:
    """Send a GET request."""
    resp = httpx.get(f"{BASE_URL}{path}", headers=headers, params=params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register Calendly tools."""

    @mcp.tool()
    def calendly_get_current_user() -> dict:
        """Get the current authenticated Calendly user.

        Returns user URI (needed for other endpoints), name, email,
        scheduling URL, and organization URI.
        """
        headers = _get_headers()
        if headers is None:
            return {"error": "CALENDLY_PAT is required"}

        data = _get("/users/me", headers)
        if "error" in data:
            return data

        user = data.get("resource", {})
        return {
            "uri": user.get("uri"),
            "name": user.get("name"),
            "email": user.get("email"),
            "scheduling_url": user.get("scheduling_url"),
            "timezone": user.get("timezone"),
            "organization": user.get("current_organization"),
        }

    @mcp.tool()
    def calendly_list_event_types(
        user_uri: str,
        active: bool = True,
        count: int = 20,
    ) -> dict:
        """List Calendly event types (meeting templates) for a user.

        Args:
            user_uri: Full user URI from calendly_get_current_user (e.g. 'https://api.calendly.com/users/XXX').
            active: If true, only return active event types.
            count: Number of results per page (max 100).
        """
        headers = _get_headers()
        if headers is None:
            return {"error": "CALENDLY_PAT is required"}
        if not user_uri:
            return {"error": "user_uri is required"}

        params: dict[str, Any] = {
            "user": user_uri,
            "count": min(count, 100),
        }
        if active:
            params["active"] = "true"

        data = _get("/event_types", headers, params)
        if "error" in data:
            return data

        items = data.get("collection", [])
        return {
            "count": len(items),
            "event_types": [
                {
                    "uri": et.get("uri"),
                    "name": et.get("name"),
                    "slug": et.get("slug"),
                    "active": et.get("active"),
                    "duration": et.get("duration"),
                    "kind": et.get("kind"),
                    "scheduling_url": et.get("scheduling_url"),
                    "description": et.get("description_plain"),
                }
                for et in items
            ],
        }

    @mcp.tool()
    def calendly_list_scheduled_events(
        user_uri: str,
        status: str = "active",
        min_start_time: str = "",
        max_start_time: str = "",
        count: int = 20,
    ) -> dict:
        """List scheduled Calendly events (booked meetings).

        Args:
            user_uri: Full user URI from calendly_get_current_user.
            status: Filter by status: 'active' or 'canceled'.
            min_start_time: Start of date range (ISO 8601, e.g. '2024-01-01T00:00:00Z').
            max_start_time: End of date range (ISO 8601).
            count: Number of results per page (max 100).
        """
        headers = _get_headers()
        if headers is None:
            return {"error": "CALENDLY_PAT is required"}
        if not user_uri:
            return {"error": "user_uri is required"}

        params: dict[str, Any] = {
            "user": user_uri,
            "count": min(count, 100),
        }
        if status:
            params["status"] = status
        if min_start_time:
            params["min_start_time"] = min_start_time
        if max_start_time:
            params["max_start_time"] = max_start_time

        data = _get("/scheduled_events", headers, params)
        if "error" in data:
            return data

        items = data.get("collection", [])
        return {
            "count": len(items),
            "events": [
                {
                    "uri": ev.get("uri"),
                    "name": ev.get("name"),
                    "status": ev.get("status"),
                    "start_time": ev.get("start_time"),
                    "end_time": ev.get("end_time"),
                    "event_type": ev.get("event_type"),
                    "location": ev.get("location", {}).get("location"),
                    "invitees_count": ev.get("invitees_counter", {}).get("total", 0),
                }
                for ev in items
            ],
        }

    @mcp.tool()
    def calendly_get_scheduled_event(event_uri: str) -> dict:
        """Get details of a specific scheduled Calendly event.

        Args:
            event_uri: Full event URI (e.g. 'https://api.calendly.com/scheduled_events/XXX').
        """
        headers = _get_headers()
        if headers is None:
            return {"error": "CALENDLY_PAT is required"}
        if not event_uri:
            return {"error": "event_uri is required"}

        # Extract the UUID from the full URI
        event_uuid = event_uri.rstrip("/").rsplit("/", 1)[-1]

        data = _get(f"/scheduled_events/{event_uuid}", headers)
        if "error" in data:
            return data

        ev = data.get("resource", {})
        return {
            "uri": ev.get("uri"),
            "name": ev.get("name"),
            "status": ev.get("status"),
            "start_time": ev.get("start_time"),
            "end_time": ev.get("end_time"),
            "event_type": ev.get("event_type"),
            "location": ev.get("location"),
            "invitees_counter": ev.get("invitees_counter"),
            "event_memberships": ev.get("event_memberships"),
            "created_at": ev.get("created_at"),
        }

    @mcp.tool()
    def calendly_list_invitees(
        event_uri: str,
        count: int = 25,
    ) -> dict:
        """List invitees for a scheduled Calendly event.

        Args:
            event_uri: Full event URI (e.g. 'https://api.calendly.com/scheduled_events/XXX').
            count: Number of results per page (max 100).
        """
        headers = _get_headers()
        if headers is None:
            return {"error": "CALENDLY_PAT is required"}
        if not event_uri:
            return {"error": "event_uri is required"}

        event_uuid = event_uri.rstrip("/").rsplit("/", 1)[-1]
        params: dict[str, Any] = {"count": min(count, 100)}

        data = _get(f"/scheduled_events/{event_uuid}/invitees", headers, params)
        if "error" in data:
            return data

        items = data.get("collection", [])
        return {
            "count": len(items),
            "invitees": [
                {
                    "uri": inv.get("uri"),
                    "name": inv.get("name"),
                    "email": inv.get("email"),
                    "status": inv.get("status"),
                    "timezone": inv.get("timezone"),
                    "questions_and_answers": inv.get("questions_and_answers", []),
                    "created_at": inv.get("created_at"),
                }
                for inv in items
            ],
        }
