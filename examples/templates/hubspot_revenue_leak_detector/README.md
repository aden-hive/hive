# HubSpot Revenue Leak Detector

An autonomous HubSpot CRM monitor built on the Aden Hive framework.
Continuously scans the sales pipeline, detects revenue leak patterns,
sends structured alerts, and emails ghosted contacts via Resend — cycling until a
critical threshold triggers escalation and halt.

---

## What It Detects

| Pattern | Trigger | Business Risk |
|---|---|---|
| **GHOSTED** | Prospect silent 21+ days | Lost deal value |
| **STALLED** | Deal stuck in same stage 10-20 days | Slow pipeline velocity |

---

## Agent Graph

```
monitor ──► analyze ──► notify ──► followup
                                       │
           ◄───────────────────────────┘   (loop while halt != true)
```

- **monitor** — LLM calls `hubspot_search_deals` + `hubspot_search_contacts` (MCP) to fetch deals and contact emails, then calls `scan_pipeline` to store deals for analysis
- **analyze** — calls `detect_revenue_leaks` to classify GHOSTED/STALLED patterns and compute severity
- **notify** — calls `build_telegram_alert` to build the report, then `telegram_send_message` (MCP) to send the Telegram alert + prints console report
- **followup** — calls `prepare_followup_emails` to get email payloads, then `send_email` (MCP) to email GHOSTED contacts
- Loop halts when severity = **critical** or after **3 consecutive low-severity cycles**

---

## Required Setup

This agent requires **all three** credential types to function meaningfully:

### 1. HubSpot CRM (Required)

The LLM uses HubSpot MCP tools to fetch deal data directly.

1. Go to **HubSpot → Settings → Integrations → Private Apps**
2. Create a new Private App with the following scopes:
   - `crm.objects.deals.read`
   - `crm.objects.contacts.read`
3. Copy the access token and set the environment variable:

```bash
export HUBSPOT_ACCESS_TOKEN="pat-na2-..."
```

### 2. Resend Email (Required)

The LLM uses `send_email` MCP tool to send follow-up emails to GHOSTED contacts.

1. Visit [https://resend.com/api-keys](https://resend.com/api-keys)
2. Create an API key with **Full access**
3. Export the key:

```bash
export RESEND_API_KEY="re_xxx..."
```

> **Note:** You must also verify a sending domain in Resend → **Domains** before emails will deliver.

### 3. Telegram Alerts

The LLM uses `telegram_send_message` MCP tool to send alerts.

1. Message **@BotFather** → `/newbot` → copy the token
2. Add the bot to a group or DM it
3. Send any message to your bot — the agent will auto-detect your `chat_id` via `getUpdates` on first run
4. Optionally export `TELEGRAM_CHAT_ID` to skip auto-detection on subsequent runs

```bash
export TELEGRAM_BOT_TOKEN="7123...:AAF..."
export TELEGRAM_CHAT_ID="-1001234567890"  # optional — auto-fetched if not set
```

---

## Running the Agent

```bash
# With all credentials (HubSpot, Resend, Telegram)
export HUBSPOT_ACCESS_TOKEN="pat-na2-..."
export RESEND_API_KEY="re_xxx..."
export TELEGRAM_BOT_TOKEN="7123...:AAF..."
export TELEGRAM_CHAT_ID="-1001234567890"      # optional — auto-fetched if not set

# Run the agent
uv run python -m examples.templates.hubspot_revenue_leak_detector run

# Or via TUI
uv run python -m examples.templates.hubspot_revenue_leak_detector tui
```

---

## MCP Tools Used

All external integrations go exclusively through the `hive-tools` MCP server.

### HubSpot MCP Tools

| MCP Tool | Purpose |
|-----------|---------|
| `hubspot_search_deals` | Search for open HubSpot deals |
| `hubspot_search_contacts` | Fetch contact email addresses by deal name |

### Email MCP Tools

| MCP Tool | Purpose |
|-----------|---------|
| `send_email` | Send follow-up emails via Resend API |

### Telegram MCP Tools

| MCP Tool | Purpose |
|-----------|---------|
| `telegram_send_message` | Send Telegram alerts |

---

## Local Tools

| Tool | Purpose |
|------|---------|
| `scan_pipeline(cycle, deals)` | Normalises and stores HubSpot deals fetched by the LLM into a session-isolated ContextVar cache |
| `detect_revenue_leaks(cycle)` | Reads stored deals, classifies GHOSTED/STALLED patterns, computes severity + at-risk USD |
| `build_telegram_alert(...)` | Builds HTML Telegram message + prints console report; auto-fetches `chat_id` via `getUpdates` if not set |
| `prepare_followup_emails(cycle)` | Builds per-contact HTML email payloads for all GHOSTED contacts this cycle |

Tools are registered via `TOOLS` dict + `tool_executor()` pattern and discovered
automatically by `ToolRegistry.discover_from_module()` at agent startup.

---

## Halt Conditions

| Severity | Trigger | Action |
|----------|---------|--------|
| `critical` | ≥2 critical signals OR ≥$50k at risk | `halt = True` immediately |
| `high` | ≥3 leaks OR ≥$20k at risk | Continue monitoring |
| `medium` | ≥1 leak | Continue monitoring |
| `low` | 0 leaks | Halt after 3 consecutive low cycles |
