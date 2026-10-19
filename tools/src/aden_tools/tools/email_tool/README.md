# Email Tool

Send emails using multiple providers. Supports Gmail (via Google OAuth2) and Resend.

The `provider` parameter is required — you must explicitly choose `"gmail"` or `"resend"`.

## Tools

### `send_email`
Send a general-purpose email.

**Parameters:**
- `to` (str | list[str]) - Recipient email address(es)
- `subject` (str) - Email subject line (1-998 chars per RFC 2822)
- `html` (str) - Email body as HTML
- `provider` ("gmail" | "resend") - Provider to use. Required.
- `from_email` (str, optional) - Sender address. Falls back to `EMAIL_FROM` env var. Optional for Gmail (defaults to the authenticated user's address)
- `cc` (str | list[str], optional) - CC recipient(s)
- `bcc` (str | list[str], optional) - BCC recipient(s)

## Setup

### Gmail (via Aden OAuth2)

Connect Gmail through hive.adenhq.com. The `GOOGLE_ACCESS_TOKEN` is provided automatically at runtime via the `CredentialStoreAdapter`.

### Resend

```bash
export RESEND_API_KEY=re_your_api_key_here
export EMAIL_FROM=notifications@yourdomain.com
```

- `RESEND_API_KEY` - Get an API key at: https://resend.com/api-keys
- `EMAIL_FROM` - Default sender address. Must be from a domain verified in your email provider. Required for Resend, optional for Gmail.

### Testing override

Set `EMAIL_OVERRIDE_TO` to redirect all outbound mail to a single address. The original recipients are prepended to the subject line for traceability.

```bash
export EMAIL_OVERRIDE_TO=you@example.com
```

## Adding a New Provider

1. Add a `_send_via_<provider>` function in `email_tool.py`
2. Add the provider's credential key to `_get_credential()`
3. Extend the `provider` Literal type in `_send_email_impl()`
4. Add tests for the new provider
