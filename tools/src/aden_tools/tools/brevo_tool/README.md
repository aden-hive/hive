# Brevo Tool

Interact with [Brevo](https://www.brevo.com) (formerly Sendinblue) to send 
transactional emails, SMS messages, and manage contacts via the 
[Brevo API](https://developers.brevo.com/reference).

## Setup

### 1. Create a Brevo Account
Sign up for free at [brevo.com](https://www.brevo.com). The free tier includes
300 emails/day and basic contact management.

### 2. Get Your API Key
1. Log in to your Brevo account
2. Go to **Settings → API Keys**
3. Click **Generate a new API key**
4. Copy the key

### 3. Set Environment Variable
```bash
export BREVO_API_KEY=your_api_key_here
```

### 4. Verify Your Sender Email
Before sending emails, verify your sender address in Brevo under
**Senders & IP → Senders**.

---

## Tools (6 Total)

### Email (2)
| Tool | Purpose |
|---|---|
| `brevo_send_email` | Send a transactional email with HTML content |
| `brevo_get_email_stats` | Get delivery status and events for a sent email |

### SMS (1)
| Tool | Purpose |
|---|---|
| `brevo_send_sms` | Send a transactional SMS to a phone number |

### Contacts (3)
| Tool | Purpose |
|---|---|
| `brevo_create_contact` | Create a new contact in your Brevo account |
| `brevo_get_contact` | Retrieve contact details by email address |
| `brevo_update_contact` | Update an existing contact's attributes |

---

## Usage Examples

### Send a Transactional Email
```python
brevo_send_email(
    to_email="user@example.com",
    to_name="John Doe",
    subject="Your report is ready",
    html_content="<h1>Hello John!</h1><p>Your report has been generated.</p>",
    from_email="agent@yourcompany.com",
    from_name="Hive Agent",
    text_content="Hello John! Your report has been generated."  # optional
)
# Returns: {"success": True, "message_id": "<abc123@smtp-relay.brevo.com>"}
```

### Send an SMS
```python
brevo_send_sms(
    to="+919876543210",       # international format required
    content="Your OTP is 4821. Valid for 10 minutes.",
    sender="HiveAgent"        # max 11 alphanumeric characters
)
# Returns: {"success": True, "reference": "...", "remaining_credits": 95.0}
```

### Create a Contact
```python
brevo_create_contact(
    email="lead@example.com",
    first_name="Jane",
    last_name="Smith",
    phone="+14155552671",
    list_ids="2,5"            # comma-separated list IDs
)
# Returns: {"success": True, "id": 42, "email": "lead@example.com"}
```

### Get a Contact
```python
brevo_get_contact(email="lead@example.com")
# Returns:
# {
#   "success": True,
#   "id": 42,
#   "email": "lead@example.com",
#   "first_name": "Jane",
#   "last_name": "Smith",
#   "list_ids": [2, 5],
#   "email_blacklisted": False,
#   "created_at": "2024-01-15T10:30:00Z"
# }
```

### Update a Contact
```python
brevo_update_contact(
    email="lead@example.com",
    first_name="Jane",
    last_name="Johnson",      # updated last name
    list_ids="2,5,8"          # added to list 8
)
# Returns: {"success": True, "email": "lead@example.com"}
```

### Check Email Delivery Status
```python
brevo_get_email_stats(message_id="<abc123@smtp-relay.brevo.com>")
# Returns:
# {
#   "success": True,
#   "message_id": "<abc123@smtp-relay.brevo.com>",
#   "email": "user@example.com",
#   "subject": "Your report is ready",
#   "events": [{"name": "delivered", "time": "..."}]
# }
```

---

## Use Cases for AI Agents

- **Task Completion Alerts:** Agent sends email when a long-running job finishes
- **Human-in-the-Loop:** Agent sends SMS requesting approval before a sensitive action
- **Lead Management:** Agent creates/updates contacts after qualifying leads from Slack or HubSpot
- **Error Notifications:** Agent sends SMS alert when a critical workflow fails
- **Verification:** Agent sends OTP via SMS for user identity verification

---

## Error Handling

All tools return `{"error": "message"}` on failure. Always check for the 
`error` key before using results.

Common errors:

| Error | Cause | Fix |
|---|---|---|
| `Invalid Brevo API key` | Wrong or expired key | Regenerate key in Brevo settings |
| `Access forbidden` | Insufficient permissions | Check API key permissions |
| `Resource not found` | Contact/email doesn't exist | Verify the email or message ID |
| `Rate limit exceeded` | Too many requests | Wait and retry |
| `Phone number must start with '+'` | Wrong phone format | Use international format e.g. `+14155552671` |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BREVO_API_KEY` | Yes | API key from Brevo Settings → API Keys |

---

## API Reference

- [Brevo API Docs](https://developers.brevo.com/reference)
- [Transactional Email](https://developers.brevo.com/reference/sendtransacemail)
- [Transactional SMS](https://developers.brevo.com/reference/sendtransacsms)
- [Contacts API](https://developers.brevo.com/reference/createcontact)