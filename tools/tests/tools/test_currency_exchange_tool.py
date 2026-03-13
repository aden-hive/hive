"""Tests for the Frankfurter currency exchange tool."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.currency_exchange_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance with currency tools registered."""
    server = FastMCP("test")
    register_tools(server)
    return server


def get_tool_fn(mcp: FastMCP, tool_name: str):
    """Helper to retrieve a registered tool function."""
    return mcp._tool_manager._tools[tool_name].fn


class TestToolRegistration:
    """Registration-level checks."""

    def test_registers_expected_tools(self, mcp):
        tools = mcp._tool_manager._tools
        assert "currency_get_latest" in tools
        assert "currency_convert" in tools
        assert "currency_get_historical" in tools


class TestCurrencyGetLatest:
    """Tests for currency_get_latest."""

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "base": "USD",
            "date": "2026-03-10",
            "rates": {"EUR": 0.85903, "GBP": 0.72611},
        }
        mock_get.return_value = mock_response

        result = get_tool_fn(mcp, "currency_get_latest")(base="usd")

        assert result == {
            "base": "USD",
            "date": "2026-03-10",
            "rates": {"EUR": 0.85903, "GBP": 0.72611},
            "count": 2,
        }
        mock_get.assert_called_once_with(
            "https://api.frankfurter.dev/v1/latest",
            params={"base": "USD"},
            timeout=10.0,
        )

    def test_rejects_invalid_base_code(self, mcp):
        result = get_tool_fn(mcp, "currency_get_latest")(base="usdollar")
        assert result == {"error": "base must be a 3-letter currency code"}

    def test_empty_base_returns_error(self, mcp):
        result = get_tool_fn(mcp, "currency_get_latest")(base="")
        assert result == {"error": "base is required"}

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_unknown_currency_returns_helpful_error(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"message": "not found"}
        mock_get.return_value = mock_response

        result = get_tool_fn(mcp, "currency_get_latest")(base="BAD")
        assert result == {"error": "Unknown currency code: BAD"}

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_default_base_is_usd(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "base": "USD",
            "date": "2026-03-10",
            "rates": {"EUR": 0.85903},
        }
        mock_get.return_value = mock_response

        get_tool_fn(mcp, "currency_get_latest")()

        call_params = mock_get.call_args[1]["params"]
        assert call_params["base"] == "USD"


class TestCurrencyConvert:
    """Tests for currency_convert."""

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "amount": 10.0,
            "base": "USD",
            "date": "2026-03-10",
            "rates": {"EUR": 8.5903},
        }
        mock_get.return_value = mock_response

        result = get_tool_fn(mcp, "currency_convert")(
            amount=10, from_currency="usd", to_currency="eur"
        )

        assert result == {
            "from": "USD",
            "to": "EUR",
            "amount": 10,
            "converted": 8.5903,
            "rate": 0.85903,
            "date": "2026-03-10",
        }
        mock_get.assert_called_once_with(
            "https://api.frankfurter.dev/v1/latest",
            params={"amount": 10, "base": "USD", "symbols": "EUR"},
            timeout=10.0,
        )

    def test_same_currency_short_circuits(self, mcp):
        result = get_tool_fn(mcp, "currency_convert")(
            amount=25, from_currency="eur", to_currency="EUR"
        )
        assert result == {
            "from": "EUR",
            "to": "EUR",
            "amount": 25,
            "converted": 25,
            "rate": 1.0,
            "date": None,
        }

    def test_negative_amount_is_rejected(self, mcp):
        result = get_tool_fn(mcp, "currency_convert")(
            amount=-1, from_currency="USD", to_currency="EUR"
        )
        assert result == {"error": "amount must be greater than or equal to 0"}

    def test_missing_from_currency_returns_error(self, mcp):
        result = get_tool_fn(mcp, "currency_convert")(
            amount=100, from_currency="", to_currency="EUR"
        )
        assert result == {"error": "from_currency is required"}

    def test_missing_to_currency_returns_error(self, mcp):
        result = get_tool_fn(mcp, "currency_convert")(
            amount=100, from_currency="USD", to_currency=""
        )
        assert result == {"error": "to_currency is required"}

    def test_currency_codes_uppercased(self, mcp):
        with patch(
            "aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get"
        ) as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=MagicMock(
                    return_value={"base": "USD", "date": "2026-03-10", "rates": {"EUR": 92.0}}
                ),
            )
            result = get_tool_fn(mcp, "currency_convert")(
                amount=100, from_currency="usd", to_currency="eur"
            )
        assert result["from"] == "USD"
        assert result["to"] == "EUR"

    @patch(
        "aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get",
        side_effect=httpx.TimeoutException("timed out"),
    )
    def test_timeout_is_reported(self, _mock_get, mcp):
        result = get_tool_fn(mcp, "currency_convert")(
            amount=10, from_currency="USD", to_currency="EUR"
        )
        assert result == {"error": "Frankfurter API request timed out"}


class TestCurrencyGetHistorical:
    """Tests for currency_get_historical."""

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "base": "USD",
            "date": "2024-01-15",
            "rates": {"EUR": 0.9167},
        }
        mock_get.return_value = mock_response

        result = get_tool_fn(mcp, "currency_get_historical")(date="2024-01-15", base="usd")

        assert result == {
            "base": "USD",
            "date": "2024-01-15",
            "rates": {"EUR": 0.9167},
            "count": 1,
        }
        mock_get.assert_called_once_with(
            "https://api.frankfurter.dev/v1/2024-01-15",
            params={"base": "USD"},
            timeout=10.0,
        )

    def test_empty_date_returns_error(self, mcp):
        result = get_tool_fn(mcp, "currency_get_historical")(date="")
        assert result == {"error": "date is required (YYYY-MM-DD)"}

    def test_invalid_date_is_rejected_before_request(self, mcp):
        result = get_tool_fn(mcp, "currency_get_historical")(date="2024-13-40", base="USD")
        assert result == {"error": "date must use YYYY-MM-DD format"}

    def test_wrong_date_format_returns_error(self, mcp):
        result = get_tool_fn(mcp, "currency_get_historical")(date="15-01-2024")
        assert result == {"error": "date must use YYYY-MM-DD format"}

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_api_422_returns_invalid_date_error(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.json.return_value = {"message": "invalid date"}
        mock_get.return_value = mock_response

        result = get_tool_fn(mcp, "currency_get_historical")(date="2024-02-29", base="USD")
        assert result == {"error": "Invalid date: 2024-02-29"}

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_unknown_base_currency_returns_helpful_error(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"message": "not found"}
        mock_get.return_value = mock_response

        result = get_tool_fn(mcp, "currency_get_historical")(date="2024-01-15", base="BAD")
        assert result == {"error": "Unknown currency code: BAD"}
