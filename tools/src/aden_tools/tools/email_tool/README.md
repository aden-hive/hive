# Email Tool

Send emails using multiple providers. Currently supports Resend.

## Tools

### `send_email`
Send a general-purpose email.

**Parameters:**
- `to` (str | list[str]) - Recipient email address(es)
- `subject` (str) - Email subject line
- `html` (str) - Email body as HTML
- `from_email` (str, optional) - Sender address. Falls back to `EMAIL_FROM` env var
- `provider` ("auto" | "resend", optional) - Provider to use (default: "auto")

### `send_budget_alert_email`
Send a formatted budget alert notification.

**Parameters:**
- `to` (str | list[str]) - Recipient email address(es)
- `budget_name` (str) - Name of the budget
- `current_spend` (float) - Current spending amount
- `budget_limit` (float) - Budget limit amount
- `currency` (str, optional) - Currency code (default: "USD")
- `from_email` (str, optional) - Sender address. Falls back to `EMAIL_FROM` env var
- `provider` ("auto" | "resend", optional) - Provider to use

## Setup

```bash
export RESEND_API_KEY=re_your_api_key_here
export EMAIL_FROM=notifications@yourdomain.com
```

- `RESEND_API_KEY` - Get an API key at: https://resend.com/api-keys
- `EMAIL_FROM` - Default sender address. Must be from a domain verified in your email provider

## Adding a New Provider

1. Add a `_send_via_<provider>` function in `email_tool.py`
2. Add the provider's credential to `credentials/email.py`
3. Extend the `provider` Literal type and auto-detection logic
4. Add tests for the new provider
