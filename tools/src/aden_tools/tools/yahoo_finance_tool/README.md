# Yahoo Finance Tool

Latest available stock quotes, historical prices, financial statements, and company info via the `yfinance` library.

> **Note:** Data is sourced from Yahoo Finance and may be delayed by 15 minutes or more depending on the exchange.

## Tools

| Tool | Description |
|------|-------------|
| `yahoo_finance_quote` | Get current stock quote and key statistics |
| `yahoo_finance_history` | Get historical OHLCV price data |
| `yahoo_finance_financials` | Get income statement, balance sheet, or cash flow |
| `yahoo_finance_info` | Get detailed company information |
| `yahoo_finance_search` | Search for ticker symbols by company name or keyword |

## Setup

No API key or credentials required. The tool uses the `yfinance` Python library which accesses Yahoo Finance data directly.

> Data is provided by Yahoo Finance and is subject to their terms of use.

## Usage Examples

### Get a stock quote

```python
yahoo_finance_quote(symbol="AAPL")
```

### Get historical daily prices for the last month

```python
yahoo_finance_history(
    symbol="MSFT",
    period="1mo",
    interval="1d",
)
```

### Get intraday prices (last 5 days, hourly)

```python
yahoo_finance_history(
    symbol="GOOGL",
    period="5d",
    interval="1h",
)
```

### Get the income statement

```python
yahoo_finance_financials(symbol="AAPL", statement="income")
```

### Get the balance sheet

```python
yahoo_finance_financials(symbol="TSLA", statement="balance")
```

### Get the cash flow statement

```python
yahoo_finance_financials(symbol="NVDA", statement="cashflow")
```

### Get company info

```python
yahoo_finance_info(symbol="AMZN")
```

### Search for a ticker symbol

```python
yahoo_finance_search(query="Tesla")
```

## Period Values

| Period | Meaning |
|--------|---------|
| `1d` | 1 day |
| `5d` | 5 days |
| `1mo` | 1 month |
| `3mo` | 3 months |
| `6mo` | 6 months |
| `1y` | 1 year |
| `2y` | 2 years |
| `5y` | 5 years |
| `ytd` | Year to date |
| `max` | All available history |

## Interval Values

| Interval | Meaning |
|----------|---------|
| `1m` | 1 minute (last 7 days only) |
| `5m` | 5 minutes |
| `1h` | 1 hour |
| `1d` | Daily |
| `1wk` | Weekly |
| `1mo` | Monthly |

> **Interval constraints:** Intraday intervals have range limits enforced by yfinance. `1m` is limited to the last 7 days. `5m`, `15m`, `30m`, and `1h` are limited to the last 60 days. Invalid combinations return an empty result silently rather than raising an error.

## Error Handling

All tools return error dicts on failure:

```python
{"error": "symbol is required"}
{"error": "No data found for symbol 'XYZ'"}
{"error": "Invalid statement type: xyz. Use: income, balance, cashflow"}
{"error": "Failed to fetch quote for AAPL: ..."}
```
