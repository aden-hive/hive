# HubSpot Webhooks Integration Guide

This guide explains how to configure HubSpot webhooks to trigger Hive agents in real-time.

---

## 🔐 1. Authentication & Setup

### Environment Variables
Add the following to your `.env` file:
```bash
HUBSPOT_ACCESS_TOKEN=your_private_app_token
HUBSPOT_WEBHOOK_SIGNING_SECRET=your_signing_secret
```

### Required Scopes
Ensure your HubSpot Private App has the following scopes:
- `crm.objects.contacts.read`
- `crm.objects.deals.read`
- `crm.objects.companies.read`

---

## 🛠 2. Using Webhook Tools

Hive provides several tools to manage and verify HubSpot webhooks:

1.  **`hubspot_health_check`**: Run this to verify your API token is working.
2.  **`hubspot_webhook_verify`**: Use this within your webhook receiver to ensure requests truly come from HubSpot.
3.  **`hubspot_register_webhook_subscription`**: Programmatically subscribe to events (e.g., `deal.creation`).
4.  **`hubspot_list_webhook_subscriptions`**: Check active subscriptions.

---

## 🚀 3. Receiving Webhooks

To receive webhooks, you must expose an endpoint (e.g., via FastAPI) and dispatch the event to the Hive `EventBus`.

### Example Receiver (FastAPI)
```python
from fastapi import FastAPI, Request, Header, HTTPException
from core.framework.runtime import EventBus, AgentEvent, EventType
from aden_tools.tools.hubspot_tool import hubspot_webhook_verify

app = FastAPI()
event_bus = EventBus()

@app.post("/api/webhooks/hubspot")
async def hubspot_webhook(
    request: Request,
    x_hubspot_signature_v3: str = Header(...),
    x_hubspot_request_timestamp: str = Header(...)
):
    body = await request.body()
    body_str = body.decode("utf-8")
    
    # Verify Signature
    is_valid = await hubspot_webhook_verify(
        request_body=body_str,
        signature=x_hubspot_signature_v3,
        timestamp=x_hubspot_request_timestamp
    )
    
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Dispatch to Hive
    payload = await request.json()
    for event in payload:
        await event_bus.publish(AgentEvent(
            type=EventType.WEBHOOK_RECEIVED,
            stream_id="hubspot_integration",
            data={
                "source": "hubspot",
                "event_type": event.get("subscriptionType"),
                "object_id": event.get("objectId"),
                "portal_id": event.get("portalId")
            }
        ))
    
    return {"status": "received"}
```

---

## 🤖 4. Reference Agent Implementation

You can now create an agent that triggers on `WEBHOOK_RECEIVED`.

**Agent Config excerpt:**
```json
{
  "triggers": [
    {
      "type": "event_bus",
      "event_type": "webhook_received",
      "filter": { "event_type": "deal.creation" }
    }
  ]
}
```

---

## 🧪 5. Testing the Integration

You can run the suite of unit and integration tests to ensure your environment is configured correctly:

```bash
# Run all HubSpot specific tests
pytest tools/tests/tools/test_hubspot_tool.py tools/tests/test_crm_credentials.py
```

These tests cover:
- **Signature Verification**: Success, bad signature, and expired timestamp scenarios.
- **Credential Specs**: Verification of environment variable mappings.
- **Tool Logic**: Mocked API interactions for health checks and subscriptions.
