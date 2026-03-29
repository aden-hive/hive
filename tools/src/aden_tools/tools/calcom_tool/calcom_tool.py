"""
Cal.com Tool - Open source scheduling infrastructure.

Supports:
- Booking management (list, get, create, cancel)
- Availability queries and schedule updates
- Event type configuration

API Reference: https://cal.com/docs/api-reference/v1
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

CALCOM_API_BASE = "https://api.cal.com/v1"
DEFAULT_TIMEOUT = 30.0


class _CalcomClient:
    """Internal client wrapping Cal.com API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get_params(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Add API key to query parameters."""
        p = {"apiKey": self._api_key}
        if params:
            p.update(params)
        return p

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid or expired Cal.com API key"}
        if response.status_code == 403:
            return {"error": "Access forbidden. Check API key permissions."}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Cal.com API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def list_bookings(
        self,
        status: str | None = None,
        event_type_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List bookings with optional filters."""
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if event_type_id:
            params["eventTypeId"] = event_type_id
        if start_date:
            params["afterStart"] = start_date
        if end_date:
            params["beforeEnd"] = end_date

        response = httpx.get(
            f"{CALCOM_API_BASE}/bookings",
            headers=self._headers,
            params=self._get_params(params),
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)

    def get_booking(self, booking_id: int) -> dict[str, Any]:
        """Get a single booking by ID."""
        response = httpx.get(
            f"{CALCOM_API_BASE}/bookings/{booking_id}",
            headers=self._headers,
            params=self._get_params(),
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)

    def create_booking(
        self,
        event_type_id: int,
        start: str,
        name: str,
        email: str,
        timezone: str = "UTC",
        language: str = "en",
        notes: str | None = None,
        guests: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new booking."""
        data: dict[str, Any] = {
            "eventTypeId": event_type_id,
            "start": start,
            "responses": {
                "name": name,
                "email": email,
            },
            "timeZone": timezone,
            "language": language,
            "metadata": metadata or {},
        }
        if notes:
            data["responses"]["notes"] = notes
        if guests:
            data["responses"]["guests"] = guests

        response = httpx.post(
            f"{CALCOM_API_BASE}/bookings",
            headers=self._headers,
            params=self._get_params(),
            json=data,
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)

    def cancel_booking(
        self,
        booking_id: int,
        cancel_reason: str | None = None,
    ) -> dict[str, Any]:
        """Cancel an existing booking."""
        data: dict[str, Any] = {}
        if cancel_reason:
            data["cancellationReason"] = cancel_reason

        response = httpx.request(
            "DELETE",
            f"{CALCOM_API_BASE}/bookings/{booking_id}",
            headers=self._headers,
            params=self._get_params(),
            json=data if data else None,
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)

    def get_availability(
        self,
        event_type_id: int,
        start_time: str,
        end_time: str,
        timezone: str = "UTC",
    ) -> dict[str, Any]:
        """Get available time slots for an event type."""
        params: dict[str, Any] = {
            "eventTypeId": event_type_id,
            "startTime": start_time,
            "endTime": end_time,
            "timeZone": timezone,
        }

        response = httpx.get(
            f"{CALCOM_API_BASE}/slots",
            headers=self._headers,
            params=self._get_params(params),
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)

    def list_schedules(self) -> dict[str, Any]:
        """List all schedules for the authenticated user."""
        response = httpx.get(
            f"{CALCOM_API_BASE}/schedules",
            headers=self._headers,
            params=self._get_params(),
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)

    def update_schedule(
        self,
        schedule_id: int,
        name: str | None = None,
        timezone: str | None = None,
        availability: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Update an existing schedule."""
        data: dict[str, Any] = {}
        if name:
            data["name"] = name
        if timezone:
            data["timeZone"] = timezone
        if availability:
            data["availability"] = availability

        response = httpx.patch(
            f"{CALCOM_API_BASE}/schedules/{schedule_id}",
            headers=self._headers,
            params=self._get_params(),
            json=data,
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)

    def list_event_types(self) -> dict[str, Any]:
        """List all event types."""
        response = httpx.get(
            f"{CALCOM_API_BASE}/event-types",
            headers=self._headers,
            params=self._get_params(),
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)

    def get_event_type(self, event_type_id: int) -> dict[str, Any]:
        """Get a single event type by ID."""
        response = httpx.get(
            f"{CALCOM_API_BASE}/event-types/{event_type_id}",
            headers=self._headers,
            params=self._get_params(),
            timeout=DEFAULT_TIMEOUT,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Cal.com tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get Cal.com API key from credential manager or environment."""
        if credentials is not None:
            api_key = credentials.get("calcom")
            if api_key is not None and not isinstance(api_key, str):
                return None
            return api_key
        return os.getenv("CALCOM_API_KEY")

    def _get_client() -> _CalcomClient | dict[str, str]:
        """Get a Cal.com client, or return an error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Cal.com API key not configured",
                "help": (
                    "Set CALCOM_API_KEY environment variable or configure via credential store"
                ),
            }
        return _CalcomClient(api_key)

    # --- Bookings ---

    @mcp.tool()
    def calcom_list_bookings(
        status: str | None = None,
        event_type_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
    ) -> dict:
        """
        List Cal.com bookings with optional filters.

        Use this when you need to:
        - View upcoming or past bookings
        - Filter bookings by status or event type
        - Get bookings within a date range

        Args:
            status: Filter by status - "upcoming", "recurring", "past", "cancelled"
            event_type_id: Filter by specific event type ID
            start_date: Filter bookings after this date (ISO 8601 format)
            end_date: Filter bookings before this date (ISO 8601 format)
            limit: Maximum number of bookings to return (default: 50)

        Returns:
            Dict with list of bookings or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.list_bookings(
                status=status,
                event_type_id=event_type_id,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def calcom_get_booking(booking_id: int) -> dict:
        """
        Get detailed information about a specific booking.

        Use this when you need to:
        - Get full details of a booking including attendees
        - Check meeting link and location details
        - Review booking metadata and responses

        Args:
            booking_id: The unique ID of the booking

        Returns:
            Dict with booking details or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.get_booking(booking_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def calcom_create_booking(
        event_type_id: int,
        start: str,
        name: str,
        email: str,
        timezone: str = "UTC",
        language: str = "en",
        notes: str | None = None,
        guests: list[str] | None = None,
    ) -> dict:
        """
        Create a new booking for an event type.

        Use this when you need to:
        - Schedule a meeting with someone
        - Book an available time slot
        - Create appointments programmatically

        Args:
            event_type_id: The event type ID to book
            start: Start time in ISO 8601 format (e.g., "2024-01-20T14:00:00Z")
            name: Name of the person booking
            email: Email of the person booking
            timezone: Timezone for the booking (default: "UTC")
            language: Language for the booking confirmation (default: "en")
            notes: Optional notes or message for the booking
            guests: Optional list of additional guest emails

        Returns:
            Dict with created booking details or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not event_type_id:
            return {"error": "event_type_id is required"}
        if not start:
            return {"error": "start time is required"}
        if not name:
            return {"error": "name is required"}
        if not email:
            return {"error": "email is required"}

        try:
            return client.create_booking(
                event_type_id=event_type_id,
                start=start,
                name=name,
                email=email,
                timezone=timezone,
                language=language,
                notes=notes,
                guests=guests,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def calcom_cancel_booking(
        booking_id: int,
        reason: str | None = None,
    ) -> dict:
        """
        Cancel an existing booking.

        Use this when you need to:
        - Cancel a scheduled meeting
        - Free up a time slot

        Args:
            booking_id: The unique ID of the booking to cancel
            reason: Optional cancellation reason

        Returns:
            Dict with cancellation confirmation or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not booking_id:
            return {"error": "booking_id is required"}

        try:
            return client.cancel_booking(booking_id, cancel_reason=reason)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Availability ---

    @mcp.tool()
    def calcom_get_availability(
        event_type_id: int,
        start_time: str,
        end_time: str,
        timezone: str = "UTC",
    ) -> dict:
        """
        Get available time slots for booking.

        Use this when you need to:
        - Find available times for scheduling
        - Check what slots are open for a meeting
        - Offer booking options to users

        Args:
            event_type_id: The event type to check availability for
            start_time: Start of availability window (ISO 8601 format)
            end_time: End of availability window (ISO 8601 format)
            timezone: Timezone for the slots (default: "UTC")

        Returns:
            Dict with available time slots or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not event_type_id:
            return {"error": "event_type_id is required"}
        if not start_time or not end_time:
            return {"error": "start_time and end_time are required"}

        try:
            return client.get_availability(
                event_type_id=event_type_id,
                start_time=start_time,
                end_time=end_time,
                timezone=timezone,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def calcom_update_schedule(
        schedule_id: int,
        name: str | None = None,
        timezone: str | None = None,
        availability: list[dict] | None = None,
    ) -> dict:
        """
        Update a user's availability schedule.

        Use this when you need to:
        - Change schedule name or timezone
        - Modify availability windows

        Args:
            schedule_id: The schedule ID to update
            name: New name for the schedule
            timezone: New timezone (e.g., "America/New_York")
            availability: List of availability rules, each with days (list of
                ints 0-6) and startTime/endTime (e.g. "09:00", "17:00")

        Returns:
            Dict with updated schedule or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not schedule_id:
            return {"error": "schedule_id is required"}

        try:
            return client.update_schedule(
                schedule_id=schedule_id,
                name=name,
                timezone=timezone,
                availability=availability,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def calcom_list_schedules() -> dict:
        """
        List all availability schedules for the authenticated user.

        Use this when you need to:
        - Discover schedule IDs before updating availability
        - View configured schedules and their settings

        Returns:
            Dict with list of schedules or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.list_schedules()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Event Types ---

    @mcp.tool()
    def calcom_list_event_types() -> dict:
        """
        List all configured event types.

        Use this when you need to:
        - See what meeting types are available
        - Get event type IDs for booking
        - Review event configurations

        Returns:
            Dict with list of event types or error
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
    def calcom_get_event_type(event_type_id: int) -> dict:
        """
        Get detailed information about an event type.

        Use this when you need to:
        - Get duration, location, and configuration of an event type
        - Check booking questions and requirements
        - Review event type settings

        Args:
            event_type_id: The event type ID

        Returns:
            Dict with event type details or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not event_type_id:
            return {"error": "event_type_id is required"}

        try:
            return client.get_event_type(event_type_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
