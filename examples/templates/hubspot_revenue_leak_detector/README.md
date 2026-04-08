# HubSpot Revenue Leak Detector

An autonomous HubSpot CRM monitor built on the Aden Hive framework.
Continuously scans the sales pipeline, detects revenue leak patterns,
sends structured Telegram alerts, and creates Gmail draft re-engagement emails
for ghosted contacts — cycling until a critical threshold triggers escalation and halt.

---

## What It Detects

| Pattern | Trigger | Business Risk |
|---|---|---|
| **GHOSTED** | No sales activity for **>30 days** | Lost deal value |
| **STALLED** | No sales activity for **15–30 days** (>14 and ≤30) | Slow pipeline velocity |

Inactivity is measured using `notes_last_contacted` (last logged call, email, or meeting),
which is populated on all HubSpot plans. Falls back to `hs_lastmodifieddate` if no activity
has ever been logged.

---

## Agent Graph

```
monitor ──► analyze ──► notify ──► followup
                                       │
           ◄───────────────────────────┘   (loop while halt != true)
```

- **monitor** — LLM calls `hubspot_search_deals` (with auto-retry on error) to fetch deals, then resolves contact emails via `hubspot_get_deal` (associations API) + `hubspot_get_contact`, then calls `scan_pipeline` to normalise and store deals
- **analyze** — calls `detect_revenue_leaks` to classify GHOSTED/STALLED patterns and compute severity
- **notify** — calls `build_telegram_alert` to build the report, then `telegram_send_message` (MCP) to send the Telegram alert + prints console report
- **followup** — calls `prepare_followup_emails` to get email payloads, then `gmail_create_draft` (MCP) to create Gmail drafts for GHOSTED contacts
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

### 2. Google Account / Gmail (Required)

The LLM uses `gmail_create_draft` MCP tool to create follow-up email drafts for GHOSTED contacts.

1. Open the Hive app (`hive open`)
2. Go to **Credentials → Add** and sign in with Google
3. Grant Gmail access when prompted

> **Note:** Drafts are created in your Gmail for review — the agent never sends emails automatically.

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
# With all credentials (HubSpot, Google OAuth via hive open, Telegram)
export HUBSPOT_ACCESS_TOKEN="pat-na2-..."
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
| `hubspot_search_deals` | Search for open HubSpot deals (retried once on error) |
| `hubspot_get_deal` | Fetch deal associations (contact IDs) via Associations API |
| `hubspot_get_contact` | Fetch contact email, firstname, lastname by ID |

### Email MCP Tools

| MCP Tool | Purpose |
|-----------|---------|
| `gmail_create_draft` | Create follow-up email drafts in Gmail for GHOSTED contacts |

### Telegram MCP Tools

| MCP Tool | Purpose |
|-----------|---------|
| `telegram_send_message` | Send Telegram alerts |

---

## Local Tools

| Tool | Purpose |
|------|---------|
| `scan_pipeline(cycle, deals)` | Normalises HubSpot deals (resolves `notes_last_contacted` → `days_inactive`, maps stage IDs); serialises to `deals_json` passed between nodes |
| `detect_revenue_leaks(cycle, deals_json)` | Classifies GHOSTED (>30d) / STALLED (>14d) patterns, computes severity + at-risk USD; returns `leaks_json` |
| `build_telegram_alert(...)` | Builds HTML Telegram message + prints console report from `leaks_json`; auto-fetches `chat_id` via `getUpdates` if not set |
| `prepare_followup_emails(cycle, leaks_json)` | Builds per-contact HTML email payloads for all GHOSTED contacts this cycle |

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
