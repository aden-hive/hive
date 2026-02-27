# HubSpot Revenue Leak Detector

An autonomous HubSpot CRM monitor built on the Aden Hive framework.
Continuously scans the sales pipeline, detects revenue leak patterns,
sends structured alerts, and emails ghosted contacts — cycling until a
critical threshold triggers escalation and halt.

---

## What It Detects

| Pattern | Trigger | Business Risk |
|---|---|---|
| **GHOSTED** | Prospect silent 21+ days | Lost deal value |
| **STALLED** | Deal stuck in same stage 10-20 days | Slow pipeline velocity |
| **OVERDUE_PAYMENT** | Invoice unpaid after due date | Cash flow leak |
| **CHURN_RISK** | 3+ unresolved support escalations | Customer churn |

---

## Agent Graph

```
monitor ──► analyze ──► notify ──► followup
                                       │
           ◄───────────────────────────┘   (loop while halt != true)
```

- **monitor** — LLM calls HubSpot MCP tools (`hubspot_search_deals`, `hubspot_get_deal`, `hubspot_get_contact`) to fetch deals, then `increment_cycle` and `detect_revenue_leaks` with fetched deals
- **analyze** — calls `detect_revenue_leaks` with fetched HubSpot deal data to classify leaks and compute severity
- **notify** — calls `send_telegram_alert` which internally uses `telegram_send_message` (MCP) to send Telegram alert + prints console report
- **followup** — LLM calls `prepare_followup_emails` to get email data, then `send_email` (MCP) to email GHOSTED contacts
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

### 2. Gmail / Email (Required)

The LLM uses `send_email` MCP tool to send follow-up emails.

**Note:** The TUI credential setup may show an "Use Aden Platform (OAuth)" option for Gmail.
This agent uses direct credential export (`GOOGLE_ACCESS_TOKEN`), not the Aden sync mechanism.
When setting up Gmail, select **"Enter API key directly"** and paste your access token.
Do NOT use the Aden option.

**Option 1: Gmail OAuth2 (Recommended)**
- Visit [https://hive.adenhq.com](https://hive.adenhq.com)
- Create an OAuth2 client with scopes: `https://www.googleapis.com/auth/gmail.send`
- Copy the client ID and secret
- Connect to authorize and get your access token
- Export `GOOGLE_ACCESS_TOKEN`

**Option 2: Resend API**
- Visit [https://resend.com/api-keys](https://resend.com/api-keys)
- Create an API key
- Export `RESEND_API_KEY`

```bash
# Gmail OAuth2
export GOOGLE_ACCESS_TOKEN="ya29..."

# Or Resend API
export RESEND_API_KEY="re_xxx..."
```

### 3. Telegram Alerts (Required)

The LLM uses `telegram_send_message` MCP tool to send alerts.

1. Message **@BotFather** → `/newbot` → copy the token
2. Add the bot to a group or DM it
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat.id`
4. Export `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`

```bash
export TELEGRAM_BOT_TOKEN="7123...:AAF..."
export TELEGRAM_CHAT_ID="-1001234567890"
```

---

## Running the Agent

```bash
# With all credentials (HubSpot, Gmail/Email, Telegram)
export HUBSPOT_ACCESS_TOKEN="pat-na2-..."
export GOOGLE_ACCESS_TOKEN="ya29..."          # Or RESEND_API_KEY="re_xxx..."
export TELEGRAM_BOT_TOKEN="7123...:AAF..."
export TELEGRAM_CHAT_ID="-1001234567890"

# Run the agent
uv run hive run examples/templates/hubspot_revenue_leak_detector --tui
```

---

## MCP Tools Used

The LLM uses a combination of local tools (which may wrap MCP tools) and direct MCP tool calls from the hive-tools server:

### HubSpot MCP Tools (directly invoked by LLM)

| MCP Tool | Purpose |
|-----------|---------|
| `hubspot_search_deals` | Search for open HubSpot deals |
| `hubspot_get_deal` | Get specific deal details |
| `hubspot_get_contact` | Fetch contact email addresses for follow-up |

### Email MCP Tools (directly invoked by LLM)

| MCP Tool | Purpose |
|-----------|---------|
| `send_email` | Send emails via Gmail OAuth2 or Resend API |

### Telegram MCP Tools (wrapped by local tool `send_telegram_alert`)

| MCP Tool | Purpose |
|-----------|---------|
| `telegram_send_message` | Send Telegram alerts |

---

## Local Tools

| Tool | Purpose |
|------|---------|
| `increment_cycle(cycle)` | Increments cycle counter; LLM uses HubSpot MCP tools to fetch deals |
| `detect_revenue_leaks(cycle, deals?)` | Classifies HubSpot deals, computes severity + at-risk USD |
| `send_telegram_alert(...)` | Sends Telegram alert via `telegram_send_message` MCP tool + prints console report |
| `prepare_followup_emails(cycle)` | Prepares contact list and HTML email body for follow-ups |

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
