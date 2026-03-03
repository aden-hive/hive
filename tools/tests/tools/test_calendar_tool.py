"""Tests for Google Calendar tools (FastMCP)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.calendar_tool import register_tools


@pytest.fixture
def calendar_tools(mcp: FastMCP):
    """Register and return calendar tool functions."""
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {
        "list_events": tools["calendar_list_events"].fn,
        "get_event": tools["calendar_get_event"].fn,
        "create_event": tools["calendar_create_event"].fn,
        "update_event": tools["calendar_update_event"].fn,
        "delete_event": tools["calendar_delete_event"].fn,
        "list_calendars": tools["calendar_list_calendars"].fn,
        "get_calendar": tools["calendar_get_calendar"].fn,
        "check_availability": tools["calendar_check_availability"].fn,
    }


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Create a mock httpx.Response."""
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.json.return_value = json_data or {}
    return mock


class TestCredentialErrors:
    """Tests for missing credentials handling."""

    def test_list_events_no_credentials(self, calendar_tools, monkeypatch):
        """list_events without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)

        result = calendar_tools["list_events"]()

        assert "error" in result
        assert "Calendar credentials not configured" in result["error"]
        assert "help" in result
        assert "GOOGLE_ACCESS_TOKEN" in result["help"]

    def test_get_event_no_credentials(self, calendar_tools, monkeypatch):
        """get_event without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)

        result = calendar_tools["get_event"](event_id="test-event-id")

        assert "error" in result
        assert "Calendar credentials not configured" in result["error"]

    def test_create_event_no_credentials(self, calendar_tools, monkeypatch):
        """create_event without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)

        result = calendar_tools["create_event"](
            summary="Test Event",
            start_time="2024-01-15T09:00:00Z",
            end_time="2024-01-15T10:00:00Z",
        )

        assert "error" in result
        assert "Calendar credentials not configured" in result["error"]

    def test_update_event_no_credentials(self, calendar_tools, monkeypatch):
        """update_event without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)

        result = calendar_tools["update_event"](event_id="test-event-id")

        assert "error" in result
        assert "Calendar credentials not configured" in result["error"]

    def test_delete_event_no_credentials(self, calendar_tools, monkeypatch):
        """delete_event without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)

        result = calendar_tools["delete_event"](event_id="test-event-id")

        assert "error" in result
        assert "Calendar credentials not configured" in result["error"]

    def test_list_calendars_no_credentials(self, calendar_tools, monkeypatch):
        """list_calendars without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)

        result = calendar_tools["list_calendars"]()

        assert "error" in result
        assert "Calendar credentials not configured" in result["error"]

    def test_get_calendar_no_credentials(self, calendar_tools, monkeypatch):
        """get_calendar without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)

        result = calendar_tools["get_calendar"](calendar_id="primary")

        assert "error" in result
        assert "Calendar credentials not configured" in result["error"]

    def test_check_availability_no_credentials(self, calendar_tools, monkeypatch):
        """check_availability without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)

        result = calendar_tools["check_availability"](
            time_min="2024-01-15T00:00:00Z",
            time_max="2024-01-16T00:00:00Z",
        )

        assert "error" in result
        assert "Calendar credentials not configured" in result["error"]


class TestParameterValidation:
    """Tests for parameter validation."""

    def test_list_events_max_results_too_low(self, calendar_tools, monkeypatch):
        """max_results below 1 returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["list_events"](max_results=0)

        assert "error" in result
        assert "max_results" in result["error"]

    def test_list_events_max_results_too_high(self, calendar_tools, monkeypatch):
        """max_results above 2500 returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["list_events"](max_results=2501)

        assert "error" in result
        assert "max_results" in result["error"]

    def test_get_event_missing_event_id(self, calendar_tools, monkeypatch):
        """get_event without event_id returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["get_event"](event_id="")

        assert "error" in result
        assert "event_id" in result["error"]

    def test_create_event_missing_summary(self, calendar_tools, monkeypatch):
        """create_event without summary returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["create_event"](
            summary="",
            start_time="2024-01-15T09:00:00Z",
            end_time="2024-01-15T10:00:00Z",
        )

        assert "error" in result
        assert "summary" in result["error"]

    def test_create_event_missing_start_time(self, calendar_tools, monkeypatch):
        """create_event without start_time returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["create_event"](
            summary="Test Event",
            start_time="",
            end_time="2024-01-15T10:00:00Z",
        )

        assert "error" in result
        assert "start_time" in result["error"]

    def test_create_event_missing_end_time(self, calendar_tools, monkeypatch):
        """create_event without end_time returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["create_event"](
            summary="Test Event",
            start_time="2024-01-15T09:00:00Z",
            end_time="",
        )

        assert "error" in result
        assert "end_time" in result["error"]

    def test_update_event_missing_event_id(self, calendar_tools, monkeypatch):
        """update_event without event_id returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["update_event"](event_id="")

        assert "error" in result
        assert "event_id" in result["error"]

    def test_delete_event_missing_event_id(self, calendar_tools, monkeypatch):
        """delete_event without event_id returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["delete_event"](event_id="")

        assert "error" in result
        assert "event_id" in result["error"]

    def test_list_calendars_max_results_too_high(self, calendar_tools, monkeypatch):
        """list_calendars max_results above 250 returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["list_calendars"](max_results=251)

        assert "error" in result
        assert "max_results" in result["error"]

    def test_get_calendar_missing_calendar_id(self, calendar_tools, monkeypatch):
        """get_calendar without calendar_id returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["get_calendar"](calendar_id="")

        assert "error" in result
        assert "calendar_id" in result["error"]

    def test_check_availability_missing_time_min(self, calendar_tools, monkeypatch):
        """check_availability without time_min returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["check_availability"](
            time_min="",
            time_max="2024-01-16T00:00:00Z",
        )

        assert "error" in result
        assert "time_min" in result["error"]

    def test_check_availability_missing_time_max(self, calendar_tools, monkeypatch):
        """check_availability without time_max returns error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["check_availability"](
            time_min="2024-01-15T00:00:00Z",
            time_max="",
        )

        assert "error" in result
        assert "time_max" in result["error"]


class TestMockedAPIResponses:
    """Tests with mocked API responses."""

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_list_events_success(self, mock_get, calendar_tools, monkeypatch):
        """list_events returns formatted events on success."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(
            200,
            {
                "items": [
                    {
                        "id": "event1",
                        "summary": "Team Meeting",
                        "start": {"dateTime": "2024-01-15T09:00:00Z"},
                        "end": {"dateTime": "2024-01-15T10:00:00Z"},
                        "status": "confirmed",
                        "htmlLink": "https://calendar.google.com/event?eid=xxx",
                    }
                ]
            },
        )

        result = calendar_tools["list_events"](
            time_min="2024-01-15T00:00:00Z",
            max_results=10,
        )

        assert "events" in result
        assert len(result["events"]) == 1
        assert result["events"][0]["summary"] == "Team Meeting"
        assert result["total"] == 1

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_list_events_empty(self, mock_get, calendar_tools, monkeypatch):
        """list_events handles empty calendar."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(200, {"items": []})

        result = calendar_tools["list_events"](time_min="2024-01-15T00:00:00Z")

        assert "events" in result
        assert len(result["events"]) == 0
        assert result["total"] == 0

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.post")
    def test_create_event_success(self, mock_post, calendar_tools, monkeypatch):
        """create_event returns created event details."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_post.return_value = _mock_response(
            200,
            {
                "id": "new-event-id",
                "summary": "New Event",
                "start": {"dateTime": "2024-01-15T09:00:00Z"},
                "end": {"dateTime": "2024-01-15T10:00:00Z"},
                "status": "confirmed",
            },
        )

        result = calendar_tools["create_event"](
            summary="New Event",
            start_time="2024-01-15T09:00:00Z",
            end_time="2024-01-15T10:00:00Z",
        )

        assert "id" in result
        assert result["summary"] == "New Event"

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.delete")
    def test_delete_event_success(self, mock_delete, calendar_tools, monkeypatch):
        """delete_event returns success message."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_delete.return_value = _mock_response(204)

        result = calendar_tools["delete_event"](event_id="event123")

        assert result["success"] is True
        assert "event123" in result["message"]

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_list_calendars_success(self, mock_get, calendar_tools, monkeypatch):
        """list_calendars returns formatted calendar list."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(
            200,
            {
                "items": [
                    {
                        "id": "primary",
                        "summary": "My Calendar",
                        "primary": True,
                        "accessRole": "owner",
                    },
                    {
                        "id": "team@group.calendar.google.com",
                        "summary": "Team Calendar",
                        "primary": False,
                        "accessRole": "reader",
                    },
                ]
            },
        )

        result = calendar_tools["list_calendars"]()

        assert "calendars" in result
        assert len(result["calendars"]) == 2
        assert result["calendars"][0]["primary"] is True
        assert result["total"] == 2

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.post")
    def test_check_availability_success(self, mock_post, calendar_tools, monkeypatch):
        """check_availability returns busy periods."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_post.return_value = _mock_response(
            200,
            {
                "calendars": {
                    "primary": {
                        "busy": [
                            {
                                "start": "2024-01-15T09:00:00Z",
                                "end": "2024-01-15T10:00:00Z",
                            }
                        ]
                    }
                }
            },
        )

        result = calendar_tools["check_availability"](
            time_min="2024-01-15T00:00:00Z",
            time_max="2024-01-16T00:00:00Z",
        )

        assert "calendars" in result
        assert "primary" in result["calendars"]
        assert len(result["calendars"]["primary"]["busy"]) == 1

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_unauthorized_returns_error(self, mock_get, calendar_tools, monkeypatch):
        """401 response returns appropriate error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "invalid-token")

        mock_get.return_value = _mock_response(401, {"error": {"message": "Invalid credentials"}})

        result = calendar_tools["list_events"](time_min="2024-01-15T00:00:00Z")

        assert "error" in result
        assert "Invalid or expired OAuth token" in result["error"]

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_rate_limit_returns_error(self, mock_get, calendar_tools, monkeypatch):
        """429 response returns rate limit error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(429)

        result = calendar_tools["list_events"](time_min="2024-01-15T00:00:00Z")

        assert "error" in result
        assert "Rate limit" in result["error"]

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_not_found_returns_error(self, mock_get, calendar_tools, monkeypatch):
        """404 response returns not found error."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(404)

        result = calendar_tools["get_event"](event_id="nonexistent")

        assert "error" in result
        assert "not found" in result["error"]


class TestCredentialManager:
    """Tests for CredentialManager integration."""

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_uses_credential_store_adapter_when_provided(self, mock_get, mcp, monkeypatch):
        """Tool uses CredentialStoreAdapter when provided."""
        from aden_tools.credentials import CredentialStoreAdapter

        # Don't set env var - only use credential store adapter
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)

        # Create credential store adapter with test token
        creds = CredentialStoreAdapter.for_testing({"google": "test-oauth-token"})
        register_tools(mcp, credentials=creds)

        list_events_fn = mcp._tool_manager._tools["calendar_list_events"].fn

        # Mock the API call to verify credentials work
        mock_get.return_value = _mock_response(200, {"items": []})

        result = list_events_fn()

        # Should NOT get credential error since manager has the token
        assert "Calendar credentials not configured" not in result.get("error", "")
        assert "events" in result


class TestTokenRefresh:
    """Tests for OAuth token refresh functionality."""

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_expired_token_returns_helpful_error(self, mock_get, calendar_tools, monkeypatch):
        """401 response with simple token suggests re-authorization."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "expired-token")

        mock_get.return_value = _mock_response(401, {"error": {"message": "Token expired"}})

        result = calendar_tools["list_events"](time_min="2024-01-15T00:00:00Z")

        assert "error" in result
        assert "expired" in result["error"].lower() or "invalid" in result["error"].lower()
        assert "help" in result

    @patch("aden_tools.tools.calendar_tool.calendar_tool._create_lifecycle_manager")
    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_auto_refresh_uses_lifecycle_manager(
        self, mock_get, mock_create_lifecycle, mcp, monkeypatch
    ):
        """Token auto-refresh uses TokenLifecycleManager when available."""
        pytest.importorskip("framework.credentials", reason="Requires framework.credentials module")
        from unittest.mock import MagicMock

        from framework.credentials import CredentialStore

        from aden_tools.credentials import CredentialStoreAdapter

        # Clear env var
        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)

        # Create mock lifecycle manager
        mock_lifecycle = MagicMock()
        mock_token = MagicMock()
        mock_token.access_token = "refreshed-token"
        mock_lifecycle.sync_get_valid_token.return_value = mock_token
        mock_create_lifecycle.return_value = mock_lifecycle

        # Create credential store with OAuth tokens
        store = CredentialStore.for_testing(
            {
                "google": {
                    "access_token": "old-token",
                    "refresh_token": "test-refresh-token",
                }
            }
        )
        creds = CredentialStoreAdapter(store)

        register_tools(mcp, credentials=creds)

        list_events_fn = mcp._tool_manager._tools["calendar_list_events"].fn

        # Mock successful API response
        mock_get.return_value = _mock_response(200, {"items": []})

        result = list_events_fn()

        # Should have used lifecycle manager for token
        assert mock_lifecycle.sync_get_valid_token.called
        assert "events" in result

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_no_lifecycle_manager_without_refresh_token(self, mock_get, mcp, monkeypatch):
        """Lifecycle manager not created without refresh_token."""
        pytest.importorskip("framework.credentials", reason="Requires framework.credentials module")
        from framework.credentials import CredentialStore

        from aden_tools.credentials import CredentialStoreAdapter

        monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)

        # Create store with only access_token (no refresh_token)
        store = CredentialStore.for_testing(
            {
                "google": {
                    "access_token": "simple-token",
                }
            }
        )
        creds = CredentialStoreAdapter(store)

        register_tools(mcp, credentials=creds)

        list_events_fn = mcp._tool_manager._tools["calendar_list_events"].fn

        mock_get.return_value = _mock_response(200, {"items": []})

        result = list_events_fn()

        # Should work using simple token
        assert "events" in result

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_graceful_degradation_on_refresh_failure(self, mock_get, calendar_tools, monkeypatch):
        """If token refresh fails, returns helpful error message."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "invalid-token")

        # Simulate 401 (expired token that couldn't be refreshed)
        mock_get.return_value = _mock_response(401, {"error": {"message": "Invalid credentials"}})

        result = calendar_tools["list_events"](time_min="2024-01-15T00:00:00Z")

        # Should get error with helpful message
        assert "error" in result
        assert "help" in result
        # Should suggest re-authorization
        assert "setup" in result["help"].lower() or "token" in result["help"].lower()


class TestUpdateEventPatch:
    """Tests for PATCH-based update_event."""

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.patch")
    def test_update_event_patch_success(self, mock_patch, calendar_tools, monkeypatch):
        """update_event uses PATCH and returns updated event."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_patch.return_value = _mock_response(
            200,
            {
                "id": "event123",
                "summary": "Updated Title",
                "start": {"dateTime": "2024-01-15T09:00:00Z"},
                "end": {"dateTime": "2024-01-15T10:00:00Z"},
                "status": "confirmed",
            },
        )

        result = calendar_tools["update_event"](
            event_id="event123",
            summary="Updated Title",
        )

        assert result["summary"] == "Updated Title"
        # Verify PATCH was called (not GET+PUT)
        mock_patch.assert_called_once()
        call_kwargs = mock_patch.call_args
        assert call_kwargs[1]["json"] == {"summary": "Updated Title"}

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.patch")
    def test_update_event_partial_fields(self, mock_patch, calendar_tools, monkeypatch):
        """update_event sends only provided fields in PATCH body."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_patch.return_value = _mock_response(
            200,
            {
                "id": "event123",
                "summary": "Existing",
                "description": "New desc",
                "location": "New place",
            },
        )

        result = calendar_tools["update_event"](
            event_id="event123",
            description="New desc",
            location="New place",
        )

        assert "error" not in result
        call_kwargs = mock_patch.call_args
        body = call_kwargs[1]["json"]
        assert body == {"description": "New desc", "location": "New place"}
        assert "summary" not in body

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.patch")
    def test_update_event_with_timezone(self, mock_patch, calendar_tools, monkeypatch):
        """update_event includes timezone in start/end when provided."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_patch.return_value = _mock_response(200, {"id": "event123"})

        result = calendar_tools["update_event"](
            event_id="event123",
            start_time="2024-01-15T09:00:00",
            end_time="2024-01-15T10:00:00",
            timezone="America/New_York",
        )

        assert "error" not in result
        body = mock_patch.call_args[1]["json"]
        assert body["start"]["timeZone"] == "America/New_York"
        assert body["end"]["timeZone"] == "America/New_York"


class TestAllDayEvents:
    """Tests for all-day event support."""

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.post")
    def test_create_all_day_event(self, mock_post, calendar_tools, monkeypatch):
        """create_event with all_day=True uses date field."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_post.return_value = _mock_response(
            200,
            {
                "id": "allday1",
                "summary": "Birthday",
                "start": {"date": "2024-06-15"},
                "end": {"date": "2024-06-16"},
            },
        )

        result = calendar_tools["create_event"](
            summary="Birthday",
            start_time="2024-06-15",
            end_time="2024-06-16",
            all_day=True,
        )

        assert "error" not in result
        assert result["id"] == "allday1"
        body = mock_post.call_args[1]["json"]
        assert "date" in body["start"]
        assert "dateTime" not in body["start"]
        assert body["start"]["date"] == "2024-06-15"
        assert body["end"]["date"] == "2024-06-16"

    def test_create_all_day_event_invalid_start_format(self, calendar_tools, monkeypatch):
        """create_event with all_day=True rejects non-date start_time."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["create_event"](
            summary="Bad Event",
            start_time="2024-01-15T09:00:00Z",
            end_time="2024-01-16",
            all_day=True,
        )

        assert "error" in result
        assert "date-only format" in result["error"]
        assert "start_time" in result["error"]

    def test_create_all_day_event_invalid_end_format(self, calendar_tools, monkeypatch):
        """create_event with all_day=True rejects non-date end_time."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["create_event"](
            summary="Bad Event",
            start_time="2024-01-15",
            end_time="2024-01-15T10:00:00Z",
            all_day=True,
        )

        assert "error" in result
        assert "date-only format" in result["error"]
        assert "end_time" in result["error"]

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.patch")
    def test_update_to_all_day_event(self, mock_patch, calendar_tools, monkeypatch):
        """update_event can convert timed event to all-day."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_patch.return_value = _mock_response(
            200,
            {
                "id": "event123",
                "start": {"date": "2024-01-15"},
                "end": {"date": "2024-01-16"},
            },
        )

        result = calendar_tools["update_event"](
            event_id="event123",
            start_time="2024-01-15",
            end_time="2024-01-16",
            all_day=True,
        )

        assert "error" not in result
        body = mock_patch.call_args[1]["json"]
        assert body["start"] == {"date": "2024-01-15"}
        assert body["end"] == {"date": "2024-01-16"}


class TestTimezoneValidation:
    """Tests for timezone validation."""

    def test_invalid_timezone_create_event(self, calendar_tools, monkeypatch):
        """create_event rejects invalid timezone."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["create_event"](
            summary="Test",
            start_time="2024-01-15T09:00:00",
            end_time="2024-01-15T10:00:00",
            timezone="Not/A_Timezone",
        )

        assert "error" in result
        assert "Invalid timezone" in result["error"]
        assert "Not/A_Timezone" in result["error"]
        assert "IANA format" in result["error"]

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.post")
    def test_valid_timezone_passes(self, mock_post, calendar_tools, monkeypatch):
        """create_event accepts valid timezone."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_post.return_value = _mock_response(200, {"id": "event123"})

        result = calendar_tools["create_event"](
            summary="Test",
            start_time="2024-01-15T09:00:00",
            end_time="2024-01-15T10:00:00",
            timezone="America/New_York",
        )

        assert "error" not in result
        body = mock_post.call_args[1]["json"]
        assert body["start"]["timeZone"] == "America/New_York"

    def test_invalid_timezone_update_event(self, calendar_tools, monkeypatch):
        """update_event rejects invalid timezone."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["update_event"](
            event_id="event123",
            start_time="2024-01-15T09:00:00",
            timezone="Fake/Zone",
        )

        assert "error" in result
        assert "Invalid timezone" in result["error"]

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.post")
    def test_all_day_event_ignores_timezone(self, mock_post, calendar_tools, monkeypatch):
        """create_event with all_day=True skips timezone validation."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_post.return_value = _mock_response(200, {"id": "allday1"})

        # Even with an invalid timezone, all_day should not validate it
        result = calendar_tools["create_event"](
            summary="Birthday",
            start_time="2024-06-15",
            end_time="2024-06-16",
            timezone="Not/A_Timezone",
            all_day=True,
        )

        assert "error" not in result


class TestCreateEventWithAttendees:
    """Tests for create_event with attendees."""

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.post")
    def test_create_event_with_attendees(self, mock_post, calendar_tools, monkeypatch):
        """create_event includes attendees in request body."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_post.return_value = _mock_response(
            200,
            {
                "id": "event123",
                "summary": "Team Meeting",
                "attendees": [
                    {"email": "alice@example.com"},
                    {"email": "bob@example.com"},
                ],
            },
        )

        result = calendar_tools["create_event"](
            summary="Team Meeting",
            start_time="2024-01-15T09:00:00Z",
            end_time="2024-01-15T10:00:00Z",
            attendees=["alice@example.com", "bob@example.com"],
        )

        assert "error" not in result
        body = mock_post.call_args[1]["json"]
        assert body["attendees"] == [
            {"email": "alice@example.com"},
            {"email": "bob@example.com"},
        ]
        # Verify sendUpdates is "all" by default
        params = mock_post.call_args[1]["params"]
        assert params["sendUpdates"] == "all"

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.post")
    def test_create_event_with_attendees_includes_conference_data(
        self, mock_post, calendar_tools, monkeypatch
    ):
        """create_event with attendees auto-generates conferenceData with unique requestId."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_post.return_value = _mock_response(200, {"id": "event123"})

        calendar_tools["create_event"](
            summary="Meeting",
            start_time="2024-01-15T09:00:00Z",
            end_time="2024-01-15T10:00:00Z",
            attendees=["alice@example.com"],
        )

        body = mock_post.call_args[1]["json"]
        assert "conferenceData" in body
        conf = body["conferenceData"]
        assert "createRequest" in conf
        assert conf["createRequest"]["conferenceSolutionKey"]["type"] == "hangoutsMeet"
        # requestId should start with "meet-" and have a unique hex suffix
        request_id = conf["createRequest"]["requestId"]
        assert request_id.startswith("meet-")
        assert len(request_id) > len("meet-")

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.post")
    def test_create_event_with_attendees_sets_conference_data_version(
        self, mock_post, calendar_tools, monkeypatch
    ):
        """create_event with attendees includes conferenceDataVersion=1 in query params."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_post.return_value = _mock_response(200, {"id": "event123"})

        calendar_tools["create_event"](
            summary="Meeting",
            start_time="2024-01-15T09:00:00Z",
            end_time="2024-01-15T10:00:00Z",
            attendees=["alice@example.com"],
        )

        params = mock_post.call_args[1]["params"]
        assert params["conferenceDataVersion"] == 1

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.post")
    def test_create_event_without_attendees_no_conference_data(
        self, mock_post, calendar_tools, monkeypatch
    ):
        """create_event without attendees does not add conferenceData."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_post.return_value = _mock_response(200, {"id": "event123"})

        calendar_tools["create_event"](
            summary="Solo Event",
            start_time="2024-01-15T09:00:00Z",
            end_time="2024-01-15T10:00:00Z",
        )

        body = mock_post.call_args[1]["json"]
        assert "conferenceData" not in body
        params = mock_post.call_args[1]["params"]
        assert "conferenceDataVersion" not in params


class TestListEventsOutputFields:
    """Tests for list_events output field coverage."""

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_list_events_includes_description_and_hangout_link(
        self, mock_get, calendar_tools, monkeypatch
    ):
        """list_events output includes description and hangoutLink fields."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(
            200,
            {
                "items": [
                    {
                        "id": "event1",
                        "summary": "Meeting",
                        "start": {"dateTime": "2024-01-15T09:00:00Z"},
                        "end": {"dateTime": "2024-01-15T10:00:00Z"},
                        "status": "confirmed",
                        "description": "Discuss Q1 goals",
                        "hangoutLink": "https://meet.google.com/abc-defg-hij",
                    }
                ]
            },
        )

        result = calendar_tools["list_events"](time_min="2024-01-15T00:00:00Z")

        event = result["events"][0]
        assert event["description"] == "Discuss Q1 goals"
        assert event["hangoutLink"] == "https://meet.google.com/abc-defg-hij"

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_list_events_includes_attendees(self, mock_get, calendar_tools, monkeypatch):
        """list_events output includes attendee emails when present."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(
            200,
            {
                "items": [
                    {
                        "id": "event1",
                        "summary": "Team Sync",
                        "start": {"dateTime": "2024-01-15T09:00:00Z"},
                        "end": {"dateTime": "2024-01-15T10:00:00Z"},
                        "attendees": [
                            {"email": "alice@example.com", "responseStatus": "accepted"},
                            {"email": "bob@example.com", "responseStatus": "needsAction"},
                        ],
                    }
                ]
            },
        )

        result = calendar_tools["list_events"](time_min="2024-01-15T00:00:00Z")

        event = result["events"][0]
        assert "attendees" in event
        assert event["attendees"] == ["alice@example.com", "bob@example.com"]

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_list_events_no_attendees_omits_field(self, mock_get, calendar_tools, monkeypatch):
        """list_events without attendees omits the attendees field."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(
            200,
            {
                "items": [
                    {
                        "id": "event1",
                        "summary": "Solo Focus",
                        "start": {"dateTime": "2024-01-15T09:00:00Z"},
                        "end": {"dateTime": "2024-01-15T10:00:00Z"},
                    }
                ]
            },
        )

        result = calendar_tools["list_events"](time_min="2024-01-15T00:00:00Z")

        event = result["events"][0]
        assert "attendees" not in event

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_list_events_max_results_2500_accepted(self, mock_get, calendar_tools, monkeypatch):
        """list_events accepts max_results=2500 (the API maximum)."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(200, {"items": []})

        result = calendar_tools["list_events"](max_results=2500)

        assert "error" not in result
        assert result["total"] == 0


class TestIsNotNoneBehavior:
    """Tests for 'is not None' checks allowing empty strings."""

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.post")
    def test_create_event_empty_description_included(self, mock_post, calendar_tools, monkeypatch):
        """create_event with description='' includes it in body (not None check)."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_post.return_value = _mock_response(200, {"id": "event123"})

        calendar_tools["create_event"](
            summary="Test",
            start_time="2024-01-15T09:00:00Z",
            end_time="2024-01-15T10:00:00Z",
            description="",
        )

        body = mock_post.call_args[1]["json"]
        assert "description" in body
        assert body["description"] == ""

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.post")
    def test_create_event_empty_location_included(self, mock_post, calendar_tools, monkeypatch):
        """create_event with location='' includes it in body (not None check)."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_post.return_value = _mock_response(200, {"id": "event123"})

        calendar_tools["create_event"](
            summary="Test",
            start_time="2024-01-15T09:00:00Z",
            end_time="2024-01-15T10:00:00Z",
            location="",
        )

        body = mock_post.call_args[1]["json"]
        assert "location" in body
        assert body["location"] == ""

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.post")
    def test_create_event_none_description_excluded(self, mock_post, calendar_tools, monkeypatch):
        """create_event with description=None does not include it in body."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_post.return_value = _mock_response(200, {"id": "event123"})

        calendar_tools["create_event"](
            summary="Test",
            start_time="2024-01-15T09:00:00Z",
            end_time="2024-01-15T10:00:00Z",
        )

        body = mock_post.call_args[1]["json"]
        assert "description" not in body
        assert "location" not in body


class TestEmptyPatchGuard:
    """Tests for empty PATCH body guard on update."""

    def test_update_event_no_fields_returns_error(self, calendar_tools, monkeypatch):
        """update_event with no fields to change returns error instead of empty PATCH."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        result = calendar_tools["update_event"](event_id="event123")

        assert "error" in result
        assert "No fields to update" in result["error"]


class TestRemoveAttendees:
    """Tests for remove_attendees on update_event."""

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.patch")
    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_remove_single_attendee(self, mock_get, mock_patch, calendar_tools, monkeypatch):
        """remove_attendees removes specified email and keeps the rest."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        # GET returns current event with 3 attendees
        mock_get.return_value = _mock_response(
            200,
            {
                "id": "event123",
                "summary": "Stand Up",
                "attendees": [
                    {"email": "alice@example.com", "responseStatus": "accepted"},
                    {"email": "bob@example.com", "responseStatus": "accepted"},
                    {"email": "charlie@example.com", "responseStatus": "needsAction"},
                ],
            },
        )
        mock_patch.return_value = _mock_response(
            200,
            {
                "id": "event123",
                "summary": "Stand Up",
                "attendees": [
                    {"email": "alice@example.com"},
                    {"email": "charlie@example.com"},
                ],
            },
        )

        result = calendar_tools["update_event"](
            event_id="event123",
            remove_attendees=["bob@example.com"],
        )

        assert "error" not in result
        # Verify GET was called to fetch current event
        mock_get.assert_called_once()
        # Verify PATCH body has bob removed
        body = mock_patch.call_args[1]["json"]
        attendee_emails = [a["email"] for a in body["attendees"]]
        assert "bob@example.com" not in attendee_emails
        assert "alice@example.com" in attendee_emails
        assert "charlie@example.com" in attendee_emails

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.patch")
    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_remove_attendees_case_insensitive(
        self, mock_get, mock_patch, calendar_tools, monkeypatch
    ):
        """remove_attendees matching is case-insensitive."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(
            200,
            {
                "id": "event123",
                "attendees": [
                    {"email": "Alice@Example.com"},
                    {"email": "bob@example.com"},
                ],
            },
        )
        mock_patch.return_value = _mock_response(200, {"id": "event123"})

        calendar_tools["update_event"](
            event_id="event123",
            remove_attendees=["alice@example.com"],
        )

        body = mock_patch.call_args[1]["json"]
        attendee_emails = [a["email"] for a in body["attendees"]]
        assert "Alice@Example.com" not in attendee_emails
        assert "bob@example.com" in attendee_emails

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.patch")
    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_remove_multiple_attendees(self, mock_get, mock_patch, calendar_tools, monkeypatch):
        """remove_attendees can remove multiple emails at once."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(
            200,
            {
                "id": "event123",
                "attendees": [
                    {"email": "alice@example.com"},
                    {"email": "bob@example.com"},
                    {"email": "charlie@example.com"},
                ],
            },
        )
        mock_patch.return_value = _mock_response(200, {"id": "event123"})

        calendar_tools["update_event"](
            event_id="event123",
            remove_attendees=["alice@example.com", "charlie@example.com"],
        )

        body = mock_patch.call_args[1]["json"]
        attendee_emails = [a["email"] for a in body["attendees"]]
        assert attendee_emails == ["bob@example.com"]

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.patch")
    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_remove_attendees_from_event_with_no_attendees(
        self, mock_get, mock_patch, calendar_tools, monkeypatch
    ):
        """remove_attendees on event with no attendees sends empty list."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(
            200,
            {"id": "event123", "summary": "Solo Event"},
        )
        mock_patch.return_value = _mock_response(200, {"id": "event123"})

        calendar_tools["update_event"](
            event_id="event123",
            remove_attendees=["nobody@example.com"],
        )

        body = mock_patch.call_args[1]["json"]
        assert body["attendees"] == []

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.patch")
    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_remove_attendees_sets_conference_data_version(
        self, mock_get, mock_patch, calendar_tools, monkeypatch
    ):
        """remove_attendees triggers conferenceDataVersion=1 in query params."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(
            200,
            {
                "id": "event123",
                "attendees": [{"email": "alice@example.com"}],
            },
        )
        mock_patch.return_value = _mock_response(200, {"id": "event123"})

        calendar_tools["update_event"](
            event_id="event123",
            remove_attendees=["alice@example.com"],
        )

        params = mock_patch.call_args[1]["params"]
        assert params["conferenceDataVersion"] == 1

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.get")
    def test_remove_attendees_get_fails_returns_error(self, mock_get, calendar_tools, monkeypatch):
        """remove_attendees returns error if GET to fetch event fails."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_get.return_value = _mock_response(404)

        result = calendar_tools["update_event"](
            event_id="event123",
            remove_attendees=["alice@example.com"],
        )

        assert "error" in result
        assert "not found" in result["error"]


class TestUpdateMeetLink:
    """Tests for add_meet_link on update_event."""

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.patch")
    def test_update_event_add_meet_link(self, mock_patch, calendar_tools, monkeypatch):
        """update_event with add_meet_link=True includes conferenceData."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_patch.return_value = _mock_response(
            200,
            {
                "id": "event123",
                "hangoutLink": "https://meet.google.com/abc-defg-hij",
            },
        )

        result = calendar_tools["update_event"](
            event_id="event123",
            add_meet_link=True,
        )

        assert "error" not in result
        body = mock_patch.call_args[1]["json"]
        assert "conferenceData" in body
        conf = body["conferenceData"]
        assert conf["createRequest"]["conferenceSolutionKey"]["type"] == "hangoutsMeet"
        assert conf["createRequest"]["requestId"].startswith("meet-")
        # conferenceDataVersion must be 1 for Meet link creation
        params = mock_patch.call_args[1]["params"]
        assert params["conferenceDataVersion"] == 1

    @patch("aden_tools.tools.calendar_tool.calendar_tool.httpx.patch")
    def test_update_event_without_meet_link_no_conference_data(
        self, mock_patch, calendar_tools, monkeypatch
    ):
        """update_event without add_meet_link does not add conferenceData."""
        monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "test-token")

        mock_patch.return_value = _mock_response(200, {"id": "event123", "summary": "Updated"})

        calendar_tools["update_event"](
            event_id="event123",
            summary="Updated",
        )

        body = mock_patch.call_args[1]["json"]
        assert "conferenceData" not in body
        # conferenceDataVersion should NOT be set for simple updates
        params = mock_patch.call_args[1]["params"]
        assert "conferenceDataVersion" not in params
