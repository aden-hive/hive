# Gmail Tool

Read, modify, and manage Gmail messages using the Gmail API v1.

## Tools

| Tool | Description |
|------|-------------|
| `gmail_list_messages` | List messages matching a Gmail search query |
| `gmail_get_message` | Get message details (headers, snippet, body) |
| `gmail_trash_message` | Move a message to trash |
| `gmail_modify_message` | Add/remove labels on a single message |
| `gmail_batch_modify_messages` | Add/remove labels on multiple messages |
| `gmail_create_draft` | Create a new draft (or threaded reply) |
| `gmail_get_signature` | Read the user's Gmail signature from settings |

## Setup

Requires Google OAuth2 via Aden:

1. Connect your Google account at [hive.adenhq.com](https://hive.adenhq.com)
2. The `GOOGLE_ACCESS_TOKEN` is managed automatically by the Aden credential system

Required OAuth scopes (configured in Aden):
- `gmail.readonly` — list and read messages
- `gmail.modify` — trash, star, and modify labels
- `gmail.compose` — create drafts
- `gmail.settings.basic` — read signatures via `gmail_get_signature` (optional; without it, pass `signature=` directly to `gmail_create_draft`)

## Usage Examples

### List unread emails
```python
gmail_list_messages(query="is:unread label:INBOX", max_results=10)
```

### Read a specific message
```python
gmail_get_message(message_id="18abc123", format="metadata")
```

### Trash a message
```python
gmail_trash_message(message_id="18abc123")
```

### Star a message
```python
gmail_modify_message(message_id="18abc123", add_labels=["STARRED"])
```

### Mark multiple messages as read
```python
gmail_batch_modify_messages(
    message_ids=["18abc123", "18abc456"],
    remove_labels=["UNREAD"],
)
```

### Create a draft with the user's signature
Gmail does **not** auto-append signatures to drafts created via the API, so the
caller must pass it in. If the token has `gmail.settings.basic`, fetch the
configured signature once; otherwise supply your own string.

```python
sig = gmail_get_signature()  # {"signature": "<div>— Tim</div>", ...}
gmail_create_draft(
    html="<p>Hi there,</p>",
    to="a@b.com",
    subject="Quick note",
    signature=sig["signature"],
)
```

For replies, the signature is placed between the reply body and the quoted
original message:

```python
gmail_create_draft(
    html="<p>Thanks!</p>",
    reply_to_message_id="18abc123",
    signature=sig["signature"],
)
```

## Common Label IDs

| Label | Description |
|-------|-------------|
| `STARRED` | Starred/flagged |
| `UNREAD` | Unread |
| `IMPORTANT` | Marked important |
| `SPAM` | Spam |
| `TRASH` | Trash |
| `INBOX` | Inbox |
| `CATEGORY_PERSONAL` | Primary tab |
| `CATEGORY_SOCIAL` | Social tab |
| `CATEGORY_PROMOTIONS` | Promotions tab |

## Error Handling

All tools return error dicts on failure:
```python
{"error": "Gmail token expired or invalid", "help": "Re-authorize via hive.adenhq.com"}
{"error": "Message not found"}
{"error": "Gmail credentials not configured", "help": "Connect Gmail via hive.adenhq.com"}
```
