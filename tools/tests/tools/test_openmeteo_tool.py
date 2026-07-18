"""Tests for openmeteo_tool - Open-Meteo current weather and forecasts."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.openmeteo_tool.openmeteo_tool import register_tools

HTTPX_GET = "aden_tools.tools.openmeteo_tool.openmeteo_tool.httpx.get"


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


def _mock_response(json_data: dict) -> MagicMock:
    """Create a mock httpx response returning the given JSON payload."""
    response = MagicMock()
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


def _http_error_response(status_code: int) -> MagicMock:
    """Create a mock httpx response whose raise_for_status raises."""
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"{status_code}", request=MagicMock(), response=response
    )
    return response


class TestWeatherGetCurrent:
    def test_successful_request(self, tool_fns):
        payload = {
            "current_weather": {
                "temperature": 21.4,
                "windspeed": 12.3,
                "winddirection": 250,
                "weathercode": 2,
                "is_day": 1,
                "time": "2026-07-18T12:00",
            }
        }
        with patch(HTTPX_GET, return_value=_mock_response(payload)) as mock_get:
            result = tool_fns["weather_get_current"](latitude=52.52, longitude=13.41)

        assert result["temperature"] == 21.4
        assert result["weathercode"] == 2
        params = mock_get.call_args.kwargs["params"]
        assert params["latitude"] == 52.52
        assert params["longitude"] == 13.41
        assert params["current_weather"] is True

    def test_missing_current_weather_in_response(self, tool_fns):
        with patch(HTTPX_GET, return_value=_mock_response({})):
            result = tool_fns["weather_get_current"](latitude=52.52, longitude=13.41)

        assert "error" in result

    def test_http_status_error(self, tool_fns):
        with patch(HTTPX_GET, return_value=_http_error_response(429)):
            result = tool_fns["weather_get_current"](latitude=52.52, longitude=13.41)

        assert result == {"error": "API request failed: 429"}

    def test_network_error(self, tool_fns):
        with patch(HTTPX_GET, side_effect=httpx.ConnectError("connection refused")):
            result = tool_fns["weather_get_current"](latitude=52.52, longitude=13.41)

        assert "error" in result
        assert "connection refused" in result["error"]

    def test_timeout_error(self, tool_fns):
        with patch(HTTPX_GET, side_effect=httpx.TimeoutException("timed out")):
            result = tool_fns["weather_get_current"](latitude=40.71, longitude=-74.01)

        assert "error" in result


class TestWeatherGetForecast:
    def test_successful_request(self, tool_fns):
        payload = {
            "daily": {
                "time": ["2026-07-18", "2026-07-19"],
                "temperature_2m_max": [25.1, 27.3],
                "temperature_2m_min": [15.2, 16.8],
                "precipitation_sum": [0.0, 2.4],
                "weathercode": [1, 61],
            }
        }
        with patch(HTTPX_GET, return_value=_mock_response(payload)) as mock_get:
            result = tool_fns["weather_get_forecast"](
                latitude=52.52, longitude=13.41, days=2
            )

        assert result["dates"] == ["2026-07-18", "2026-07-19"]
        assert result["temperature_max"] == [25.1, 27.3]
        assert result["temperature_min"] == [15.2, 16.8]
        assert result["precipitation"] == [0.0, 2.4]
        assert result["weathercode"] == [1, 61]
        params = mock_get.call_args.kwargs["params"]
        assert params["forecast_days"] == 2

    @pytest.mark.parametrize("days", [0, -1, 17, 100])
    def test_days_out_of_range(self, tool_fns, days):
        with patch(HTTPX_GET) as mock_get:
            result = tool_fns["weather_get_forecast"](
                latitude=52.52, longitude=13.41, days=days
            )

        assert result == {"error": "days must be between 1 and 16"}
        mock_get.assert_not_called()

    @pytest.mark.parametrize("days", [1, 16])
    def test_days_boundary_values_accepted(self, tool_fns, days):
        with patch(HTTPX_GET, return_value=_mock_response({"daily": {}})):
            result = tool_fns["weather_get_forecast"](
                latitude=52.52, longitude=13.41, days=days
            )

        assert "error" not in result

    def test_missing_daily_in_response(self, tool_fns):
        with patch(HTTPX_GET, return_value=_mock_response({})):
            result = tool_fns["weather_get_forecast"](latitude=52.52, longitude=13.41)

        assert result == {
            "dates": [],
            "temperature_max": [],
            "temperature_min": [],
            "precipitation": [],
            "weathercode": [],
        }

    def test_http_status_error(self, tool_fns):
        with patch(HTTPX_GET, return_value=_http_error_response(500)):
            result = tool_fns["weather_get_forecast"](latitude=52.52, longitude=13.41)

        assert result == {"error": "API request failed: 500"}

    def test_network_error(self, tool_fns):
        with patch(HTTPX_GET, side_effect=httpx.ConnectError("connection refused")):
            result = tool_fns["weather_get_forecast"](latitude=52.52, longitude=13.41)

        assert "error" in result
