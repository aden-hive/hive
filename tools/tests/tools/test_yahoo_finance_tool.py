"""Tests for yahoo_finance_tool - Stock quotes, historical prices, and financial data."""

from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.yahoo_finance_tool.yahoo_finance_tool import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


def _mock_yf():
    """Create a mock yfinance module."""
    mock_mod = ModuleType("yfinance")
    mock_mod.Ticker = MagicMock
    mock_mod.Search = MagicMock
    return mock_mod


class TestYahooFinanceQuote:
    def test_empty_symbol(self, tool_fns):
        result = tool_fns["yahoo_finance_quote"](symbol="")
        assert "error" in result

    def test_successful_quote(self, tool_fns):
        mock_yf = _mock_yf()
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "shortName": "Apple Inc.",
            "regularMarketPrice": 175.50,
            "regularMarketPreviousClose": 174.00,
            "regularMarketOpen": 174.50,
            "regularMarketDayHigh": 176.00,
            "regularMarketDayLow": 174.00,
            "regularMarketVolume": 50000000,
            "marketCap": 2700000000000,
            "trailingPE": 28.5,
            "trailingEps": 6.16,
            "dividendYield": 0.005,
            "fiftyTwoWeekHigh": 200.00,
            "fiftyTwoWeekLow": 130.00,
            "currency": "USD",
            "exchange": "NMS",
        }
        mock_yf.Ticker = MagicMock(return_value=mock_ticker)

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = tool_fns["yahoo_finance_quote"](symbol="AAPL")

        assert result["symbol"] == "AAPL"
        assert result["price"] == 175.50
        assert result["name"] == "Apple Inc."


class TestYahooFinanceHistory:
    def test_empty_symbol(self, tool_fns):
        result = tool_fns["yahoo_finance_history"](symbol="")
        assert "error" in result

    def test_successful_history(self, tool_fns):
        mock_yf = _mock_yf()
        mock_ticker = MagicMock()

        # Create a mock DataFrame
        import pandas as pd

        mock_df = pd.DataFrame(
            {
                "Open": [174.0, 175.0],
                "High": [176.0, 177.0],
                "Low": [173.0, 174.5],
                "Close": [175.5, 176.5],
                "Volume": [50000000, 45000000],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        mock_ticker.history.return_value = mock_df
        mock_yf.Ticker = MagicMock(return_value=mock_ticker)

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = tool_fns["yahoo_finance_history"](symbol="AAPL", period="5d")

        assert result["symbol"] == "AAPL"
        assert len(result["data"]) == 2
        assert result["data"][0]["close"] == 175.5


class TestYahooFinanceInfo:
    def test_empty_symbol(self, tool_fns):
        result = tool_fns["yahoo_finance_info"](symbol="")
        assert "error" in result

    def test_successful_info(self, tool_fns):
        mock_yf = _mock_yf()
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "shortName": "Apple Inc.",
            "longName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "longBusinessSummary": "Apple designs and sells electronics.",
            "website": "https://apple.com",
            "fullTimeEmployees": 164000,
            "country": "United States",
            "city": "Cupertino",
            "address1": "One Apple Park Way",
        }
        mock_yf.Ticker = MagicMock(return_value=mock_ticker)

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = tool_fns["yahoo_finance_info"](symbol="AAPL")

        assert result["sector"] == "Technology"
        assert result["employees"] == 164000


class TestYahooFinanceSearch:
    def test_empty_query(self, tool_fns):
        result = tool_fns["yahoo_finance_search"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_yf = _mock_yf()
        mock_search = MagicMock()
        mock_search.quotes = [
            {"symbol": "AAPL", "shortname": "Apple Inc.", "exchange": "NMS", "quoteType": "EQUITY"},
        ]
        mock_yf.Search = MagicMock(return_value=mock_search)

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = tool_fns["yahoo_finance_search"](query="Apple")

        assert len(result["results"]) == 1
        assert result["results"][0]["symbol"] == "AAPL"
