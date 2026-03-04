"""
Zoom Meeting Management Tool - Meetings, recordings, and user info.

Supports:
- Server-to-Server OAuth Bearer tokens (ZOOM_ACCESS_TOKEN)

API Reference: https://developers.zoom.us/docs/api/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

ZOOM_API_BASE = "https://api.zoom.us/v2"


def _get_token(
    credentials: CredentialStoreAdapter | None,
) -> str | dict[str, str]:
    """Return access token string or an error dict."""
    if credentials is not None:
        token = credentials.get("zoom")
    else:
        token = os.getenv("ZOOM_ACCESS_TOKEN")

    if not token:
        return {
            "error": "Zoom credentials not configured",
            "help": (
                "Set ZOOM_ACCESS_TOKEN environment variable or configure via credential store"
            ),
        }
    return token


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _handle_response(resp: httpx.Response) -> dict[str, Any]:
    if resp.status_code == 204:
        return {"success": True}
    if resp.status_code == 401:
        return {"error": "Invalid or expired Zoom access token"}
    if resp.status_code == 403:
        return {"error": "Insufficient Zoom API scopes for this operation"}
    if resp.status_code == 404:
        return {"error": "Zoom resource not found"}
    if resp.status_code == 429:
        return {"error": "Zoom rate limit exceeded. Try again later."}
    if resp.status_code >= 400:
        try:
            body = resp.json()
            detail = body.get("message", resp.text)
        except Exception:
            detail = resp.text
        return {"error": f"Zoom API error (HTTP {resp.status_code}): {detail}"}
    return resp.json()


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Zoom meeting management tools with the MCP server."""

    @mcp.tool()
    def zoom_get_user(user_id: str = "me") -> dict:
        """
        Get Zoom user information.

        Args:
            user_id: User ID, email, or "me" for the authenticated user.

        Returns:
            Dict with user profile information.
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        try:
            resp = httpx.get(
                f"{ZOOM_API_BASE}/users/{user_id}",
                headers=_headers(token),
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            return {
                "id": result.get("id"),
                "email": result.get("email"),
                "first_name": result.get("first_name"),
                "last_name": result.get("last_name"),
                "display_name": result.get("display_name"),
                "type": result.get("type"),
                "timezone": result.get("timezone"),
                "status": result.get("status"),
                "account_id": result.get("account_id"),
                "created_at": result.get("created_at"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def zoom_list_meetings(
        user_id: str = "me",
        type: str = "upcoming",
        page_size: int = 30,
        next_page_token: str = "",
    ) -> dict:
        """
        List Zoom meetings for a user.

        Args:
            user_id: User ID, email, or "me" for the authenticated user.
            type: Meeting type filter - "scheduled", "live", "upcoming",
                  "upcoming_meetings", or "previous_meetings".
            page_size: Number of meetings per page (max 300, default 30).
            next_page_token: Pagination token from a previous response.

        Returns:
            Dict with meetings list and pagination info.
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        try:
            params: dict[str, Any] = {
                "type": type,
                "page_size": min(page_size, 300),
            }
            if next_page_token:
                params["next_page_token"] = next_page_token

            resp = httpx.get(
                f"{ZOOM_API_BASE}/users/{user_id}/meetings",
                headers=_headers(token),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            meetings = []
            for m in result.get("meetings", []):
                meetings.append(
                    {
                        "id": m.get("id"),
                        "uuid": m.get("uuid"),
                        "topic": m.get("topic"),
                        "type": m.get("type"),
                        "start_time": m.get("start_time"),
                        "duration": m.get("duration"),
                        "timezone": m.get("timezone"),
                        "join_url": m.get("join_url"),
                        "created_at": m.get("created_at"),
                    }
                )

            output: dict[str, Any] = {
                "total_records": result.get("total_records", 0),
                "count": len(meetings),
                "meetings": meetings,
            }
            npt = result.get("next_page_token", "")
            if npt:
                output["next_page_token"] = npt
            return output
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def zoom_get_meeting(meeting_id: str) -> dict:
        """
        Get details of a specific Zoom meeting.

        Args:
            meeting_id: The Zoom meeting ID (numeric).

        Returns:
            Dict with full meeting details including settings.
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        if not meeting_id:
            return {"error": "meeting_id is required"}

        try:
            resp = httpx.get(
                f"{ZOOM_API_BASE}/meetings/{meeting_id}",
                headers=_headers(token),
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            settings = result.get("settings", {})
            return {
                "id": result.get("id"),
                "uuid": result.get("uuid"),
                "topic": result.get("topic"),
                "type": result.get("type"),
                "start_time": result.get("start_time"),
                "duration": result.get("duration"),
                "timezone": result.get("timezone"),
                "agenda": result.get("agenda"),
                "join_url": result.get("join_url"),
                "start_url": result.get("start_url"),
                "password": result.get("password"),
                "host_id": result.get("host_id"),
                "created_at": result.get("created_at"),
                "settings": {
                    "host_video": settings.get("host_video"),
                    "participant_video": settings.get("participant_video"),
                    "join_before_host": settings.get("join_before_host"),
                    "mute_upon_entry": settings.get("mute_upon_entry"),
                    "waiting_room": settings.get("waiting_room"),
                    "auto_recording": settings.get("auto_recording"),
                },
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def zoom_create_meeting(
        topic: str,
        start_time: str = "",
        duration: int = 60,
        timezone: str = "",
        agenda: str = "",
        user_id: str = "me",
    ) -> dict:
        """
        Create a new Zoom meeting.

        Args:
            topic: Meeting topic/title.
            start_time: Start time in ISO 8601 format (e.g. "2025-03-15T14:00:00Z").
                         If empty, creates an instant meeting.
            duration: Meeting duration in minutes (default 60).
            timezone: Timezone (e.g. "America/New_York"). Uses host timezone if empty.
            agenda: Meeting description/agenda.
            user_id: User ID or "me" for the authenticated user.

        Returns:
            Dict with created meeting details including join_url and start_url.
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        if not topic:
            return {"error": "topic is required"}

        try:
            body: dict[str, Any] = {
                "topic": topic,
                "type": 2 if start_time else 1,  # 2=scheduled, 1=instant
                "duration": duration,
            }
            if start_time:
                body["start_time"] = start_time
            if timezone:
                body["timezone"] = timezone
            if agenda:
                body["agenda"] = agenda

            resp = httpx.post(
                f"{ZOOM_API_BASE}/users/{user_id}/meetings",
                headers=_headers(token),
                json=body,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            return {
                "id": result.get("id"),
                "uuid": result.get("uuid"),
                "topic": result.get("topic"),
                "start_time": result.get("start_time"),
                "duration": result.get("duration"),
                "join_url": result.get("join_url"),
                "start_url": result.get("start_url"),
                "password": result.get("password"),
                "created_at": result.get("created_at"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def zoom_delete_meeting(meeting_id: str) -> dict:
        """
        Delete/cancel a Zoom meeting.

        Args:
            meeting_id: The Zoom meeting ID to delete.

        Returns:
            Dict with success status or error.
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        if not meeting_id:
            return {"error": "meeting_id is required"}

        try:
            resp = httpx.delete(
                f"{ZOOM_API_BASE}/meetings/{meeting_id}",
                headers=_headers(token),
                timeout=30.0,
            )
            return _handle_response(resp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def zoom_list_recordings(
        from_date: str,
        to_date: str,
        user_id: str = "me",
        page_size: int = 30,
        next_page_token: str = "",
    ) -> dict:
        """
        List cloud recordings for a Zoom user within a date range.

        Args:
            from_date: Start date in YYYY-MM-DD format (max 1 month range).
            to_date: End date in YYYY-MM-DD format.
            user_id: User ID, email, or "me" for the authenticated user.
            page_size: Number of results per page (max 300, default 30).
            next_page_token: Pagination token from a previous response.

        Returns:
            Dict with recordings list and pagination info.
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        if not from_date or not to_date:
            return {"error": "from_date and to_date are required (YYYY-MM-DD)"}

        try:
            params: dict[str, Any] = {
                "from": from_date,
                "to": to_date,
                "page_size": min(page_size, 300),
            }
            if next_page_token:
                params["next_page_token"] = next_page_token

            resp = httpx.get(
                f"{ZOOM_API_BASE}/users/{user_id}/recordings",
                headers=_headers(token),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            recordings = []
            for m in result.get("meetings", []):
                files = []
                for f in m.get("recording_files", []):
                    files.append(
                        {
                            "id": f.get("id"),
                            "file_type": f.get("file_type"),
                            "file_size": f.get("file_size"),
                            "recording_type": f.get("recording_type"),
                            "status": f.get("status"),
                            "play_url": f.get("play_url"),
                        }
                    )
                recordings.append(
                    {
                        "meeting_id": m.get("id"),
                        "topic": m.get("topic"),
                        "start_time": m.get("start_time"),
                        "duration": m.get("duration"),
                        "recording_count": m.get("recording_count"),
                        "total_size": m.get("total_size"),
                        "recording_files": files,
                    }
                )

            output: dict[str, Any] = {
                "total_records": result.get("total_records", 0),
                "count": len(recordings),
                "recordings": recordings,
            }
            npt = result.get("next_page_token", "")
            if npt:
                output["next_page_token"] = npt
            return output
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
