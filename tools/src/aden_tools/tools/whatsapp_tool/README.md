# WhatsApp Cloud API Tool

Send messages, templates, images, and documents via the Meta WhatsApp Business Cloud API.

## Setup

```bash
# Required
export WHATSAPP_ACCESS_TOKEN=your-access-token
export WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id
```

**Get your credentials:**

1. Go to [Meta for Developers](https://developers.facebook.com/)
2. Create or select a Meta App with WhatsApp product enabled
3. Navigate to **WhatsApp > API Setup**
4. Copy the **Temporary access token** (or generate a permanent System User token)
5. Copy the **Phone number ID** from the same page
6. Set `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID` environment variables

Alternatively, configure via the Hive credential store (`CredentialStoreAdapter`).

> **Important:** Enable `whatsapp_business_messaging` and `whatsapp_business_management` permissions for your app before generating the access token.

## Tools (7)

### Messaging (2)

| Tool | Description |
|------|-------------|
| `whatsapp_send_message` | Send a text message (requires 24h conversation window) |
| `whatsapp_send_template` | Send a pre-approved template message (can initiate conversations) |

### Templates (1)

| Tool | Description |
|------|-------------|
| `whatsapp_list_templates` | List approved message templates for a WhatsApp Business Account |

### Media (2)

| Tool | Description |
|------|-------------|
| `whatsapp_send_image` | Send an image message (JPEG/PNG, max 5MB) |
| `whatsapp_send_document` | Send a document (PDF, etc., max 100MB) |

### Engagement (2)

| Tool | Description |
|------|-------------|
| `whatsapp_mark_as_read` | Mark a message as read (blue ticks) |
| `whatsapp_send_reaction` | React to a message with an emoji |

## Usage

### Send a Text Message

```python
whatsapp_send_message(
    to="+14155552671",
    body="Hello from Hive!",
)
# Returns: {"success": True, "message_id": "wamid.xxx", "to": "+14155552671"}
```

### Initiate a Conversation with a Template

```python
whatsapp_send_template(
    to="+14155552671",
    template_name="hello_world",
    language="en",
)
# Returns: {"success": True, "message_id": "wamid.xxx", "template": "hello_world"}
```

### Send a Template with Parameters

```python
whatsapp_send_template(
    to="+14155552671",
    template_name="order_update",
    language="en",
    components='[{"type":"body","parameters":[{"type":"text","text":"ORD-12345"}]}]',
)
```

### List Available Templates

```python
whatsapp_list_templates(
    waba_id="123456789012345",
    limit=10,
)
# Returns: {"success": True, "templates": [...], "count": 5}
```

### Send an Image

```python
whatsapp_send_image(
    to="+14155552671",
    image_url="https://example.com/photo.jpg",
    caption="Check this out!",
)
```

### Send a Document

```python
whatsapp_send_document(
    to="+14155552671",
    document_url="https://example.com/report.pdf",
    filename="Q1_Report.pdf",
    caption="Quarterly report attached",
)
```

### React to a Message

```python
whatsapp_send_reaction(
    to="+14155552671",
    message_id="wamid.xxx",
    emoji="\U0001f44d",
)
```

### Mark as Read

```python
whatsapp_mark_as_read(message_id="wamid.xxx")
# Returns: {"success": True}
```

## API Reference

### whatsapp_send_message

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| to | str | Yes | Recipient phone number in E.164 format |
| body | str | Yes | Message text (max 4096 characters) |

### whatsapp_send_template

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| to | str | Yes | Recipient phone number in E.164 format |
| template_name | str | Yes | Name of the approved template |
| language | str | No | Language code (default `en`) |
| components | str | No | JSON string of template components for personalization |

### whatsapp_list_templates

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| waba_id | str | Yes | WhatsApp Business Account ID |
| limit | int | No | Max templates to return, 1-100 (default 20) |

### whatsapp_send_image

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| to | str | Yes | Recipient phone number in E.164 format |
| image_url | str | Yes | Public URL of the image (JPEG/PNG, max 5MB) |
| caption | str | No | Caption for the image |

### whatsapp_send_document

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| to | str | Yes | Recipient phone number in E.164 format |
| document_url | str | Yes | Public URL of the document (max 100MB) |
| filename | str | No | Display filename (e.g., `report.pdf`) |
| caption | str | No | Caption for the document |

### whatsapp_mark_as_read

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| message_id | str | Yes | WhatsApp message ID to mark as read |

### whatsapp_send_reaction

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| to | str | Yes | Recipient phone number in E.164 format |
| message_id | str | Yes | WhatsApp message ID to react to |
| emoji | str | Yes | Emoji character to react with |

## Scope

- Send free-form text messages within the 24-hour conversation window
- Initiate conversations with pre-approved template messages
- Send images (JPEG, PNG) and documents (PDF, etc.) with optional captions
- Mark incoming messages as read (blue ticks)
- React to messages with emoji
- Discover available templates for a WhatsApp Business Account

## Rate Limits

| Tier | Limit |
|------|-------|
| Free (test) | 1,000 service conversations/month, limited recipients |
| Standard | Per-conversation pricing, varies by country |

> WhatsApp pricing is per-conversation (24h window), not per-message. See [WhatsApp Pricing](https://developers.facebook.com/docs/whatsapp/pricing) for details.

## Error Handling

The tools return error dictionaries on failure:

```python
{"error": "WhatsApp credentials not configured"}
{"error": "Invalid or expired WhatsApp access token"}
{"error": "Re-engagement message requires a template (24h window expired)"}
{"error": "Recipient phone number not on WhatsApp"}
{"error": "Rate limit exceeded. Try again later."}
```

## External Links

- [WhatsApp Cloud API Docs](https://developers.facebook.com/docs/whatsapp/cloud-api)
- [Message Templates](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates)
- [Media Messages](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages#media-messages)
