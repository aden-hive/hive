# Email Tool

Multi-provider email support with automatic provider detection.

## Providers

| Provider | Send | Read | Setup |
|----------|------|------|-------|
| Gmail    | Yes  | Yes  | Connect via hive.adenhq.com (OAuth2) |
| Outlook  | Yes  | Yes  | Connect via hive.adenhq.com (OAuth2) |
| Resend   | Yes  | No   | Set `RESEND_API_KEY` env var |

Auto-detection order for send: Gmail > Outlook > Resend.
Auto-detection order for read: Gmail > Outlook.

## Tools

### Send
- `send_email` - Send an email (auto-detects provider or specify one)
- `gmail_reply_email` - Reply to a Gmail message in-thread with threading headers

### Read
- `email_list` - List messages in a folder (INBOX, SENT, DRAFTS, TRASH, SPAM)
- `email_read` - Read a full message by ID
- `email_search` - Search messages (Gmail search syntax or Outlook full-text)
- `email_labels` - List available labels/folders

### Write Operations
- `email_mark_read` - Mark a message as read or unread
- `email_delete` - Delete or trash a message
- `email_reply` - Reply to a message (supports reply-all)
- `email_forward` - Forward a message
- `email_move` - Move a message to a different folder
- `email_bulk_delete` - Bulk delete or trash multiple messages

## Setup

### Gmail / Outlook (via Aden OAuth2)

Connect through hive.adenhq.com. Tokens are provided automatically at runtime via `CredentialStoreAdapter`.

### Resend

```bash
export RESEND_API_KEY=re_your_api_key_here
export EMAIL_FROM=notifications@yourdomain.com
```

- `RESEND_API_KEY` - Get an API key at: https://resend.com/api-keys
- `EMAIL_FROM` - Default sender address. Must be from a verified domain. Required for Resend, optional for Gmail/Outlook.

### Testing override

Set `EMAIL_OVERRIDE_TO` to redirect all outbound mail to a single address. Original recipients are prepended to the subject for traceability.

```bash
export EMAIL_OVERRIDE_TO=you@example.com
```

## Adding a New Provider

1. Add a `_send_via_<provider>` function in `email_tool.py`
2. Add the provider's credential key to `_get_credentials()`
3. Extend the `provider` Literal type in `_send_email_impl()`
4. Add tests for the new provider
