"""
Tests for Currency Exchange Rate Tool.

Covers:
- _CurrencyExchangeClient response handling
- All 3 registered MCP tools
- Error cases: invalid key, rate limit, network errors, bad input
"""

from unittest.mock import MagicMock, patch

from aden_tools.tools.currency_exchange_tool.currency_exchange_tool import (
    _CurrencyExchangeClient,
    register_tools,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Build a fake httpx.Response for mocking."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data or {}
    mock.text = "OK"
    return mock


# ---------------------------------------------------------------------------
# Tests for _CurrencyExchangeClient
# ---------------------------------------------------------------------------

class TestCurrencyExchangeClient:
    """Unit tests for the internal API client."""

    def setup_method(self):
        self.client = _CurrencyExchangeClient(api_key="test_key")

    # --- get_latest_rates ---

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_latest_rates_success(self, mock_get):
        mock_get.return_value = _mock_response(json_data={
            "result": "success",
            "base_code": "USD",
            "time_last_update_unix": 1700000000,
            "conversion_rates": {"EUR": 0.92, "INR": 83.5},
        })
        result = self.client.get_latest_rates("USD")
        assert result["base_code"] == "USD"
        assert "EUR" in result["conversion_rates"]

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_latest_rates_invalid_code(self, mock_get):
        mock_get.return_value = _mock_response(json_data={
            "result": "error",
            "error-type": "unsupported-code",
        })
        result = self.client.get_latest_rates("XYZ")
        assert "error" in result
        assert "not supported" in result["error"]

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_latest_rates_rate_limited(self, mock_get):
        mock_get.return_value = _mock_response(status_code=429)
        result = self.client.get_latest_rates("USD")
        assert "error" in result
        assert "Rate limit" in result["error"]

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_latest_rates_invalid_key(self, mock_get):
        mock_get.return_value = _mock_response(status_code=401)
        result = self.client.get_latest_rates("USD")
        assert "error" in result
        assert "Invalid API key" in result["error"]

    # --- convert_currency ---

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_convert_currency_success(self, mock_get):
        mock_get.return_value = _mock_response(json_data={
            "result": "success",
            "base_code": "USD",
            "target_code": "INR",
            "conversion_rate": 83.5,
            "conversion_result": 8350.0,
            "time_last_update_unix": 1700000000,
        })
        result = self.client.convert_currency("USD", "INR", 100)
        assert result["conversion_result"] == 8350.0
        assert result["conversion_rate"] == 83.5

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_convert_currency_unsupported_code(self, mock_get):
        mock_get.return_value = _mock_response(json_data={
            "result": "error",
            "error-type": "unsupported-code",
        })
        result = self.client.convert_currency("USD", "XYZ", 100)
        assert "error" in result

    # --- get_supported_currencies ---

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_supported_currencies_success(self, mock_get):
        mock_get.return_value = _mock_response(json_data={
            "result": "success",
            "supported_codes": [
                ["USD", "US Dollar"],
                ["EUR", "Euro"],
                ["INR", "Indian Rupee"],
            ],
        })
        result = self.client.get_supported_currencies()
        assert len(result["supported_codes"]) == 3

    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_handle_response_quota_reached(self, mock_get):
        mock_get.return_value = _mock_response(json_data={
            "result": "error",
            "error-type": "quota-reached",
        })
        result = self.client.get_latest_rates("USD")
        assert "error" in result
        assert "quota" in result["error"].lower()


# ---------------------------------------------------------------------------
# Tests for register_tools MCP functions
# ---------------------------------------------------------------------------

class TestRegisterTools:
    """Tests for the MCP tool functions registered via register_tools."""

    def setup_method(self):
        """Register tools using a mock MCP and collect tool functions."""
        self.mcp = MagicMock()
        self.tools = {}

        def tool_decorator():
            def decorator(func):
                self.tools[func.__name__] = func
                return func
            return decorator

        self.mcp.tool = tool_decorator
        register_tools(self.mcp, credentials=None)

    # --- No credentials ---

    def test_get_rates_no_credentials(self):
        result = self.tools["currency_exchange_get_rates"](base_currency="USD")
        assert "error" in result
        assert "credentials" in result["error"]

    def test_convert_no_credentials(self):
        result = self.tools["currency_exchange_convert"](
            from_currency="USD", to_currency="INR", amount=100
        )
        assert "error" in result
        assert "credentials" in result["error"]

    def test_list_currencies_no_credentials(self):
        result = self.tools["currency_exchange_list_currencies"]()
        assert "error" in result
        assert "credentials" in result["error"]

    # --- Invalid input ---

    @patch.dict("os.environ", {"EXCHANGERATE_API_KEY": "test_key"})
    def test_convert_zero_amount(self):
        result = self.tools["currency_exchange_convert"](
            from_currency="USD", to_currency="INR", amount=0
        )
        assert "error" in result
        assert "greater than 0" in result["error"]

    @patch.dict("os.environ", {"EXCHANGERATE_API_KEY": "test_key"})
    def test_convert_negative_amount(self):
        result = self.tools["currency_exchange_convert"](
            from_currency="USD", to_currency="INR", amount=-50
        )
        assert "error" in result
        assert "greater than 0" in result["error"]

    # --- Success cases ---

    @patch.dict("os.environ", {"EXCHANGERATE_API_KEY": "test_key"})
    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_rates_success(self, mock_get):
        mock_get.return_value = _mock_response(json_data={
            "result": "success",
            "base_code": "USD",
            "time_last_update_unix": 1700000000,
            "conversion_rates": {"EUR": 0.92, "INR": 83.5},
        })
        result = self.tools["currency_exchange_get_rates"](base_currency="USD")
        assert result["success"] is True
        assert result["base_currency"] == "USD"
        assert "EUR" in result["rates"]

    @patch.dict("os.environ", {"EXCHANGERATE_API_KEY": "test_key"})
    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_convert_success(self, mock_get):
        mock_get.return_value = _mock_response(json_data={
            "result": "success",
            "base_code": "USD",
            "target_code": "INR",
            "conversion_rate": 83.5,
            "conversion_result": 8350.0,
            "time_last_update_unix": 1700000000,
        })
        result = self.tools["currency_exchange_convert"](
            from_currency="USD", to_currency="INR", amount=100
        )
        assert result["success"] is True
        assert result["converted_amount"] == 8350.0
        assert result["exchange_rate"] == 83.5

    @patch.dict("os.environ", {"EXCHANGERATE_API_KEY": "test_key"})
    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_list_currencies_success(self, mock_get):
        mock_get.return_value = _mock_response(json_data={
            "result": "success",
            "supported_codes": [
                ["USD", "US Dollar"],
                ["EUR", "Euro"],
                ["INR", "Indian Rupee"],
            ],
        })
        result = self.tools["currency_exchange_list_currencies"]()
        assert result["success"] is True
        assert result["count"] == 3
        assert result["currencies"][0]["code"] == "USD"

    # --- Network errors ---

    @patch.dict("os.environ", {"EXCHANGERATE_API_KEY": "test_key"})
    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_get_rates_timeout(self, mock_get):
        import httpx
        mock_get.side_effect = httpx.TimeoutException("timed out")
        result = self.tools["currency_exchange_get_rates"](base_currency="USD")
        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch.dict("os.environ", {"EXCHANGERATE_API_KEY": "test_key"})
    @patch("aden_tools.tools.currency_exchange_tool.currency_exchange_tool.httpx.get")
    def test_convert_network_error(self, mock_get):
        import httpx
        mock_get.side_effect = httpx.RequestError("connection failed")
        result = self.tools["currency_exchange_convert"](
            from_currency="USD", to_currency="INR", amount=100
        )
        assert "error" in result
        assert "Network error" in result["error"]
