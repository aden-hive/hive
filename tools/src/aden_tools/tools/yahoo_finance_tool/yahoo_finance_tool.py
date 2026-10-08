"""
Yahoo Finance Tool - Stock quotes, historical prices, and financial data.

Uses the yfinance Python library (no API key needed).
Supports:
- Real-time stock quotes and info
- Historical price data
- Financial statements
- Company info and news

Reference: https://github.com/ranaroussi/yfinance
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


def _get_ticker(symbol: str) -> Any:
    """Lazily import yfinance and create a Ticker object."""
    import yfinance as yf

    return yf.Ticker(symbol)


def register_tools(mcp: FastMCP) -> None:
    """Register Yahoo Finance tools with the MCP server (no credentials needed)."""

    @mcp.tool()
    def yahoo_finance_quote(symbol: str) -> dict[str, Any]:
        """
        Get current stock quote and key statistics.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL", "MSFT", "GOOGL")

        Returns:
            Dict with price, change, market cap, PE ratio, volume, and more
        """
        if not symbol:
            return {"error": "symbol is required"}

        try:
            ticker = _get_ticker(symbol)
            info = ticker.info
            if not info or not info.get("regularMarketPrice"):
                return {"error": f"No data found for symbol '{symbol}'"}

            return {
                "symbol": symbol.upper(),
                "name": info.get("shortName", ""),
                "price": info.get("regularMarketPrice"),
                "previous_close": info.get("regularMarketPreviousClose"),
                "open": info.get("regularMarketOpen"),
                "day_high": info.get("regularMarketDayHigh"),
                "day_low": info.get("regularMarketDayLow"),
                "volume": info.get("regularMarketVolume"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "eps": info.get("trailingEps"),
                "dividend_yield": info.get("dividendYield"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "currency": info.get("currency", ""),
                "exchange": info.get("exchange", ""),
            }
        except Exception as e:
            return {"error": f"Failed to fetch quote for {symbol}: {e!s}"}

    @mcp.tool()
    def yahoo_finance_history(
        symbol: str,
        period: str = "1mo",
        interval: str = "1d",
    ) -> dict[str, Any]:
        """
        Get historical price data for a stock.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
            period: Time period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
            interval: Data interval: 1m, 5m, 15m, 30m, 1h, 1d, 5d, 1wk, 1mo

        Returns:
            Dict with historical data points (date, open, high, low, close, volume)
        """
        if not symbol:
            return {"error": "symbol is required"}

        try:
            ticker = _get_ticker(symbol)
            hist = ticker.history(period=period, interval=interval)
            if hist.empty:
                return {"error": f"No historical data for '{symbol}' with period={period}"}

            data = []
            for idx, row in hist.iterrows():
                data.append(
                    {
                        "date": str(idx.date()) if hasattr(idx, "date") else str(idx),
                        "open": round(row.get("Open", 0), 2),
                        "high": round(row.get("High", 0), 2),
                        "low": round(row.get("Low", 0), 2),
                        "close": round(row.get("Close", 0), 2),
                        "volume": int(row.get("Volume", 0)),
                    }
                )
            return {"symbol": symbol.upper(), "period": period, "interval": interval, "data": data}
        except Exception as e:
            return {"error": f"Failed to fetch history for {symbol}: {e!s}"}

    @mcp.tool()
    def yahoo_finance_financials(
        symbol: str,
        statement: str = "income",
    ) -> dict[str, Any]:
        """
        Get financial statements for a company.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")
            statement: Statement type: income, balance, cashflow (default: income)

        Returns:
            Dict with financial statement data (most recent periods)
        """
        if not symbol:
            return {"error": "symbol is required"}

        try:
            ticker = _get_ticker(symbol)

            if statement == "income":
                df = ticker.income_stmt
            elif statement == "balance":
                df = ticker.balance_sheet
            elif statement == "cashflow":
                df = ticker.cashflow
            else:
                return {"error": f"Invalid statement type: {statement}. Use: income, balance, cashflow"}

            if df is None or df.empty:
                return {"error": f"No {statement} statement data for '{symbol}'"}

            # Convert to dict with date columns as keys
            result = {}
            for col in df.columns[:4]:  # Last 4 periods
                period_data = {}
                for idx, val in df[col].items():
                    if val is not None and str(val) != "nan":
                        period_data[str(idx)] = float(val) if isinstance(val, (int, float)) else str(val)
                result[str(col.date()) if hasattr(col, "date") else str(col)] = period_data

            return {"symbol": symbol.upper(), "statement": statement, "data": result}
        except Exception as e:
            return {"error": f"Failed to fetch financials for {symbol}: {e!s}"}

    @mcp.tool()
    def yahoo_finance_info(symbol: str) -> dict[str, Any]:
        """
        Get detailed company information.

        Args:
            symbol: Stock ticker symbol (e.g. "AAPL")

        Returns:
            Dict with company details: sector, industry, description, employees, website
        """
        if not symbol:
            return {"error": "symbol is required"}

        try:
            ticker = _get_ticker(symbol)
            info = ticker.info
            if not info or not info.get("shortName"):
                return {"error": f"No info found for symbol '{symbol}'"}

            desc = info.get("longBusinessSummary", "")
            if len(desc) > 1000:
                desc = desc[:1000] + "..."

            return {
                "symbol": symbol.upper(),
                "name": info.get("shortName", ""),
                "long_name": info.get("longName", ""),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "description": desc,
                "website": info.get("website", ""),
                "employees": info.get("fullTimeEmployees"),
                "country": info.get("country", ""),
                "city": info.get("city", ""),
                "address": info.get("address1", ""),
            }
        except Exception as e:
            return {"error": f"Failed to fetch info for {symbol}: {e!s}"}

    @mcp.tool()
    def yahoo_finance_search(query: str) -> dict[str, Any]:
        """
        Search for stock tickers by company name or keyword.

        Args:
            query: Search query (company name, keyword, or partial ticker)

        Returns:
            Dict with matching tickers (symbol, name, exchange, type)
        """
        if not query:
            return {"error": "query is required"}

        try:
            import yfinance as yf

            search = yf.Search(query)
            quotes = search.quotes if hasattr(search, "quotes") else []

            results = []
            for q in quotes[:20]:
                results.append(
                    {
                        "symbol": q.get("symbol", ""),
                        "name": q.get("shortname", q.get("longname", "")),
                        "exchange": q.get("exchange", ""),
                        "type": q.get("quoteType", ""),
                    }
                )
            return {"query": query, "results": results}
        except Exception as e:
            return {"error": f"Search failed: {e!s}"}
