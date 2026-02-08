"""Time Tool - Time manipulation and timezone utilities."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, available_timezones

from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register time tools with the MCP server."""

    @mcp.tool()
    def time_difference_tool(
        start_datetime: str,
        end_datetime: str,
        unit: str = "seconds",
    ) -> dict:
        """
        Calculate duration between two datetimes.

        Args:
            start_datetime: ISO 8601 datetime string (e.g., "2024-01-15T10:30:00Z")
            end_datetime: ISO 8601 datetime string
            unit: Unit for result ("days", "hours", "minutes", "seconds")

        Returns:
            dict with difference in specified unit and breakdown
        """
        valid_units = ["days", "hours", "minutes", "seconds"]
        if unit not in valid_units:
            return {"error": f"Invalid unit. Must be one of: {', '.join(valid_units)}"}

        try:
            start = datetime.fromisoformat(start_datetime.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_datetime.replace("Z", "+00:00"))

            diff = end - start
            total_seconds = diff.total_seconds()

            # Calculate breakdown
            days = diff.days
            hours = int(total_seconds // 3600)
            minutes = int(total_seconds // 60)
            seconds = int(total_seconds)

            # Calculate result in requested unit
            result_value = {
                "days": diff.days + (diff.seconds / 86400),
                "hours": total_seconds / 3600,
                "minutes": total_seconds / 60,
                "seconds": total_seconds,
            }[unit]

            return {
                "success": True,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "difference": result_value,
                "unit": unit,
                "breakdown": {
                    "days": days,
                    "hours": hours,
                    "minutes": minutes,
                    "seconds": seconds,
                },
            }

        except ValueError as e:
            return {"error": f"Invalid datetime format: {str(e)}. Use ISO 8601 format."}
        except Exception as e:
            return {"error": f"Failed to calculate time difference: {str(e)}"}

    @mcp.tool()
    def format_datetime_tool(
        datetime_str: str,
        format_style: str = "iso",
        timezone_name: str | None = None,
    ) -> dict:
        """
        Format datetime in various styles.

        Args:
            datetime_str: ISO 8601 datetime string
            format_style: Style ("iso", "relative", "short", "long", "date_only", "time_only")
            timezone_name: IANA timezone name (e.g., "America/New_York") or None for UTC

        Returns:
            dict with formatted datetime string
        """
        valid_styles = ["iso", "relative", "short", "long", "date_only", "time_only"]
        if format_style not in valid_styles:
            return {"error": f"Invalid format_style. Must be one of: {', '.join(valid_styles)}"}

        try:
            dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))

            # Convert to specified timezone
            if timezone_name:
                try:
                    tz = ZoneInfo(timezone_name)
                    dt = dt.astimezone(tz)
                except Exception as e:
                    return {"error": f"Invalid timezone: {str(e)}"}

            # Format based on style
            if format_style == "iso":
                formatted = dt.isoformat()
            elif format_style == "relative":
                now = datetime.now(timezone.utc)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                diff = now - dt
                if diff.total_seconds() < 60:
                    formatted = "just now"
                elif diff.total_seconds() < 3600:
                    formatted = f"{int(diff.total_seconds() / 60)} minutes ago"
                elif diff.total_seconds() < 86400:
                    formatted = f"{int(diff.total_seconds() / 3600)} hours ago"
                else:
                    formatted = f"{diff.days} days ago"
            elif format_style == "short":
                formatted = dt.strftime("%Y-%m-%d %H:%M")
            elif format_style == "long":
                formatted = dt.strftime("%B %d, %Y at %I:%M %p")
            elif format_style == "date_only":
                formatted = dt.strftime("%Y-%m-%d")
            elif format_style == "time_only":
                formatted = dt.strftime("%H:%M:%S")

            return {
                "success": True,
                "input_datetime": datetime_str,
                "formatted": formatted,
                "format_style": format_style,
                "timezone": timezone_name or "UTC",
            }

        except ValueError as e:
            return {"error": f"Invalid datetime format: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to format datetime: {str(e)}"}

    @mcp.tool()
    def parse_datetime_tool(
        datetime_input: str,
        input_format: str = "iso",
        timezone_name: str = "UTC",
    ) -> dict:
        """
        Parse datetime strings in various formats.

        Args:
            datetime_input: Datetime string to parse
            input_format: Format hint ("iso", "us", "eu", "timestamp")
            timezone_name: IANA timezone name to interpret the datetime in

        Returns:
            dict with parsed datetime in ISO format
        """
        try:
            tz = ZoneInfo(timezone_name)
        except Exception as e:
            return {"error": f"Invalid timezone: {str(e)}"}

        try:
            if input_format == "iso":
                dt = datetime.fromisoformat(datetime_input.replace("Z", "+00:00"))
            elif input_format == "timestamp":
                dt = datetime.fromtimestamp(float(datetime_input), tz=timezone.utc)
            elif input_format == "us":  # MM/DD/YYYY HH:MM:SS
                dt = datetime.strptime(datetime_input, "%m/%d/%Y %H:%M:%S")
                dt = dt.replace(tzinfo=tz)
            elif input_format == "eu":  # DD/MM/YYYY HH:MM:SS
                dt = datetime.strptime(datetime_input, "%d/%m/%Y %H:%M:%S")
                dt = dt.replace(tzinfo=tz)
            else:
                return {"error": f"Invalid input_format: {input_format}"}

            return {
                "success": True,
                "input": datetime_input,
                "parsed_datetime": dt.isoformat(),
                "input_format": input_format,
                "timezone": timezone_name,
            }

        except ValueError as e:
            return {"error": f"Failed to parse datetime: {str(e)}"}
        except Exception as e:
            return {"error": f"Parsing error: {str(e)}"}

    @mcp.tool()
    def add_time_tool(
        datetime_str: str,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
    ) -> dict:
        """
        Add or subtract duration from a datetime.

        Args:
            datetime_str: ISO 8601 datetime string
            days: Days to add (negative to subtract)
            hours: Hours to add (negative to subtract)
            minutes: Minutes to add (negative to subtract)
            seconds: Seconds to add (negative to subtract)

        Returns:
            dict with new datetime after adding/subtracting duration
        """
        try:
            dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
            delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
            new_dt = dt + delta

            return {
                "success": True,
                "original_datetime": datetime_str,
                "new_datetime": new_dt.isoformat(),
                "added": {
                    "days": days,
                    "hours": hours,
                    "minutes": minutes,
                    "seconds": seconds,
                },
            }

        except ValueError as e:
            return {"error": f"Invalid datetime format: {str(e)}"}
        except Exception as e:
            return {"error": f"Failed to add time: {str(e)}"}

    @mcp.tool()
    def list_timezones_tool(
        search: str | None = None,
        limit: int = 50,
    ) -> dict:
        """
        List available IANA timezone names.

        Args:
            search: Optional search filter (case-insensitive substring match)
            limit: Maximum number of timezones to return

        Returns:
            dict with list of timezone names
        """
        try:
            all_timezones = sorted(available_timezones())

            if search:
                search_lower = search.lower()
                filtered = [tz for tz in all_timezones if search_lower in tz.lower()]
            else:
                filtered = all_timezones

            # Apply limit
            result_timezones = filtered[:limit]

            return {
                "success": True,
                "timezones": result_timezones,
                "count": len(result_timezones),
                "total_available": len(all_timezones),
                "search": search,
                "limit": limit,
            }

        except Exception as e:
            return {"error": f"Failed to list timezones: {str(e)}"}
