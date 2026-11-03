# Atomic Mail Tool

Give an agent its own email inbox with [Atomic Mail](https://docs.atomicmail.ai).
The agent gets an `@atomicmail.ai` address it controls. It can send outreach,
receive verification codes, read replies and answer in-thread, without borrowing
a human's Gmail or Outlook account or setting up a domain.

The inbox API is [JMAP](https://jmap.io) (RFC 8620/8621). Atomic Mail is in open
alpha and free.

## Setup

### 1. Register an agent inbox
Follow the quickstart at [docs.atomicmail.ai](https://docs.atomicmail.ai).
Registration needs no domain, card or email confirmation: it uses a
proof-of-work step instead. It returns an API key for the new inbox.

### 2. Set the API key
```bash
export ATOMIC_MAIL_API_KEY=your_api_key_here
```

Or store it in the credential store under `atomicmail`.

### Optional overrides
| Variable | Purpose | Default |
|---|---|---|
| `ATOMIC_MAIL_AUTH_URL` | Auth service base URL | `https://auth.atomicmail.ai` |
| `ATOMIC_MAIL_API_URL` | JMAP API base URL | `https://api.atomicmail.ai` |
| `ATOMIC_MAIL_INBOX_DOMAIN` | Domain used to build the address (custom domains) | `atomicmail.ai` |
| `ATOMIC_MAIL_SCRYPT_SALT` | Proof-of-work scrypt salt | Atomic Mail's published default |

---

## Tools (7 total)

| Tool | Purpose |
|---|---|
| `atomicmail_get_address` | Return the agent's own email address |
| `atomicmail_send` | Send an email (plain text, optional HTML, CC) |
| `atomicmail_list_emails` | List recent emails in a mailbox (`inbox`, `sent`, …), optionally unread only |
| `atomicmail_read_email` | Read one email: headers, text body, attachment list |
| `atomicmail_search` | Full-text search across the inbox |
| `atomicmail_reply` | Reply in-thread (sets `In-Reply-To`/`References`, `Re:` subject) |
| `atomicmail_mark_read` | Mark emails read or unread |

---

## Usage Examples

### Sign up for a service and read the confirmation
```python
atomicmail_get_address()
# {"success": True, "address": "my-agent@atomicmail.ai"}

atomicmail_search(query="verification code", limit=5)
atomicmail_read_email(email_id="M1a2b3c")
atomicmail_mark_read(email_ids="M1a2b3c")
```

### Send and follow up
```python
atomicmail_send(
    to="founder@example.com",
    subject="Quick question about your API",
    body="Hi, I'm researching ...",
)

atomicmail_list_emails(unread_only=True)
atomicmail_reply(email_id="M9z8y7x", body="Thanks, that answers it.")
```

---

## How authentication works

The API key is not sent with each request. On first use, the tool:

1. Requests a challenge from the auth service and solves a scrypt proof-of-work.
   This takes a moment of CPU time.
2. Exchanges the key for a session token (about 1 hour).
3. Mints a capability token (about 2 minutes) that authorizes JMAP calls.

Tokens are cached per API key and refreshed before they expire, so the
proof-of-work runs about once an hour rather than on every call.

## Error Handling

Every tool returns a dict. On failure it contains an `error` key, plus `help`
when credentials are missing or the auth service suggests a fix:

```python
{"error": "Atomic Mail credentials not configured", "help": "Set the ATOMIC_MAIL_API_KEY ..."}
{"error": "Atomic Mail session failed: Invalid Atomic Mail API key (...)"}
{"error": "Email 'M123' not found"}
```

## Reference
- [Atomic Mail docs](https://docs.atomicmail.ai)
- [Atomic Mail Agentic on GitHub](https://github.com/Atomic-Mail/atomic-mail-agentic)
- [RFC 8621: JMAP for Mail](https://www.rfc-editor.org/rfc/rfc8621)
