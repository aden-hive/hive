"""
Time Tool - Get current date and time for FastMCP.

Provides accurate current time for agents, especially useful for
long-running sessions where injected system prompt time goes stale.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register time tools with the MCP server."""

    @mcp.tool()
    def get_current_time(timezone: str = "UTC") -> dict:
        """
        Get the current date and time.

        Use this tool when you need accurate current time, especially in
        long-running sessions or when precision matters (e.g., scheduling,
        checking availability, time-sensitive operations).

        Args:
            timezone: IANA timezone name (e.g., "UTC", "America/New_York",
                     "Asia/Kolkata", "Europe/London"). Defaults to "UTC".

        Returns:
            Dictionary with datetime info:
            - datetime: Full ISO 8601 datetime string
            - date: Date in YYYY-MM-DD format
            - time: Time in HH:MM:SS format
            - timezone: The timezone used
            - day_of_week: Full day name (e.g., "Monday")
            - unix_timestamp: Unix timestamp (seconds since epoch)
        """
        try:
            tz = ZoneInfo(timezone)
            now = datetime.now(tz)

            return {
                "datetime": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "timezone": timezone,
                "day_of_week": now.strftime("%A"),
                "unix_timestamp": int(now.timestamp()),
            }

        except KeyError:
            return {"error": f"Invalid timezone: {timezone}"}
