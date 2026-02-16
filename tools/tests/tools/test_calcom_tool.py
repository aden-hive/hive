"""Tests for Cal.com tool with FastMCP."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.calcom_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-calcom")


@pytest.fixture
def calcom_tools(mcp: FastMCP, monkeypatch):
    """Register Cal.com tools and return tool functions."""
    monkeypatch.setenv("CALCOM_API_KEY", "test-api-key")
    register_tools(mcp)
    return {
        "list_bookings": mcp._tool_manager._tools["calcom_list_bookings"].fn,
        "get_booking": mcp._tool_manager._tools["calcom_get_booking"].fn,
        "create_booking": mcp._tool_manager._tools["calcom_create_booking"].fn,
        "cancel_booking": mcp._tool_manager._tools["calcom_cancel_booking"].fn,
        "get_availability": mcp._tool_manager._tools["calcom_get_availability"].fn,
        "update_schedule": mcp._tool_manager._tools["calcom_update_schedule"].fn,
        "list_schedules": mcp._tool_manager._tools["calcom_list_schedules"].fn,
        "list_event_types": mcp._tool_manager._tools["calcom_list_event_types"].fn,
        "get_event_type": mcp._tool_manager._tools["calcom_get_event_type"].fn,
    }


class TestToolRegistration:
    """Tests for tool registration."""

    def test_all_tools_registered(self, mcp: FastMCP, monkeypatch):
        """All 9 Cal.com tools are registered."""
        monkeypatch.setenv("CALCOM_API_KEY", "test-key")
        register_tools(mcp)

        expected_tools = [
            "calcom_list_bookings",
            "calcom_get_booking",
            "calcom_create_booking",
            "calcom_cancel_booking",
            "calcom_get_availability",
            "calcom_update_schedule",
            "calcom_list_schedules",
            "calcom_list_event_types",
            "calcom_get_event_type",
        ]

        for tool_name in expected_tools:
            assert tool_name in mcp._tool_manager._tools


class TestCredentialHandling:
    """Tests for credential handling."""

    def test_no_credentials_returns_error(self, mcp: FastMCP, monkeypatch):
        """Tools without credentials return helpful error."""
        monkeypatch.delenv("CALCOM_API_KEY", raising=False)
        register_tools(mcp)

        fn = mcp._tool_manager._tools["calcom_list_bookings"].fn
        result = fn()

        assert "error" in result
        assert "not configured" in result["error"]
        assert "help" in result

    def test_non_string_credential_returns_error(self, mcp: FastMCP, monkeypatch):
        """Non-string credential returns error dict instead of raising."""
        monkeypatch.delenv("CALCOM_API_KEY", raising=False)
        creds = MagicMock()
        creds.get.return_value = 12345  # non-string
        register_tools(mcp, credentials=creds)

        fn = mcp._tool_manager._tools["calcom_list_bookings"].fn
        result = fn()

        assert "error" in result
        assert "not configured" in result["error"]

    def test_credentials_from_env(self, mcp: FastMCP, monkeypatch):
        """Tools use credentials from environment variable."""
        monkeypatch.setenv("CALCOM_API_KEY", "test-key")
        register_tools(mcp)

        # Tool should not return credential error
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"bookings": []}
            mock_get.return_value = mock_response

            fn = mcp._tool_manager._tools["calcom_list_bookings"].fn
            result = fn()

            assert "error" not in result or "not configured" not in result.get("error", "")

            # Verify apiKey is in params
            call_kwargs = mock_get.call_args
            params = call_kwargs.kwargs.get("params", {})
            assert params.get("apiKey") == "test-key"


class TestListBookings:
    """Tests for calcom_list_bookings tool."""

    def test_list_bookings_success(self, calcom_tools, monkeypatch):
        """List bookings returns bookings on success."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "bookings": [
                    {"id": 1, "title": "Meeting 1"},
                    {"id": 2, "title": "Meeting 2"},
                ]
            }
            mock_get.return_value = mock_response

            result = calcom_tools["list_bookings"]()

            assert "bookings" in result
            assert len(result["bookings"]) == 2

    def test_list_bookings_with_filters(self, calcom_tools):
        """List bookings accepts filter parameters."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"bookings": []}
            mock_get.return_value = mock_response

            calcom_tools["list_bookings"](
                status="upcoming",
                event_type_id=123,
                start_date="2024-01-01",
                end_date="2024-01-31",
                limit=10,
            )

            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args
            params = call_kwargs.kwargs.get("params", {})
            assert params.get("status") == "upcoming"
            assert params.get("eventTypeId") == 123
            assert params.get("limit") == 10


class TestGetBooking:
    """Tests for calcom_get_booking tool."""

    def test_get_booking_success(self, calcom_tools):
        """Get booking returns booking details."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "booking": {"id": 123, "title": "Meeting", "status": "accepted"}
            }
            mock_get.return_value = mock_response

            result = calcom_tools["get_booking"](booking_id=123)

            assert "booking" in result

    def test_get_booking_not_found(self, calcom_tools):
        """Get booking returns error for non-existent booking."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_get.return_value = mock_response

            result = calcom_tools["get_booking"](booking_id=99999)

            assert "error" in result
            assert "not found" in result["error"].lower()


class TestCreateBooking:
    """Tests for calcom_create_booking tool."""

    def test_create_booking_success(self, calcom_tools):
        """Create booking succeeds with valid data."""
        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"id": 456, "status": "accepted"}
            mock_post.return_value = mock_response

            result = calcom_tools["create_booking"](
                event_type_id=123,
                start="2024-01-20T14:00:00Z",
                name="John Doe",
                email="john@example.com",
            )

            assert "id" in result

            # Verify request payload
            call_kwargs = mock_post.call_args
            json_data = call_kwargs.kwargs.get("json", {})
            assert json_data.get("language") == "en"
            assert json_data.get("metadata") == {}
            assert "metadata" not in json_data["responses"]

    def test_create_booking_missing_required_fields(self, calcom_tools):
        """Create booking returns error for missing required fields."""
        result = calcom_tools["create_booking"](
            event_type_id=123,
            start="2024-01-20T14:00:00Z",
            name="",  # Empty name
            email="john@example.com",
        )

        assert "error" in result


class TestCancelBooking:
    """Tests for calcom_cancel_booking tool."""

    def test_cancel_booking_success(self, calcom_tools):
        """Cancel booking succeeds."""
        with patch("httpx.request") as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_request.return_value = mock_response

            result = calcom_tools["cancel_booking"](booking_id=123)

            assert "error" not in result

            # Verify method and URL
            mock_request.assert_called_once()
            args = mock_request.call_args[0]
            assert args[0] == "DELETE"
            assert "/bookings/123" in args[1]

    def test_cancel_booking_with_reason(self, calcom_tools):
        """Cancel booking includes cancellation reason."""
        with patch("httpx.request") as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_request.return_value = mock_response

            calcom_tools["cancel_booking"](booking_id=123, reason="Schedule conflict")

            call_kwargs = mock_request.call_args
            json_data = call_kwargs.kwargs.get("json", {})
            assert json_data.get("cancellationReason") == "Schedule conflict"


class TestGetAvailability:
    """Tests for calcom_get_availability tool."""

    def test_get_availability_success(self, calcom_tools):
        """Get availability returns slots."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "slots": {
                    "2024-01-20": ["09:00", "10:00", "14:00"],
                }
            }
            mock_get.return_value = mock_response

            result = calcom_tools["get_availability"](
                event_type_id=123,
                start_time="2024-01-20T00:00:00Z",
                end_time="2024-01-21T00:00:00Z",
            )

            assert "slots" in result

    def test_get_availability_missing_required(self, calcom_tools):
        """Get availability returns error for missing required fields."""
        result = calcom_tools["get_availability"](
            event_type_id=123,
            start_time="",  # Empty
            end_time="2024-01-21T00:00:00Z",
        )

        assert "error" in result


class TestUpdateSchedule:
    """Tests for calcom_update_schedule tool."""

    def test_update_schedule_with_availability(self, calcom_tools):
        """Update schedule passes availability to the API."""
        with patch("httpx.patch") as mock_patch:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"schedule": {"id": 1}}
            mock_patch.return_value = mock_response

            avail = [{"days": [1, 2, 3, 4, 5], "startTime": "09:00", "endTime": "17:00"}]
            calcom_tools["update_schedule"](schedule_id=1, availability=avail)

            call_kwargs = mock_patch.call_args
            json_data = call_kwargs.kwargs.get("json", {})
            assert json_data["availability"] == avail


class TestListSchedules:
    """Tests for calcom_list_schedules tool."""

    def test_list_schedules_success(self, calcom_tools):
        """List schedules returns schedules on success."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "schedules": [
                    {"id": 1, "name": "Working Hours", "timeZone": "America/New_York"},
                ]
            }
            mock_get.return_value = mock_response

            result = calcom_tools["list_schedules"]()

            assert "schedules" in result
            assert len(result["schedules"]) == 1

    def test_list_schedules_empty(self, calcom_tools):
        """List schedules returns empty list when no schedules configured."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"schedules": []}
            mock_get.return_value = mock_response

            result = calcom_tools["list_schedules"]()

            assert result == {"schedules": []}


class TestListEventTypes:
    """Tests for calcom_list_event_types tool."""

    def test_list_event_types_success(self, calcom_tools):
        """List event types returns event types."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "event_types": [
                    {"id": 1, "title": "30 Min Meeting"},
                    {"id": 2, "title": "60 Min Meeting"},
                ]
            }
            mock_get.return_value = mock_response

            result = calcom_tools["list_event_types"]()

            assert "event_types" in result


class TestGetEventType:
    """Tests for calcom_get_event_type tool."""

    def test_get_event_type_success(self, calcom_tools):
        """Get event type returns details."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "event_type": {"id": 123, "title": "30 Min Meeting", "length": 30}
            }
            mock_get.return_value = mock_response

            result = calcom_tools["get_event_type"](event_type_id=123)

            assert "event_type" in result

    def test_get_event_type_missing_id(self, calcom_tools):
        """Get event type returns error for missing ID."""
        result = calcom_tools["get_event_type"](event_type_id=0)

        assert "error" in result


class TestErrorHandling:
    """Tests for error handling."""

    def test_401_unauthorized(self, calcom_tools):
        """401 response returns authentication error."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_get.return_value = mock_response

            result = calcom_tools["list_bookings"]()

            assert "error" in result
            assert "Invalid" in result["error"] or "expired" in result["error"]

    def test_429_rate_limit(self, calcom_tools):
        """429 response returns rate limit error."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_get.return_value = mock_response

            result = calcom_tools["list_bookings"]()

            assert "error" in result
            assert "rate limit" in result["error"].lower()

    def test_timeout_error(self, calcom_tools):
        """Timeout returns appropriate error."""
        with patch("httpx.get") as mock_get:
            mock_get.side_effect = httpx.TimeoutException("Request timed out")

            result = calcom_tools["list_bookings"]()

            assert "error" in result
            assert "timed out" in result["error"].lower()

    def test_network_error(self, calcom_tools):
        """Network error returns appropriate error."""
        with patch("httpx.get") as mock_get:
            mock_get.side_effect = httpx.RequestError("Connection failed")

            result = calcom_tools["list_bookings"]()

            assert "error" in result
            assert "error" in result["error"].lower()
