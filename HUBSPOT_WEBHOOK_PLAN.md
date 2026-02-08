# Work Plan: HubSpot Webhooks Integration ([Issue #4035](https://github.com/Samir-atra/hive_fork/issues/4035))

## Overview
Implement real-time event processing for HubSpot CRM events (Contacts, Deals, Companies) using Webhooks. This integration allows Hive agents to switch from polling-based syncs to event-driven architectures, significantly reducing latency and API overhead.

---

## 🛠 Phase 1: Foundation & Credentials
**Goal**: Securely store and validate HubSpot Webhook credentials.

1.  **Environment Configuration**:
    *   Add `HUBSPOT_WEBHOOK_SIGNING_SECRET` to `.env` for payload verification.
    *   Ensure `HUBSPOT_ACCESS_TOKEN` is configured (Private App or OAuth).
2.  **Credential Management**:
    *   Register the `hubspot` credential spec in the Hive `CredentialStore`.
    *   Define required keys: `access_token`, `webhook_signing_secret`.
3.  **Lightweight Health Check**:
    *   Implement a `hubspot_health_check` tool that calls `GET /crm/v3/objects/contacts?limit=1` to verify token validity.

## ⚙️ Phase 2: Core Tooling Implementation
**Goal**: Build the tools necessary for signature verification and event processing.

1.  **`hubspot_webhook_verify`**:
    *   Implement HubSpot V3 signature verification (SHA-256 HMAC).
    *   Input: `request_body`, `x-hubspot-signature-v3`, `x-hubspot-request-timestamp`.
2.  **`hubspot_webhook_receive`**:
    *   Parse the HubSpot webhook payload (standardized batch format).
    *   Transform low-level change logs into high-level agent events (e.g., `deal.stage_updated`).
3.  **Subscription Management**:
    *   **`hubspot_register_webhook_subscription`**: Programmatically subscribe the Hive callback URL to HubSpot events.
    *   **`hubspot_list_webhook_subscriptions`**: List active subscriptions for the connected app.

## 🚀 Phase 3: Event-Driven Infrastructure
**Goal**: Connect webhooks to the Hive execution engine.

1.  **Webhook Endpoint Implementation**:
    *   Create a dedicated FastAPI/Express route at `/api/webhooks/hubspot`.
    *   Security: Call `hubspot_webhook_verify` before processing.
    *   Dispatch: Publish a `WEBHOOK_RECEIVED` event to the Hive `EventBus`.
2.  **Event Bus Enhancement**:
    *   Add `EventType.EXTERNAL_EVENT` to `EventBus` to support triggers from outside the framework.
3.  **Trigger Logic**:
    *   Implement a global listener that maps external HubSpot events to specific agent entry points based on the event type.

## 📚 Phase 4: Agent & Documentation
**Goal**: Provide reference implementations and guides.

1.  **Documentation**:
    *   Create `docs/HUBSPOT_WEBHOOKS.md` with step-by-step HubSpot App configuration guide.
2.  **Reference Agent**:
    *   Create `exports/hubspot_engagement_agent`: An agent that triggers when a new deal is created and auto-drafts a "Discovery Call" summary.

---

## 📅 Timeline Estimate
*   **Infrastructure & Credentials**: 1 day
*   **Signature Verification & Tools**: 2 days
*   **Endpoint & Event Bus Integration**: 2 days
*   **Docs & Testing**: 1 day

## 📝 Notes
*   **Scope**: Initially limited to read-only triggers (Contacts, Deals, Companies).
*   **Safety**: Webhook verification is strictly enforced.
*   **Scalability**: Async event processing ensures the receiver endpoint remains responsive.
