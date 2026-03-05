```markdown
# Churn Risk Agent

Detects at-risk customers using engagement signals and triggers proactive
retention actions — with human-in-the-loop approval before any outreach is sent.

## What it does

1. Takes in customer account data (login activity, support tickets, NPS, renewal date)
2. Scores churn risk 0–100 across 5 criteria
3. Routes to the right action based on risk level:
   - **HIGH** → Immediate escalation alert to CSM
   - **MEDIUM** → Drafts personalised re-engagement email, waits for CSM approval
   - **LOW** → Silently logs, schedules re-check in 7 days
4. Produces a full audit trail of every decision

## Pipeline
```

signal_intake → risk_scoring → routing → escalation ↘
→ outreach → output_log
→ monitor ↗

````

## Quickstart

### 1. Set your API key

```bash
export GROQ_API_KEY=your_key_here
export LITELLM_MODEL=groq/llama-3.3-70b-versatile
````

### 2. Run interactively (TUI)

```bash
uv run python -m examples.templates.churn_risk_agent tui
```

### 3. Run from CLI

```bash
uv run python -m examples.templates.churn_risk_agent run \
  --account "Customer: Acme Corp, Last login: 45 days ago, Usage: monthly, Tickets: 4, NPS: 5, Renewal: 20 days"
```

### 4. Validate agent structure

```bash
uv run python -m examples.templates.churn_risk_agent validate
```

### 5. Show agent info

```bash
uv run python -m examples.templates.churn_risk_agent info
```

## Input format

Provide account data as a plain text string or JSON:

```
Customer: Acme Corp
Last login: 45 days ago
Feature usage: monthly
Support tickets (last 30 days): 4
NPS score: 5
Contract renewal: 20 days
```

## Scoring criteria

| Signal                               | Points |
| ------------------------------------ | ------ |
| Last login > 30 days ago             | +30    |
| Last login 15–30 days ago            | +15    |
| Feature usage monthly or never       | +20    |
| Support tickets >= 3 in last 30 days | +20    |
| NPS score <= 6                       | +20    |
| Contract renewal < 30 days away      | +10    |

**HIGH** >= 60 · **MEDIUM** 30–59 · **LOW** < 30

## Nodes

| Node          | Type                 | Description                          |
| ------------- | -------------------- | ------------------------------------ |
| signal_intake | client-facing        | Collects and confirms account data   |
| risk_scoring  | internal             | Scores 0–100 with reasoning          |
| routing       | internal             | Routes based on risk level           |
| escalation    | client-facing        | HIGH risk alert to CSM               |
| outreach      | client-facing (HITL) | MEDIUM risk email draft for approval |
| monitor       | internal             | LOW risk silent log                  |
| output        | client-facing        | Full audit trail                     |

## Use as a library

```python
from examples.templates.churn_risk_agent import ChurnRiskAgent

agent = ChurnRiskAgent()
result = await agent.run({
    "account_data": "Customer: Acme Corp, Last login: 45 days ago..."
})
print(result.output)
```

## Related issues

- [#5701](https://github.com/aden-hive/hive/issues/5701) — Agent proposal
- [#2805](https://github.com/aden-hive/hive/issues/2805) — Integrations hub

```

```
