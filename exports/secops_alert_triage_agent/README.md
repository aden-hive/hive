# SecOps Alert Triage Agent

Intelligent security alert triage: correlates alerts, suppresses false positives, classifies threats by severity, enriches with contextual intelligence, and escalates to on-call engineers with actionable incident briefs.

## Overview

Security teams are drowning in alert noise. The average enterprise receives thousands of security alerts per day, yet over 40% are false positives. This agent helps by:

- **Alert Intake**: Receives alerts from Datadog, Wiz, Snyk, PagerDuty, GitHub Advanced Security, or manual input
- **Deduplication & Correlation**: Groups related alerts by asset, time window, and attack pattern
- **False Positive Filtering**: Suppresses known false positives with documented rationale
- **Severity Classification**: Scores alerts as Critical/High/Medium/Low using CVSS, asset criticality, and exploit likelihood
- **Context Enrichment**: Adds service owner, deployment history, prior incidents, and threat intel
- **HITL Escalation**: Requires human acknowledgment for Critical/High alerts before any action
- **Daily Digest**: Generates comprehensive SecOps summaries with metrics

## Workflow

```
intake -> dedup -> fp-filter -> severity -> enrichment -> hitl-escalation -> digest
```

## Success Criteria

| Criterion | Target |
|-----------|--------|
| False Positive Suppression | >= 35% |
| Escalation Accuracy (no missed threats) | >= 90% |
| Human Confirmation for Critical/High | 100% |
| MTTR Improvement | >= 40% |
| Daily Digest Generation | Automatic |

## Usage

### CLI Commands

```bash
# Display agent information
uv run python -m secops_alert_triage_agent info

# Validate agent structure
uv run python -m secops_alert_triage_agent validate

# Interactive shell session
uv run python -m secops_alert_triage_agent shell

# Launch TUI (requires textual)
uv run python -m secops_alert_triage_agent tui
```

### Python API

```python
from secops_alert_triage_agent import SecOpsAlertTriageAgent

agent = SecOpsAlertTriageAgent()

# Start the agent
await agent.start()

# Process alerts
result = await agent.trigger_and_wait(
    entry_point="start",
    input_data={"alert_data": "..."}
)

# Stop the agent
await agent.stop()
```

## Input Format

The agent accepts security alerts in various formats:

### Datadog Alert
```json
{
  "alert_id": "dd-12345",
  "title": "Suspicious login detected",
  "severity": "high",
  "host": "prod-web-01",
  "timestamp": "2026-03-11T10:00:00Z"
}
```

### Generic Alert
```json
{
  "alert_id": "unique-id",
  "source": "manual",
  "timestamp": "2026-03-11T10:00:00Z",
  "title": "Alert title",
  "description": "Alert description",
  "severity": "high",
  "affected_asset": {
    "hostname": "server-01",
    "ip": "10.0.0.1",
    "service": "api-gateway",
    "environment": "production"
  }
}
```

## Configuration

### Suppression Rules

Default suppression rules include:
- Known CI/CD IP ranges (10.x.x.x, 172.16-31.x.x, 192.168.x.x)
- Approved vulnerability scanner signatures (Nessus, Qualys, Rapid7)
- Scheduled maintenance windows

### Asset Criticality

| Environment | Weight |
|-------------|--------|
| Production | 1.0 |
| Staging | 0.7 |
| Development | 0.3 |
| Internal | 0.2 |

## Constraints

- **Mandatory HITL**: No automated response for Critical/High alerts without human acknowledgment
- **Audit Trail**: Full audit trail for all triage decisions
- **Alert Preservation**: Original alert data is preserved
- **Rationale Logging**: All false positive determinations documented

## Nodes

| Node | Type | Description |
|------|------|-------------|
| intake | Client-facing | Alert intake and normalization |
| dedup | Internal | Deduplication and correlation |
| fp-filter | Internal | False positive filtering |
| severity | Internal | Severity classification |
| enrichment | Internal | Context enrichment |
| hitl-escalation | Client-facing | Human-in-the-loop escalation |
| digest | Client-facing | Daily digest and reporting |

## Testing

```bash
# Run structure tests
cd core && uv run pytest exports/secops_alert_triage_agent/tests/
```

## License

MIT
