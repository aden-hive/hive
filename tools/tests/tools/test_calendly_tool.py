"""Tests for Calendly tool with FastMCP."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.calendly_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def calendly_list_event_types_fn(mcp: FastMCP):
    """Register and return the calendly_list_event_types tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["calendly_list_event_types"].fn


@pytest.fixture
def calendly_get_availability_fn(mcp: FastMCP):
    """Register and return the calendly_get_availability tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["calendly_get_availability"].fn


@pytest.fixture
def calendly_get_booking_link_fn(mcp: FastMCP):
    """Register and return the calendly_get_booking_link tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["calendly_get_booking_link"].fn


@pytest.fixture
def calendly_cancel_event_fn(mcp: FastMCP):
    """Register and return the calendly_cancel_event tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["calendly_cancel_event"].fn


class TestCalendlyCredentials:
    """Tests for Calendly credential handling."""

    def test_no_credentials_returns_error(self, calendly_list_event_types_fn, monkeypatch):
        """List event types without credentials returns helpful error."""
        monkeypatch.delenv("CALENDLY_API_TOKEN", raising=False)
        monkeypatch.delenv("CALENDLY_ACCESS_TOKEN", raising=False)

        result = calendly_list_event_types_fn()

        assert "error" in result
        assert "Calendly credentials not configured" in result["error"]
        assert "help" in result


class TestCalendlyListEventTypes:
    """Tests for calendly_list_event_types tool."""

    def test_list_event_types_success(self, calendly_list_event_types_fn, monkeypatch):
        """List event types returns event types with scheduling URLs."""
        monkeypatch.setenv("CALENDLY_API_TOKEN", "test-token")

        with (
            patch(
                "aden_tools.tools.calendly_tool.calendly_tool.httpx.request",
                side_effect=_calendly_list_responses(),
            ),
        ):
            result = calendly_list_event_types_fn()

        assert result["success"] is True
        assert result["count"] == 1
        assert len(result["event_types"]) == 1
        assert result["event_types"][0]["name"] == "15 Minute Meeting"
        assert result["event_types"][0]["scheduling_url"] == "https://calendly.com/me/15min"

    def test_list_event_types_api_error(self, calendly_list_event_types_fn, monkeypatch):
        """API error returns appropriate message."""
        monkeypatch.setenv("CALENDLY_API_TOKEN", "test-token")

        with (
            patch(
                "aden_tools.tools.calendly_tool.calendly_tool.httpx.request",
            ) as mock_request,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_request.return_value = mock_resp

            result = calendly_list_event_types_fn()

        assert "error" in result
        assert "Invalid or expired" in result["error"]


class TestCalendlyGetAvailability:
    """Tests for calendly_get_availability tool."""

    def test_get_availability_success(self, calendly_get_availability_fn, monkeypatch):
        """Get availability returns available times."""
        monkeypatch.setenv("CALENDLY_API_TOKEN", "test-token")
        event_uri = "https://api.calendly.com/event_types/et1"

        with (
            patch(
                "aden_tools.tools.calendly_tool.calendly_tool.httpx.request",
            ) as mock_request,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "collection": [
                    {"resource": {"start_time": "2026-02-01T14:00:00Z", "invitees_remaining": 1}},
                    {"resource": {"start_time": "2026-02-01T14:30:00Z", "invitees_remaining": 1}},
                ]
            }
            mock_request.return_value = mock_resp

            result = calendly_get_availability_fn(event_type_uri=event_uri)

        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["available_times"]) == 2
        assert result["available_times"][0]["start_time"] == "2026-02-01T14:00:00Z"

    def test_get_availability_date_range_validation(
        self, calendly_get_availability_fn, monkeypatch
    ):
        """Date range exceeding 7 days returns error."""
        monkeypatch.setenv("CALENDLY_API_TOKEN", "test-token")

        result = calendly_get_availability_fn(
            event_type_uri="https://api.calendly.com/event_types/et1",
            start_time="2026-01-01T00:00:00Z",
            end_time="2026-01-15T00:00:00Z",
        )

        assert "error" in result
        assert "7" in result["error"]
        assert "max_days" in result


class TestCalendlyGetBookingLink:
    """Tests for calendly_get_booking_link tool."""

    def test_get_booking_link_success(self, calendly_get_booking_link_fn, monkeypatch):
        """Get booking link returns scheduling URL."""
        monkeypatch.setenv("CALENDLY_API_TOKEN", "test-token")
        event_uri = "https://api.calendly.com/event_types/et1"

        with (
            patch(
                "aden_tools.tools.calendly_tool.calendly_tool.httpx.request",
            ) as mock_request,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "resource": {
                    "uri": event_uri,
                    "name": "15 Minute Meeting",
                    "scheduling_url": "https://calendly.com/me/15min",
                }
            }
            mock_request.return_value = mock_resp

            result = calendly_get_booking_link_fn(event_type_uri=event_uri)

        assert result["success"] is True
        assert result["scheduling_url"] == "https://calendly.com/me/15min"
        assert result["name"] == "15 Minute Meeting"

    def test_get_booking_link_not_found(self, calendly_get_booking_link_fn, monkeypatch):
        """Event type not found returns error."""
        monkeypatch.setenv("CALENDLY_API_TOKEN", "test-token")

        with (
            patch(
                "aden_tools.tools.calendly_tool.calendly_tool.httpx.request",
            ) as mock_request,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_request.return_value = mock_resp

            result = calendly_get_booking_link_fn(
                event_type_uri="https://api.calendly.com/event_types/nonexistent"
            )

        assert "error" in result
        assert "not found" in result["error"].lower()


class TestCalendlyCancelEvent:
    """Tests for calendly_cancel_event tool."""

    def test_cancel_event_success(self, calendly_cancel_event_fn, monkeypatch):
        """Cancel event returns success."""
        monkeypatch.setenv("CALENDLY_API_TOKEN", "test-token")
        event_uri = "https://api.calendly.com/scheduled_events/ev1"

        with (
            patch(
                "aden_tools.tools.calendly_tool.calendly_tool.httpx.request",
            ) as mock_request,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {}
            mock_request.return_value = mock_resp

            result = calendly_cancel_event_fn(event_uri=event_uri)

        assert result["success"] is True
        assert "message" in result
        assert "cancel" in result["message"].lower()
        mock_request.assert_called_once()
        call_url = mock_request.call_args[0][1]
        assert call_url == f"{event_uri}/cancellation"

    def test_cancel_event_with_reason(self, calendly_cancel_event_fn, monkeypatch):
        """Cancel event with reason sends reason in body."""
        monkeypatch.setenv("CALENDLY_API_TOKEN", "test-token")

        with (
            patch(
                "aden_tools.tools.calendly_tool.calendly_tool.httpx.request",
            ) as mock_request,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_request.return_value = mock_resp

            calendly_cancel_event_fn(
                event_uri="https://api.calendly.com/scheduled_events/ev1",
                reason="Meeting rescheduled",
            )

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["json"] == {"reason": "Meeting rescheduled"}


def _calendly_list_responses():
    """Return side_effect list: users/me then event_types (for list_event_types)."""
    resp1 = MagicMock()
    resp1.status_code = 200
    resp1.json.return_value = {"resource": {"uri": "https://api.calendly.com/users/me123"}}

    resp2 = MagicMock()
    resp2.status_code = 200
    resp2.json.return_value = {
        "collection": [
            {
                "resource": {
                    "uri": "https://api.calendly.com/event_types/et1",
                    "name": "15 Minute Meeting",
                    "slug": "15min",
                    "active": True,
                    "scheduling_url": "https://calendly.com/me/15min",
                    "duration": 15,
                    "kind": "solo",
                }
            }
        ]
    }

    return [resp1, resp2]
