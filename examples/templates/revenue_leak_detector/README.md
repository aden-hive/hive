# Revenue Leak Detector Agent

An autonomous business health monitor built on the Aden Hive framework.
Continuously scans a simulated CRM pipeline across 3 escalating cycles,
detects revenue leak patterns, and sends structured alerts until a critical
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
monitor ──► analyze ──► notify
                           │
           ◄───────────────┘   (loop while severity < critical)
```

- **monitor** — calls `scan_pipeline(cycle)` to load CRM snapshot
- **analyze** — calls `detect_revenue_leaks(cycle)` to classify and score leaks
- **notify** — calls `send_revenue_alert(...)` to print structured Telegram/Slack-style alert
- Loop halts automatically when severity reaches **critical**

---

## Cycle Progression

| Cycle | Leaks | Severity | At Risk |
|-------|-------|----------|---------|
| 1 | 2 (STALLED × 1, GHOSTED × 1) | medium | ~$18 k |
| 2 | 4 (GHOSTED × 2, OVERDUE × 1, STALLED × 1) | high | ~$55 k |
| 3 | 5 (GHOSTED × 2, OVERDUE × 2, CHURN_RISK × 1) | **critical** | ~$55 k+ |

On cycle 3, severity = `critical` → `halt = True` → loop exits.

---

## Running the Agent

```bash
# Console-only mode (no credentials needed)
uv run python -m examples.templates.revenue_leak_detector

# With real Telegram alerts
export TELEGRAM_BOT_TOKEN="7123456789:AAFxxxYourTokenHere"
export TELEGRAM_CHAT_ID="-1001234567890"
uv run python -m examples.templates.revenue_leak_detector
```

---

## Telegram Setup (5 minutes)

1. Open Telegram → search **@BotFather** → send `/newbot` → follow prompts → copy the token
2. Add your bot to a group **or** DM it directly
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` → find your `chat.id` in the JSON
4. Export both env vars (or add to `~/.bashrc`):
   ```bash
   export TELEGRAM_BOT_TOKEN="7123456789:AAFxxxYourTokenHere"
   export TELEGRAM_CHAT_ID="-1001234567890"   # negative = group, positive = DM
   ```
5. Run the agent — each cycle delivers a real HTML-formatted message to your chat

---

## Tools

| Tool | Purpose |
|------|---------|
| `scan_pipeline(cycle)` | Loads CRM snapshot, increments cycle counter |
| `detect_revenue_leaks(cycle)` | Classifies deals/invoices, computes severity + at-risk USD |
| `send_revenue_alert(...)` | Prints console report **and** sends real Telegram message if env vars set |

---

## Extending This Agent

- **Real CRM**: Replace `_PIPELINE_DB` in `tools.py` with a live `httpx` call to HubSpot, Salesforce, or Pipedrive
- **Slack**: Set `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID` and add a `_send_slack()` helper alongside `_send_telegram()`
- **Human-in-the-loop**: Add a `pause_node` before `notify` — agent waits for manager approval before escalating
- **Auto-follow-up**: Add a `followup_node` that calls `send_email(contact)` when GHOSTED leaks are found
- **Webhooks**: POST the `tg_message` payload to any webhook URL (Discord, Teams, PagerDuty, etc.)
