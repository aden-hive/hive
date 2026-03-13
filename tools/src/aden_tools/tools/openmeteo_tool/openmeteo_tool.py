"""
Open-Meteo Weather Tool - Get real-time weather and forecasts.

Free, open-source weather API. No API key or authentication required.
Provides current conditions and multi-day forecasts for any location.
"""

from __future__ import annotations

import httpx
from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register Open-Meteo weather tools with the MCP server."""

    @mcp.tool()
    def weather_get_current(latitude: float, longitude: float) -> dict:
        """
        Get current weather conditions for any location.

        No API key required. Uses the free Open-Meteo API.

        Args:
            latitude: Location latitude (e.g. 52.52 for Berlin, 40.71 for New York)
            longitude: Location longitude (e.g. 13.41 for Berlin, -74.01 for New York)

        Returns:
            Dictionary with current weather:
            - temperature: Current temperature in Celsius
            - windspeed: Wind speed in km/h
            - winddirection: Wind direction in degrees
            - weathercode: WMO weather code (0=clear, 1-3=cloudy, 45-48=fog, etc.)
            - is_day: 1 if daytime, 0 if nighttime
            - time: Observation time (ISO format)
        """
        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "current_weather": True,
            }
            response = httpx.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("current_weather", {"error": "No current weather data returned"})
        except httpx.HTTPStatusError as e:
            return {"error": f"API request failed: {e.response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def weather_get_forecast(latitude: float, longitude: float, days: int = 7) -> dict:
        """
        Get a multi-day weather forecast for any location.

        No API key required. Uses the free Open-Meteo API.

        Args:
            latitude: Location latitude (e.g. 52.52 for Berlin, 40.71 for New York)
            longitude: Location longitude (e.g. 13.41 for Berlin, -74.01 for New York)
            days: Number of forecast days (1-16, default 7)

        Returns:
            Dictionary with daily forecast:
            - dates: List of forecast dates
            - temperature_max: Daily maximum temperatures (Celsius)
            - temperature_min: Daily minimum temperatures (Celsius)
            - precipitation: Daily precipitation sum (mm)
            - weathercode: Daily WMO weather codes
        """
        try:
            if not 1 <= days <= 16:
                return {"error": "days must be between 1 and 16"}

            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                "forecast_days": days,
                "timezone": "auto",
            }
            response = httpx.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            daily = data.get("daily", {})
            return {
                "dates": daily.get("time", []),
                "temperature_max": daily.get("temperature_2m_max", []),
                "temperature_min": daily.get("temperature_2m_min", []),
                "precipitation": daily.get("precipitation_sum", []),
                "weathercode": daily.get("weathercode", []),
            }
        except httpx.HTTPStatusError as e:
            return {"error": f"API request failed: {e.response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
