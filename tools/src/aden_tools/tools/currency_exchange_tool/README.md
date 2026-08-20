# Currency Exchange Tool

Frankfurter-powered currency exchange tools for live and historical foreign exchange rates.

## Overview

This tool provides lightweight FX access backed by the Frankfurter API, which publishes exchange rate data sourced from the European Central Bank.

It is designed for simple agent workflows that need to:

- Fetch the latest exchange rates for a base currency
- Convert an amount between two currencies
- Retrieve historical daily rates for a specific date

## Authentication

No credentials are required.

- API provider: Frankfurter
- Auth: none
- Base URL: `https://api.frankfurter.dev/v1`

## Available Tools

### `currency_get_latest`

Fetch the latest available rates for a base currency.

**Arguments:**

- `base` (str, default: `"USD"`) - 3-letter ISO currency code

**Returns:**

```python
{
    "base": "USD",
    "date": "2026-03-10",
    "rates": {"EUR": 0.85903, "GBP": 0.72611},
    "count": 2,
}
```

### `currency_convert`

Convert an amount from one currency to another using the latest available rate.

**Arguments:**

- `amount` (float, required) - amount to convert
- `from_currency` (str, required) - source 3-letter ISO currency code
- `to_currency` (str, required) - target 3-letter ISO currency code

**Returns:**

```python
{
    "from": "USD",
    "to": "EUR",
    "amount": 10,
    "converted": 8.5903,
    "rate": 0.85903,
    "date": "2026-03-10",
}
```

### `currency_get_historical`

Fetch rates for a specific historical date.

**Arguments:**

- `date` (str, required) - date in `YYYY-MM-DD` format
- `base` (str, default: `"USD"`) - 3-letter ISO currency code

**Returns:**

```python
{
    "base": "USD",
    "date": "2024-01-15",
    "rates": {"EUR": 0.9167},
    "count": 1,
}
```

## Error Behavior

The tool validates obvious input issues before making a request.

Examples:

- Empty currency code -> `{"error": "base is required"}`
- Invalid currency code shape -> `{"error": "base must be a 3-letter currency code"}`
- Invalid historical date -> `{"error": "date must use YYYY-MM-DD format"}`
- Unknown currency code -> `{"error": "Unknown currency code: BAD"}`

Network and API failures are returned as structured error messages rather than exceptions.

## Usage

### Register directly

```python
from fastmcp import FastMCP

from aden_tools.tools.currency_exchange_tool import register_tools

mcp = FastMCP("currency-server")
register_tools(mcp)
```

### Register through the shared tool loader

This tool is currently registered as an unverified tool, so it is included when `include_unverified=True`.

```python
from fastmcp import FastMCP

from aden_tools.tools import register_all_tools

mcp = FastMCP("currency-server")
register_all_tools(mcp, include_unverified=True)
```

### Example calls

```python
currency_get_latest(base="EUR")

currency_convert(amount=100, from_currency="USD", to_currency="JPY")

currency_get_historical(date="2024-01-15", base="GBP")
```

## Testing

The tests for this tool live in the shared tools suite:

```bash
uv run pytest tools/tests/tools/test_currency_exchange_tool.py -v
```

## API Reference

- [Frankfurter API](https://frankfurter.dev)
- [Hosted API endpoint](https://api.frankfurter.dev)