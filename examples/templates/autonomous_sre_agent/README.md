# Autonomous SRE Incident Resolution Agent

An autonomous production incident resolution agent built on Hive. It accepts a production alert, fetches logs, analyzes root cause, estimates confidence, and either auto-resolves the incident or escalates to a human engineer — all without hardcoded workflows.

## Architecture

```
         Alert
           ↓
    Log Fetch Node
           ↓
  Root Cause Analyzer
           ↓
Historical Incident Memory
           ↓
Confidence + Severity Estimator
           ↓                    ↓
    confidence >= 80      confidence < 80
    severity != critical  OR severity == critical
           ↓                    ↓
    [Auto-Resolve]        [Human Escalation]
    draft_slack_message   full investigation summary
    draft_jira_ticket     human-in-the-loop pause
           ↓                    ↓
           └──────┬─────────────┘
                  ↓
          [Outcome Store] → long-term memory
                  ↓
          [Alert Intake] ← forever-alive loop
```

## Routing Logic

| Condition | Route |
|-----------|-------|
| confidence >= 80 AND severity != critical | Auto-Resolve |
| confidence < 80 OR severity == critical | Escalate to Human |

## Mock Tools (no real infra needed)

| Tool | Purpose |
|------|---------|
| `fetch_mock_logs` | Returns realistic log entries per alert type |
| `get_similar_incidents` | Returns historical incidents matching symptoms |
| `draft_slack_message` | Drafts a structured Slack alert message |
| `draft_jira_ticket` | Drafts a Jira incident ticket |
| `store_incident_outcome` | Stores outcome for future similarity matching |

## Demo Scenarios

**Scenario 1 — Auto-resolve (high confidence)**
```
Service: payment-service
Alert type: high_error_rate
→ Logs show DB connection pool exhausted
→ Similar incident INC-2847 found (92% match)
→ Confidence: 92 | Severity: high
→ Routes to: Auto-Resolve
→ Drafts Slack + Jira, presents remediation steps
```

**Scenario 2 — Escalate (critical severity)**
```
Service: auth-api
Alert type: high_error_rate
→ Logs show auth failures
→ Severity classified as: critical
→ Routes to: Escalate (regardless of confidence)
→ Presents full investigation summary to engineer
```

**Scenario 3 — Escalate (low confidence)**
```
Service: new-service
Alert type: unknown
→ No similar incidents found
→ Confidence capped at: 65
→ Routes to: Escalate
→ Engineer gets hypothesis + investigation steps
```

## Hive Features Demonstrated

- **Goal-driven generation** — agent graph built from natural language goal
- **Conditional edges** — confidence + severity determine routing dynamically
- **Human-in-the-loop** — escalation node pauses for engineer input
- **Long-term memory** — outcomes stored for future similarity matching
- **Forever-alive loop** — handles multiple incidents in one session
- **Adaptive evolution** — if remediation fails, Hive captures the failure data and evolves the agent graph to improve diagnosis in future runs
- **Real-time observability** — agent execution can be monitored live through the Hive dashboard, showing node decisions and routing paths

## Quick Start

```bash
# From hive root (Git Bash / WSL)
cd examples/templates/autonomous_sre_agent

# Validate structure
python -m autonomous_sre_agent validate

# Show agent info
python -m autonomous_sre_agent info

# Run TUI
python -m autonomous_sre_agent tui
```

## Goal Prompt (paste into Hive home screen)

```
Build an autonomous production incident resolution agent.

The agent should:
1. Accept a production alert as input (service name, alert type, description).
2. Fetch relevant logs using a log retrieval tool.
3. Analyze logs to determine likely root cause.
4. Retrieve similar historical incidents from memory to improve accuracy.
5. Classify severity level: critical, high, medium, or low.
6. Estimate confidence score (0-100%) for root cause accuracy.
   - Higher confidence if logs are clear and similar incidents found.
   - Cap at 70 if no historical matches exist.
7. If confidence >= 80% AND severity != critical:
   - Suggest numbered remediation steps.
   - Draft a Slack update message for #prod-alerts.
   - Draft a Jira ticket with title, description, and severity.
   - Present to user for approval.
8. If confidence < 80% OR severity is critical:
   - Trigger human-in-the-loop escalation.
   - Show: alert details, severity, confidence, root cause hypothesis,
     key log evidence, similar past incidents, recommended investigation steps.
9. Store the incident outcome in long-term memory for future similarity matching.
10. Loop back to accept the next alert (forever-alive).

Constraints:
- Critical severity incidents must ALWAYS be escalated. Never auto-resolve critical.
- Auto-resolution only permitted when confidence >= 80.
```
