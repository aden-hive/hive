"""
Google Calendar Tool - Manage calendar events and check availability.

Supports:
- Event CRUD operations (list, get, create, update, delete)
- Calendar listing and details
- Free/busy availability checks

Requires OAuth 2.0 credentials:
- Aden: Use aden_provider_name="google-calendar" for managed OAuth (recommended)
- Direct: Set GOOGLE_CALENDAR_ACCESS_TOKEN with token from OAuth Playground
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import quote
from zoneinfo import available_timezones

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from framework.credentials.oauth2 import TokenLifecycleManager

    from aden_tools.credentials import CredentialStoreAdapter

logger = logging.getLogger(__name__)

# Google Calendar API base URL
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


def _create_lifecycle_manager(
    credentials: CredentialStoreAdapter,
) -> TokenLifecycleManager | None:
    """
    Create a TokenLifecycleManager for automatic token refresh.

    Currently returns None because token refresh is handled server-side by Aden's
    OAuth infrastructure. When using Aden OAuth, tokens are refreshed automatically
    before they expire. For direct API access (testing), use a short-lived token
    from the OAuth Playground - these tokens expire after ~1 hour.

    This function exists as a hook for future local token refresh if needed.
    """
    return None


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Google Calendar tools with the MCP server."""

    # Create lifecycle manager for auto-refresh (if possible)
    lifecycle_manager: TokenLifecycleManager | None = None
    if credentials is not None:
        lifecycle_manager = _create_lifecycle_manager(credentials)
        if lifecycle_manager:
            logger.info("Google Calendar OAuth auto-refresh enabled")

    def _get_token(account: str = "") -> str | None:
        """
        Get OAuth token, refreshing if needed.

        Priority:
        1. TokenLifecycleManager (auto-refresh) if available
        2. CredentialStoreAdapter (includes env var fallback)
        3. Environment variable (direct fallback if no adapter)
        """
        # Try lifecycle manager first (handles auto-refresh)
        if lifecycle_manager is not None:
            token = lifecycle_manager.sync_get_valid_token()
            if token is not None:
                return token.access_token

        # Fall back to credential store adapter
        if credentials is not None:
            if account:
                return credentials.get_by_alias(
                    "google_calendar_oauth",
                    account,
                )
            return credentials.get("google_calendar_oauth")

        # Fall back to environment variable
        return os.getenv("GOOGLE_CALENDAR_ACCESS_TOKEN")

    def _get_headers(account: str = "") -> dict[str, str]:
        """Get authorization headers for API requests.

        Note: Callers must use _check_credentials() first to ensure token exists.
        """
        token = _get_token(account)
        if token is None:
            token = ""  # Will fail auth but prevents "Bearer None" in logs
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _check_credentials(account: str = "") -> dict | None:
        """Check if credentials are configured. Returns error dict if not."""
        token = _get_token(account)
        if not token:
            return {
                "error": "Calendar credentials not configured",
                "help": "Set GOOGLE_CALENDAR_ACCESS_TOKEN environment variable",
            }
        return None

    def _encode_id(id_value: str) -> str:
        """URL-encode a calendar or event ID for safe use in URLs."""
        return quote(id_value, safe="")

    def _sanitize_error(e: Exception) -> str:
        """Sanitize exception message to avoid leaking sensitive data like tokens."""
        msg = str(e)
        # httpx.RequestError can include headers with Bearer token
        # Only return the error type and a safe portion of the message
        if "Bearer" in msg or "Authorization" in msg:
            return f"{type(e).__name__}: Request failed (details redacted for security)"
        # Truncate long messages that might contain sensitive data
        if len(msg) > 200:
            return f"{type(e).__name__}: {msg[:200]}..."
        return msg

    # Pre-compute valid timezones once
    _VALID_TIMEZONES = available_timezones()

    # Pattern for date-only strings (YYYY-MM-DD)
    _DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def _validate_timezone(tz: str) -> dict | None:
        """Validate a timezone string. Returns error dict if invalid, None if valid."""
        if tz not in _VALID_TIMEZONES:
            return {"error": f"Invalid timezone '{tz}'. Use IANA format (e.g., 'America/New_York')"}
        return None

    def _handle_response(response: httpx.Response) -> dict:
        """Handle API response and return appropriate result."""
        if response.status_code == 401:
            # If we have a lifecycle manager, the token should have auto-refreshed
            # If we still get 401, the refresh token is likely invalid
            if lifecycle_manager is not None:
                return {
                    "error": "OAuth token expired and refresh failed",
                    "help": "Re-authenticate via Aden or get a new token from OAuth Playground",
                }
            return {
                "error": "Invalid or expired OAuth token",
                "help": "Get a new token from https://developers.google.com/oauthplayground/",
            }
        elif response.status_code == 403:
            return {
                "error": "Access denied. Check calendar permissions.",
                "help": "Ensure the OAuth token has calendar.events scope",
            }
        elif response.status_code == 404:
            return {"error": "Resource not found"}
        elif response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        elif response.status_code >= 400:
            try:
                error_data = response.json()
                message = error_data.get("error", {}).get("message", "Unknown error")
                return {"error": f"API error: {message}"}
            except Exception:
                return {"error": f"API request failed: HTTP {response.status_code}"}
        return response.json()

    @mcp.tool()
    def calendar_list_events(
        calendar_id: str = "primary",
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 10,
        query: str | None = None,
        account: str = "",
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        List upcoming calendar events.

        Args:
            calendar_id: Calendar ID or "primary" for main calendar
            time_min: Start time filter (ISO 8601 format, e.g., "2024-01-15T00:00:00Z")
            time_max: End time filter (ISO 8601 format)
            max_results: Maximum events to return (1-2500, default 10)
            query: Free text search terms to filter events
            workspace_id: Tracking parameter (injected by framework)
            agent_id: Tracking parameter (injected by framework)
            session_id: Tracking parameter (injected by framework)

        Returns:
            Dict with list of events or error message
        """
        cred_error = _check_credentials(account)
        if cred_error:
            return cred_error

        if max_results < 1 or max_results > 2500:
            return {"error": "max_results must be between 1 and 2500"}

        # Default time_min to now if not provided
        if time_min is None:
            time_min = datetime.now(UTC).isoformat()

        params: dict = {
            "maxResults": max_results,
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": time_min,
        }

        if time_max:
            params["timeMax"] = time_max
        if query:
            params["q"] = query

        try:
            response = httpx.get(
                f"{CALENDAR_API_BASE}/calendars/{_encode_id(calendar_id)}/events",
                headers=_get_headers(account),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(response)

            if "error" in result:
                return result

            # Format events for cleaner output
            events = []
            for item in result.get("items", []):
                start = item.get("start", {})
                end = item.get("end", {})
                event_data = {
                    "id": item.get("id"),
                    "summary": item.get("summary", "(No title)"),
                    "start": start.get("dateTime") or start.get("date"),
                    "end": end.get("dateTime") or end.get("date"),
                    "location": item.get("location"),
                    "status": item.get("status"),
                    "html_link": item.get("htmlLink"),
                    "description": item.get("description"),
                    "hangoutLink": item.get("hangoutLink"),
                }
                if item.get("attendees"):
                    event_data["attendees"] = [a.get("email") for a in item["attendees"]]
                events.append(event_data)

            return {
                "calendar_id": calendar_id,
                "events": events,
                "total": len(events),
            }

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    @mcp.tool()
    def calendar_get_event(
        event_id: str,
        calendar_id: str = "primary",
        account: str = "",
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Get details of a specific calendar event.

        Args:
            event_id: The event ID to retrieve
            calendar_id: Calendar ID or "primary" for main calendar
            workspace_id: Tracking parameter (injected by framework)
            agent_id: Tracking parameter (injected by framework)
            session_id: Tracking parameter (injected by framework)

        Returns:
            Dict with event details or error message
        """
        cred_error = _check_credentials(account)
        if cred_error:
            return cred_error

        if not event_id:
            return {"error": "event_id is required"}

        try:
            response = httpx.get(
                f"{CALENDAR_API_BASE}/calendars/{_encode_id(calendar_id)}/events/{_encode_id(event_id)}",
                headers=_get_headers(account),
                timeout=30.0,
            )
            return _handle_response(response)

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    @mcp.tool()
    def calendar_create_event(
        summary: str,
        start_time: str,
        end_time: str,
        calendar_id: str = "primary",
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        send_notifications: bool = True,
        timezone: str | None = None,
        all_day: bool = False,
        account: str = "",
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Create a new calendar event.

        Args:
            summary: Event title
            start_time: Start time (ISO 8601 format, e.g., "2024-01-15T09:00:00").
                For all-day events use date-only format: "2024-01-15"
            end_time: End time (ISO 8601 format).
                For all-day events use date-only format: "2024-01-16"
                (end date is exclusive — a 1-day event on Jan 15 uses end "2024-01-16")
            calendar_id: Calendar ID or "primary" for main calendar
            description: Event description/notes
            location: Event location (address or room name)
            attendees: List of attendee email addresses
            send_notifications: Whether to send email invites to attendees
            timezone: Timezone for the event (e.g., "America/New_York"). Ignored for all-day events.
            all_day: If True, creates an all-day event using date-only start/end
            workspace_id: Tracking parameter (injected by framework)
            agent_id: Tracking parameter (injected by framework)
            session_id: Tracking parameter (injected by framework)

        Returns:
            Dict with created event details or error message
        """
        cred_error = _check_credentials(account)
        if cred_error:
            return cred_error

        if not summary:
            return {"error": "summary is required"}
        if not start_time:
            return {"error": "start_time is required"}
        if not end_time:
            return {"error": "end_time is required"}

        # Validate timezone if provided
        if timezone and not all_day:
            tz_error = _validate_timezone(timezone)
            if tz_error:
                return tz_error

        # Build event body
        if all_day:
            # Validate date-only format for all-day events
            if not _DATE_ONLY_RE.match(start_time):
                return {
                    "error": "all-day events require date-only format for start_time (YYYY-MM-DD)"
                }
            if not _DATE_ONLY_RE.match(end_time):
                return {
                    "error": "all-day events require date-only format for end_time (YYYY-MM-DD)"
                }
            event_body: dict = {
                "summary": summary,
                "start": {"date": start_time},
                "end": {"date": end_time},
            }
        else:
            event_body = {
                "summary": summary,
                "start": {"dateTime": start_time},
                "end": {"dateTime": end_time},
            }
            if timezone:
                event_body["start"]["timeZone"] = timezone
                event_body["end"]["timeZone"] = timezone

        if description is not None:
            event_body["description"] = description
        if location is not None:
            event_body["location"] = location
        if attendees:
            event_body["attendees"] = [{"email": email} for email in attendees]
            # Auto-generate Google Meet link when attendees are present
            event_body["conferenceData"] = {
                "createRequest": {
                    "requestId": f"meet-{uuid.uuid4().hex[:12]}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }

        params: dict = {"sendUpdates": "all" if send_notifications else "none"}
        # Enable conference data support for Meet link generation
        if attendees:
            params["conferenceDataVersion"] = 1

        try:
            response = httpx.post(
                f"{CALENDAR_API_BASE}/calendars/{_encode_id(calendar_id)}/events",
                headers=_get_headers(account),
                json=event_body,
                params=params,
                timeout=30.0,
            )
            return _handle_response(response)

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    @mcp.tool()
    def calendar_update_event(
        event_id: str,
        calendar_id: str = "primary",
        summary: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        remove_attendees: list[str] | None = None,
        send_notifications: bool = True,
        timezone: str | None = None,
        all_day: bool = False,
        add_meet_link: bool = False,
        account: str = "",
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Update an existing calendar event. Only provided fields are changed.

        Args:
            event_id: The event ID to update
            calendar_id: Calendar ID or "primary" for main calendar
            summary: New event title (None to keep existing)
            start_time: New start time (ISO 8601 format).
                For all-day events use date-only format: "2024-01-15"
            end_time: New end time (ISO 8601 format).
                For all-day events use date-only format: "2024-01-16"
            description: New description
            location: New location
            attendees: Updated list of attendee emails (replaces existing)
            remove_attendees: List of attendee emails to remove from the event
            send_notifications: Whether to send update emails
            timezone: Timezone for the event (e.g., "America/New_York"). Ignored for all-day events.
            all_day: If True and start_time/end_time are provided, converts to all-day event
            add_meet_link: If True, adds a Google Meet link to the event
            workspace_id: Tracking parameter (injected by framework)
            agent_id: Tracking parameter (injected by framework)
            session_id: Tracking parameter (injected by framework)

        Returns:
            Dict with updated event details or error message
        """
        cred_error = _check_credentials(account)
        if cred_error:
            return cred_error

        if not event_id:
            return {"error": "event_id is required"}

        # Validate timezone if provided
        if timezone and not all_day:
            tz_error = _validate_timezone(timezone)
            if tz_error:
                return tz_error

        # Build partial body with only provided fields (PATCH semantics)
        patch_body: dict = {}

        if summary is not None:
            patch_body["summary"] = summary
        if description is not None:
            patch_body["description"] = description
        if location is not None:
            patch_body["location"] = location

        if remove_attendees is not None:
            # Fetch current event to get attendee list
            try:
                get_response = httpx.get(
                    f"{CALENDAR_API_BASE}/calendars/{_encode_id(calendar_id)}/events/{_encode_id(event_id)}",
                    headers=_get_headers(account),
                    timeout=30.0,
                )
                event_data = _handle_response(get_response)
                if "error" in event_data:
                    return event_data
            except httpx.TimeoutException:
                return {"error": "Request timed out while fetching event"}
            except httpx.RequestError as e:
                return {"error": f"Network error: {_sanitize_error(e)}"}

            current_attendees = event_data.get("attendees", [])
            remove_set = {e.lower() for e in remove_attendees}
            remaining = [
                a for a in current_attendees if a.get("email", "").lower() not in remove_set
            ]
            patch_body["attendees"] = remaining
        elif attendees is not None:
            patch_body["attendees"] = [{"email": email} for email in attendees]

        if add_meet_link:
            patch_body["conferenceData"] = {
                "createRequest": {
                    "requestId": f"meet-{uuid.uuid4().hex[:12]}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }

        if start_time is not None:
            if all_day:
                if not _DATE_ONLY_RE.match(start_time):
                    return {
                        "error": (
                            "all-day events require date-only format for start_time (YYYY-MM-DD)"
                        )
                    }
                patch_body["start"] = {"date": start_time}
            else:
                patch_body["start"] = {"dateTime": start_time}
                if timezone:
                    patch_body["start"]["timeZone"] = timezone

        if end_time is not None:
            if all_day:
                if not _DATE_ONLY_RE.match(end_time):
                    return {
                        "error": (
                            "all-day events require date-only format for end_time (YYYY-MM-DD)"
                        )
                    }
                patch_body["end"] = {"date": end_time}
            else:
                patch_body["end"] = {"dateTime": end_time}
                if timezone:
                    patch_body["end"]["timeZone"] = timezone

        if not patch_body:
            return {"error": "No fields to update. Provide at least one field to change."}

        params: dict = {"sendUpdates": "all" if send_notifications else "none"}
        # Enable conference data support only when modifying conference data
        if add_meet_link or attendees is not None or remove_attendees is not None:
            params["conferenceDataVersion"] = 1

        try:
            response = httpx.patch(
                f"{CALENDAR_API_BASE}/calendars/{_encode_id(calendar_id)}/events/{_encode_id(event_id)}",
                headers=_get_headers(account),
                json=patch_body,
                params=params,
                timeout=30.0,
            )
            return _handle_response(response)

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    @mcp.tool()
    def calendar_delete_event(
        event_id: str,
        calendar_id: str = "primary",
        send_notifications: bool = True,
        account: str = "",
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Delete a calendar event.

        Args:
            event_id: The event ID to delete
            calendar_id: Calendar ID or "primary" for main calendar
            send_notifications: Whether to send cancellation emails to attendees
            workspace_id: Tracking parameter (injected by framework)
            agent_id: Tracking parameter (injected by framework)
            session_id: Tracking parameter (injected by framework)

        Returns:
            Dict with success status or error message
        """
        cred_error = _check_credentials(account)
        if cred_error:
            return cred_error

        if not event_id:
            return {"error": "event_id is required"}

        params = {"sendUpdates": "all" if send_notifications else "none"}

        try:
            response = httpx.delete(
                f"{CALENDAR_API_BASE}/calendars/{_encode_id(calendar_id)}/events/{_encode_id(event_id)}",
                headers=_get_headers(account),
                params=params,
                timeout=30.0,
            )

            if response.status_code == 204:
                return {"success": True, "message": f"Event {event_id} deleted"}

            return _handle_response(response)

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    @mcp.tool()
    def calendar_list_calendars(
        max_results: int = 100,
        account: str = "",
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        List all calendars accessible to the user.

        Args:
            max_results: Maximum number of calendars to return (1-250)
            workspace_id: Tracking parameter (injected by framework)
            agent_id: Tracking parameter (injected by framework)
            session_id: Tracking parameter (injected by framework)

        Returns:
            Dict with list of calendars or error message
        """
        cred_error = _check_credentials(account)
        if cred_error:
            return cred_error

        if max_results < 1 or max_results > 250:
            return {"error": "max_results must be between 1 and 250"}

        try:
            response = httpx.get(
                f"{CALENDAR_API_BASE}/users/me/calendarList",
                headers=_get_headers(account),
                params={"maxResults": max_results},
                timeout=30.0,
            )
            result = _handle_response(response)

            if "error" in result:
                return result

            calendars = []
            for item in result.get("items", []):
                calendars.append(
                    {
                        "id": item.get("id"),
                        "summary": item.get("summary"),
                        "description": item.get("description"),
                        "primary": item.get("primary", False),
                        "access_role": item.get("accessRole"),
                        "background_color": item.get("backgroundColor"),
                    }
                )

            return {
                "calendars": calendars,
                "total": len(calendars),
            }

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    @mcp.tool()
    def calendar_get_calendar(
        calendar_id: str,
        account: str = "",
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Get details of a specific calendar.

        Args:
            calendar_id: The calendar ID to retrieve
            workspace_id: Tracking parameter (injected by framework)
            agent_id: Tracking parameter (injected by framework)
            session_id: Tracking parameter (injected by framework)

        Returns:
            Dict with calendar details or error message
        """
        cred_error = _check_credentials(account)
        if cred_error:
            return cred_error

        if not calendar_id:
            return {"error": "calendar_id is required"}

        try:
            response = httpx.get(
                f"{CALENDAR_API_BASE}/calendars/{_encode_id(calendar_id)}",
                headers=_get_headers(account),
                timeout=30.0,
            )
            return _handle_response(response)

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}

    @mcp.tool()
    def calendar_check_availability(
        time_min: str,
        time_max: str,
        calendars: list[str] | None = None,
        timezone: str = "UTC",
        account: str = "",
        # Tracking parameters (injected by framework, ignored by tool)
        workspace_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        Check free/busy availability for scheduling.

        Args:
            time_min: Start of time range (ISO 8601 format)
            time_max: End of time range (ISO 8601 format)
            calendars: List of calendar IDs to check (defaults to ["primary"])
            timezone: Timezone for the query (e.g., "America/New_York")
            workspace_id: Tracking parameter (injected by framework)
            agent_id: Tracking parameter (injected by framework)
            session_id: Tracking parameter (injected by framework)

        Returns:
            Dict with busy periods for each calendar or error message
        """
        cred_error = _check_credentials(account)
        if cred_error:
            return cred_error

        if not time_min:
            return {"error": "time_min is required"}
        if not time_max:
            return {"error": "time_max is required"}

        if calendars is None:
            calendars = ["primary"]

        request_body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "timeZone": timezone,
            "items": [{"id": cal_id} for cal_id in calendars],
        }

        try:
            response = httpx.post(
                f"{CALENDAR_API_BASE}/freeBusy",
                headers=_get_headers(account),
                json=request_body,
                timeout=30.0,
            )
            result = _handle_response(response)

            if "error" in result:
                return result

            # Format the response for easier consumption
            formatted_calendars = {}
            for cal_id, cal_data in result.get("calendars", {}).items():
                if "errors" in cal_data:
                    formatted_calendars[cal_id] = {
                        "error": cal_data["errors"][0].get("reason", "Unknown error")
                    }
                else:
                    formatted_calendars[cal_id] = {"busy": cal_data.get("busy", [])}

            return {
                "time_min": time_min,
                "time_max": time_max,
                "timezone": timezone,
                "calendars": formatted_calendars,
            }

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {_sanitize_error(e)}"}
