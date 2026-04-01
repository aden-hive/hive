"""
Tests for Currency Exchange Rate tool.

Covers:
- _CurrencyExchangeClient methods (get_latest_rates, convert_currency, get_supported_currencies)
- Error handling (401, 429, non-200, API-level errors, timeout, network error)
- API key retrieval from environment variable
- All 3 MCP tool functions
- Input validation (amount <= 0)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aden_tools.tools.currency_exchange_tool.currency_exchange_tool import (
    EXCHANGERATE_API_BASE,
    _CurrencyExchangeClient,
    register_tools,
)

# ---------------------------------------------------------------------------
# _CurrencyExchangeClient tests
# ---------------------------------------------------------------------------


class TestCurrencyExchangeClient:
    def setup_method(self):
        self.client = _CurrencyExchangeClient("test_api_key_123")

    # --- _handle_response ---

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"result": "success", "conversion_rates": {"EUR": 0.92}}
        result = self.client._handle_response(response)
        assert result == {"result": "success", "conversion_rates": {"EUR": 0.92}}

    def test_handle_response_201_success(self):
        response = MagicMock()
        response.status_code = 201
        response.json.return_value = {"result": "success"}
        result = self.client._handle_response(response)
        assert "error" not in result

    def test_handle_response_401(self):
        response = MagicMock()
        response.status_code = 401
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Invalid API key" in result["error"]

    def test_handle_response_429(self):
        response = MagicMock()
        response.status_code = 429
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Rate limit" in result["error"]

    @pytest.mark.parametrize("status_code", [400, 403, 404, 500, 503])
    def test_handle_response_other_errors(self, status_code):
        response = MagicMock()
        response.status_code = status_code
        response.text = "Server error"
        result = self.client._handle_response(response)
        assert "error" in result
        assert str(status_code) in result["error"]

    @pytest.mark.parametrize(
        "error_type,expected_substring",
        [
            ("unsupported-code", "not supported"),
            ("malformed-request", "malformed"),
            ("invalid-key", "Invalid API key"),
            ("inactive-account", "inactive"),
            ("quota-reached", "quota"),
            ("unknown-error-type", "API error"),
        ],
    )
    def test_handle_response_api_level_errors(self, error_type, expected_substring):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"result": "error", "error-type": error_type}
        result = self.client._handle_response(response)
        assert "error" in result
        assert expected_substring in result["error"]

    # --- get_latest_rates ---

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_latest_rates_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "result": "success",
                    "base_code": "USD",
                    "time_last_update_unix": 1700000000,
                    "conversion_rates": {"EUR": 0.92, "INR": 83.5, "GBP": 0.79},
                }
            ),
        )
        result = self.client.get_latest_rates("USD")
        mock_get.assert_called_once_with(
            f"{EXCHANGERATE_API_BASE}/test_api_key_123/latest/USD",
            timeout=30.0,
        )
        assert result["base_code"] == "USD"
        assert result["conversion_rates"]["EUR"] == 0.92

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_latest_rates_lowercases_code(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"result": "success"})
        )
        self.client.get_latest_rates("usd")
        call_url = mock_get.call_args.args[0]
        assert "/latest/USD" in call_url

    # --- convert_currency ---

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_convert_currency_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "result": "success",
                    "base_code": "USD",
                    "target_code": "INR",
                    "conversion_rate": 83.5,
                    "conversion_result": 8350.0,
                    "time_last_update_unix": 1700000000,
                }
            ),
        )
        result = self.client.convert_currency("USD", "INR", 100.0)
        mock_get.assert_called_once_with(
            f"{EXCHANGERATE_API_BASE}/test_api_key_123/pair/USD/INR/100.0",
            timeout=30.0,
        )
        assert result["conversion_result"] == 8350.0
        assert result["conversion_rate"] == 83.5

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_convert_currency_lowercases_codes(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"result": "success"})
        )
        self.client.convert_currency("usd", "eur", 50.0)
        call_url = mock_get.call_args.args[0]
        assert "/pair/USD/EUR/" in call_url

    # --- get_supported_currencies ---

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_supported_currencies_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "result": "success",
                    "supported_codes": [["USD", "US Dollar"], ["EUR", "Euro"]],
                }
            ),
        )
        result = self.client.get_supported_currencies()
        mock_get.assert_called_once_with(
            f"{EXCHANGERATE_API_BASE}/test_api_key_123/codes",
            timeout=30.0,
        )
        assert result["supported_codes"] == [["USD", "US Dollar"], ["EUR", "Euro"]]


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_register_tools_registers_three_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 3

    def test_no_api_key_returns_error(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp)

        get_rates_fn = next(
            fn for fn in registered_fns if fn.__name__ == "currency_exchange_get_rates"
        )
        result = get_rates_fn(base_currency="USD")
        assert "error" in result
        assert "not configured" in result["error"]
        assert "help" in result

    def test_api_key_from_env_var(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp)

        get_rates_fn = next(
            fn for fn in registered_fns if fn.__name__ == "currency_exchange_get_rates"
        )

        with (
            patch.dict("os.environ", {"EXCHANGERATE_API_KEY": "env_key_abc"}),
            patch(
                "aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get"
            ) as mock_get,
        ):
            mock_get.return_value = MagicMock(
                status_code=200,
                json=MagicMock(
                    return_value={
                        "result": "success",
                        "base_code": "USD",
                        "time_last_update_unix": 1700000000,
                        "conversion_rates": {"EUR": 0.92},
                    }
                ),
            )
            result = get_rates_fn(base_currency="USD")

        assert result["success"] is True
        assert "env_key_abc" in mock_get.call_args.args[0]


# ---------------------------------------------------------------------------
# currency_exchange_get_rates tool
# ---------------------------------------------------------------------------


class TestGetRatesTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        self.env_patcher = patch.dict(
            "os.environ", {"EXCHANGERATE_API_KEY": "test_key_xyz"}
        )
        self.env_patcher.start()
        register_tools(self.mcp)

    def teardown_method(self):
        self.env_patcher.stop()

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_rates_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "result": "success",
                    "base_code": "USD",
                    "time_last_update_unix": 1700000000,
                    "conversion_rates": {"EUR": 0.92, "INR": 83.5},
                }
            ),
        )
        result = self._fn("currency_exchange_get_rates")(base_currency="USD")
        assert result["success"] is True
        assert result["base_currency"] == "USD"
        assert result["rates"]["EUR"] == 0.92
        assert result["rates"]["INR"] == 83.5
        assert result["last_updated"] == 1700000000

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_rates_api_error_propagates(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"result": "error", "error-type": "unsupported-code"}
            ),
        )
        result = self._fn("currency_exchange_get_rates")(base_currency="XYZ")
        assert "error" in result

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_rates_timeout(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("currency_exchange_get_rates")(base_currency="USD")
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_rates_network_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError("connection refused")
        result = self._fn("currency_exchange_get_rates")(base_currency="USD")
        assert "error" in result
        assert "Network error" in result["error"]


# ---------------------------------------------------------------------------
# currency_exchange_convert tool
# ---------------------------------------------------------------------------


class TestConvertTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        self.env_patcher = patch.dict(
            "os.environ", {"EXCHANGERATE_API_KEY": "test_key_xyz"}
        )
        self.env_patcher.start()
        register_tools(self.mcp)

    def teardown_method(self):
        self.env_patcher.stop()

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_convert_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "result": "success",
                    "base_code": "USD",
                    "target_code": "INR",
                    "conversion_rate": 83.5,
                    "conversion_result": 835.0,
                    "time_last_update_unix": 1700000000,
                }
            ),
        )
        result = self._fn("currency_exchange_convert")(
            from_currency="USD", to_currency="INR", amount=10.0
        )
        assert result["success"] is True
        assert result["from_currency"] == "USD"
        assert result["to_currency"] == "INR"
        assert result["original_amount"] == 10.0
        assert result["converted_amount"] == 835.0
        assert result["exchange_rate"] == 83.5

    def test_convert_zero_amount_rejected(self):
        result = self._fn("currency_exchange_convert")(
            from_currency="USD", to_currency="INR", amount=0
        )
        assert "error" in result
        assert "greater than 0" in result["error"]

    def test_convert_negative_amount_rejected(self):
        result = self._fn("currency_exchange_convert")(
            from_currency="USD", to_currency="INR", amount=-50.0
        )
        assert "error" in result
        assert "greater than 0" in result["error"]

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_convert_api_error_propagates(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"result": "error", "error-type": "unsupported-code"}
            ),
        )
        result = self._fn("currency_exchange_convert")(
            from_currency="USD", to_currency="XYZ", amount=100.0
        )
        assert "error" in result

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_convert_timeout(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timeout")
        result = self._fn("currency_exchange_convert")(
            from_currency="USD", to_currency="EUR", amount=100.0
        )
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_convert_network_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError("network error")
        result = self._fn("currency_exchange_convert")(
            from_currency="USD", to_currency="EUR", amount=100.0
        )
        assert "error" in result
        assert "Network error" in result["error"]


# ---------------------------------------------------------------------------
# currency_exchange_list_currencies tool
# ---------------------------------------------------------------------------


class TestListCurrenciesTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        self.env_patcher = patch.dict(
            "os.environ", {"EXCHANGERATE_API_KEY": "test_key_xyz"}
        )
        self.env_patcher.start()
        register_tools(self.mcp)

    def teardown_method(self):
        self.env_patcher.stop()

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_list_currencies_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "result": "success",
                    "supported_codes": [
                        ["USD", "US Dollar"],
                        ["EUR", "Euro"],
                        ["INR", "Indian Rupee"],
                    ],
                }
            ),
        )
        result = self._fn("currency_exchange_list_currencies")()
        assert result["success"] is True
        assert result["count"] == 3
        assert result["currencies"][0] == {"code": "USD", "name": "US Dollar"}
        assert result["currencies"][1] == {"code": "EUR", "name": "Euro"}
        assert result["currencies"][2] == {"code": "INR", "name": "Indian Rupee"}

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_list_currencies_api_error_propagates(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"result": "error", "error-type": "invalid-key"}
            ),
        )
        result = self._fn("currency_exchange_list_currencies")()
        assert "error" in result

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_list_currencies_timeout(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timeout")
        result = self._fn("currency_exchange_list_currencies")()
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_list_currencies_network_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError("network error")
        result = self._fn("currency_exchange_list_currencies")()
        assert "error" in result
        assert "Network error" in result["error"]

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_list_currencies_empty_list(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"result": "success", "supported_codes": []}
            ),
        )
        result = self._fn("currency_exchange_list_currencies")()
        assert result["success"] is True
        assert result["count"] == 0
        assert result["currencies"] == []

    def test_no_api_key_returns_error(self):
        mcp = MagicMock()
        fns = []
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp)

        list_fn = next(f for f in fns if f.__name__ == "currency_exchange_list_currencies")
        result = list_fn()
        assert "error" in result
        assert "not configured" in result["error"]
