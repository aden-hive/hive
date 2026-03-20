# Currency Exchange Rate Tool

Fetch real-time currency exchange rates and convert amounts between
currencies using the [ExchangeRate-API](https://exchangerate-api.com).

## Setup

1. Go to [exchangerate-api.com](https://exchangerate-api.com)
2. Click **Get Free Key**
3. Sign up — no credit card required
4. Copy your **API Key** from the dashboard

Free tier includes 1,500 requests/month.

## Authentication

Set the following environment variable:
```bash
export EXCHANGERATE_API_KEY=your_api_key_here
```

## Available Tools

### `currency_exchange_get_rates`
Get latest exchange rates for a base currency.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| base_currency | str | Yes | ISO 4217 code e.g. 'USD', 'EUR', 'INR' |

### `currency_exchange_convert`
Convert an amount from one currency to another.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| from_currency | str | Yes | Source currency code e.g. 'USD' |
| to_currency | str | Yes | Target currency code e.g. 'INR' |
| amount | float | Yes | Amount to convert (must be > 0) |

### `currency_exchange_list_currencies`
List all ~160 supported currency codes and names. No arguments needed.

## Example Usage
```python
# Get all rates relative to USD
currency_exchange_get_rates(base_currency="USD")
# {"base_currency": "USD", "rates": {"EUR": 0.92, "INR": 83.5, ...}}

# Convert 100 USD to INR
currency_exchange_convert(from_currency="USD", to_currency="INR", amount=100)
# {"converted_amount": 8350.0, "exchange_rate": 83.5, ...}

# List all supported currencies
currency_exchange_list_currencies()
# {"count": 161, "currencies": [{"code": "USD", "name": "US Dollar"}, ...]}
```

## Use Cases

- Convert invoice amounts to client's local currency
- Monitor exchange rate changes and alert via Slack or Pushover
- Generate multi-currency financial reports
- Validate currency codes before processing payments
