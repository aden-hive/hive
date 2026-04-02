# Twilio Tool

SMS and WhatsApp messaging, call logs, and phone number management via the Twilio REST API.

## Tools

| Tool | Description |
|------|-------------|
| `twilio_send_sms` | Send an SMS message |
| `twilio_send_whatsapp` | Send a WhatsApp message |
| `twilio_list_messages` | List recent messages with optional filters |
| `twilio_get_message` | Get details of a specific message by SID |
| `twilio_delete_message` | Delete a message from your Twilio account |
| `twilio_list_phone_numbers` | List phone numbers owned by the account |
| `twilio_list_calls` | List recent calls with optional filters |

## Setup

Requires a Twilio Account SID and Auth Token:

1. Go to [console.twilio.com](https://console.twilio.com)
2. Copy your **Account SID** and **Auth Token** from the dashboard

```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your-auth-token
```

> Phone numbers must be in **E.164 format**: `+14155552671`

## Usage Examples

### Send an SMS

```python
twilio_send_sms(
    to="+14155552671",
    from_number="+18005550100",
    body="Your verification code is 123456",
)
```

### Send a WhatsApp message

```python
twilio_send_whatsapp(
    to="+14155552671",
    from_number="+14155550000",
    body="Hello from Twilio WhatsApp!",
)
```

### List recent messages

```python
twilio_list_messages(page_size=20)
```

### Filter messages by recipient

```python
twilio_list_messages(to="+14155552671", page_size=10)
```

### Get a specific message

```python
twilio_get_message(message_sid="SMxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
```

### Delete a message

```python
twilio_delete_message(message_sid="SMxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
```

### List phone numbers on the account

```python
twilio_list_phone_numbers()
```

### List recent calls

```python
twilio_list_calls(status="completed", page_size=20)
```

## Call Status Values

| Status | Meaning |
|--------|---------|
| `queued` | Call is queued |
| `ringing` | Recipient's phone is ringing |
| `in-progress` | Call is active |
| `completed` | Call ended successfully |
| `busy` | Recipient was busy |
| `failed` | Call failed |
| `no-answer` | No answer |
| `canceled` | Call was canceled |

## Error Handling

All tools return error dicts on failure:

```python
{"error": "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN not set", "help": "Get credentials from https://console.twilio.com/"}
{"error": "Unauthorized. Check your Twilio credentials."}
{"error": "Rate limited. Try again shortly."}
{"error": "Message not found."}
```
