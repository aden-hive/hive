# Revenue Leak Detector Agent

An autonomous business health monitor built on the Aden Hive framework.
Continuously scans a CRM pipeline, detects revenue leak patterns, sends
structured alerts, and emails ghosted contacts — cycling until a critical
threshold triggers escalation and halt.

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

- **monitor** — calls `scan_pipeline(cycle)` to fetch CRM snapshot (HubSpot or empty fallback)
- **analyze** — calls `detect_revenue_leaks(cycle)` to classify leaks and compute severity
- **notify** — calls `send_revenue_alert(...)` to send console + Telegram alert
- **followup** — calls `send_followup_emails(cycle)` to email GHOSTED contacts via Gmail
- Loop halts when severity = **critical** or after **3 consecutive low-severity cycles**

---

## Running the Agent

```bash
# TUI mode (recommended) — no credentials needed for offline run
uv run hive run examples/templates/revenue_leak_detector --tui

# With real integrations
export HUBSPOT_API_KEY="pat-na2-..."          # HubSpot Private App token
export TELEGRAM_BOT_TOKEN="7123...:AAF..."    # Telegram bot token
export TELEGRAM_CHAT_ID="-1001234567890"      # Telegram chat/group ID
export GMAIL_USER="you@gmail.com"             # Gmail address
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"  # Gmail App Password

uv run hive run examples/templates/revenue_leak_detector --tui
```

All integrations are optional — the agent runs fully offline without any env vars.

---

## Integrations

### HubSpot CRM
- Set `HUBSPOT_API_KEY` to a Private App token with scopes:
  `crm.objects.deals.read`, `crm.objects.contacts.read`
- The agent fetches all open deals and their contact emails each cycle

### Telegram Alerts
1. Message **@BotFather** → `/newbot` → copy the token
2. Add the bot to a group or DM it
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat.id`
4. Export `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`

### Gmail Follow-up Emails
1. Enable 2-Step Verification on your Google account
2. Go to **myaccount.google.com → Security → App Passwords** → generate
3. Export `GMAIL_USER` + `GMAIL_APP_PASSWORD`
- Emails are sent only to GHOSTED contacts that have an email address in HubSpot

---

## Tools

| Tool | Purpose |
|------|---------|
| `scan_pipeline(cycle)` | Fetches CRM snapshot (HubSpot or empty), increments cycle counter |
| `detect_revenue_leaks(cycle)` | Classifies deals/invoices, computes severity + at-risk USD |
| `send_revenue_alert(...)` | Console report + real Telegram message if env vars set |
| `send_followup_emails(cycle)` | Gmail re-engagement emails to GHOSTED contacts |

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

