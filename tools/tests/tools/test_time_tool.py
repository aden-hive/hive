"""
Tests for the time tool.

Tests cover:
- Basic functionality (UTC and other timezones)
- Timezone validation
- Return format validation
- Edge cases (invalid timezone)
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastmcp import FastMCP

from aden_tools.tools.time_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test")


@pytest.fixture
def time_tool(mcp):
    """Register and return the time tool."""
    register_tools(mcp)
    # Get the registered tool function
    for tool in mcp._tool_manager._tools.values():
        if tool.name == "get_current_time":
            return tool.fn
    raise RuntimeError("get_current_time tool not found")


class TestGetCurrentTime:
    """Tests for get_current_time tool."""

    def test_returns_dict(self, time_tool):
        """Tool should return a dictionary."""
        result = time_tool()
        assert isinstance(result, dict)

    def test_default_timezone_is_utc(self, time_tool):
        """Default timezone should be UTC."""
        result = time_tool()
        assert result["timezone"] == "UTC"

    def test_returns_required_fields(self, time_tool):
        """Tool should return all required fields."""
        result = time_tool()
        required_fields = ["datetime", "date", "time", "timezone", "day_of_week", "unix_timestamp"]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

    def test_date_format(self, time_tool):
        """Date should be in YYYY-MM-DD format."""
        result = time_tool()
        # Validate format by parsing
        datetime.strptime(result["date"], "%Y-%m-%d")

    def test_time_format(self, time_tool):
        """Time should be in HH:MM:SS format."""
        result = time_tool()
        # Validate format by parsing
        datetime.strptime(result["time"], "%H:%M:%S")

    def test_datetime_is_iso_format(self, time_tool):
        """Datetime should be valid ISO 8601 format."""
        result = time_tool()
        # Should parse without error
        datetime.fromisoformat(result["datetime"])

    def test_unix_timestamp_is_int(self, time_tool):
        """Unix timestamp should be an integer."""
        result = time_tool()
        assert isinstance(result["unix_timestamp"], int)

    def test_day_of_week_is_string(self, time_tool):
        """Day of week should be a string like 'Monday'."""
        result = time_tool()
        valid_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        assert result["day_of_week"] in valid_days

    def test_custom_timezone(self, time_tool):
        """Tool should accept custom timezone."""
        result = time_tool(timezone="America/New_York")
        assert result["timezone"] == "America/New_York"

    def test_asia_timezone(self, time_tool):
        """Tool should work with Asia timezones."""
        result = time_tool(timezone="Asia/Kolkata")
        assert result["timezone"] == "Asia/Kolkata"

    def test_europe_timezone(self, time_tool):
        """Tool should work with Europe timezones."""
        result = time_tool(timezone="Europe/London")
        assert result["timezone"] == "Europe/London"

    def test_invalid_timezone_returns_error(self, time_tool):
        """Invalid timezone should return error dict."""
        result = time_tool(timezone="Invalid/Timezone")
        assert "error" in result

    def test_time_is_current(self, time_tool):
        """Returned time should be close to actual current time."""
        before = datetime.now(ZoneInfo("UTC"))
        result = time_tool()
        after = datetime.now(ZoneInfo("UTC"))

        result_dt = datetime.fromisoformat(result["datetime"])
        assert before <= result_dt <= after

    def test_different_timezones_same_timestamp(self, time_tool):
        """Different timezones should have same unix timestamp."""
        utc_result = time_tool(timezone="UTC")
        ist_result = time_tool(timezone="Asia/Kolkata")

        # Unix timestamps should be within 1 second of each other
        assert abs(utc_result["unix_timestamp"] - ist_result["unix_timestamp"]) <= 1


class TestToolRegistration:
    """Tests for tool registration."""

    def test_tool_is_registered(self, mcp):
        """Tool should be registered with MCP."""
        register_tools(mcp)
        tool_names = [t.name for t in mcp._tool_manager._tools.values()]
        assert "get_current_time" in tool_names

    def test_tool_has_description(self, mcp):
        """Tool should have a description."""
        register_tools(mcp)
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_current_time":
                assert tool.description is not None
                assert len(tool.description) > 0
                break
