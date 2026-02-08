# PR Description: HubSpot Webhooks Integration

## 🎯 Objective
This PR implements high-performance, real-time HubSpot CRM integration for Hive agents. By transitioning from polling to a webhook-driven architecture, it reduces latency from minutes to seconds and minimizes API rate-limit consumption.

---

## ✨ Key Changes

### 🔐 1. Credential Security & Lifecycle
- **New CRM Spec**: Introduced `HUBSPOT_ACCESS_TOKEN` and `HUBSPOT_WEBHOOK_SIGNING_SECRET` into the `CredentialManager`.
- **Bipartisan Model**: Decoupled raw credential storage from tool-specific injection logic in `tools/src/aden_tools/credentials/crm.py`.

### ⚙️ 2. HubSpot CRM Toolkit
- **`hubspot_health_check`**: Automated API connectivity validation.
- **`hubspot_webhook_verify`**: Industrial-grade security implementation using HubSpot's V3 signature verification (HMAC-SHA256), protecting Hive endpoints from spoofing attacks.
- **`Subscription Management`**: New tools to programmatically register and list webhook events (`contact.creation`, `deal.propertyChange`, etc.).

### 🚀 3. Event-Driven Runtime
- **EventBus Expansion**: Added `WEBHOOK_RECEIVED` to the core `EventBus`, enabling Hive agents to observe and react to external triggers without polling.
- **Standardized Payloads**: Unified webhook batch processing into high-level agent events.

### 📚 4. reference & Docs
- **Integration Guide**: Added `docs/HUBSPOT_WEBHOOKS.md` with configuration tutorials and security implementation details.
- **Reference Agent**: Provided `exports/hubspot_engagement_agent` as a blueprint for automated Sales/CS workflows triggered by CRM changes.

---

## 🧪 Testing Details
- **Test Suite**: Created 9 comprehensive tests in `tools/tests/tools/test_hubspot_tool.py` and `tools/tests/test_crm_credentials.py`.
- **Security Validation**: Verified successful signature matching, rejection of tampered payloads, and replay protection (timestamp windows).
- **Execution Output**: All tests passed (9/9).

---

## 🏗️ Future Roadmap
- Extend to write-back operations (e.g., auto-updating deal stages).
- Implement OAuth2 token refresh via the Aden Provider.
