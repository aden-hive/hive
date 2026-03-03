# Recipe: Issue Triaging

Categorizing and routing incoming bug reports by severity and type.

## Why

Not all bugs are equal. A typo in the footer can wait; a checkout failure cannot. This agent sorts the incoming chaos — categorizing issues by severity, gathering reproduction steps, and routing them to the right person — so critical bugs get fixed fast and minor ones don't clog the queue.

## What

- Categorize incoming issues by type (bug, feature request, question)
- Assess severity based on impact and frequency
- Gather reproduction steps and environment details
- Route to appropriate team member or queue
- Track issue lifecycle from report to resolution

## Integrations

| Platform | Purpose |
|----------|---------|
| GitHub Issues / Linear / Jira | Issue tracking |
| Sentry / LogRocket / Datadog | Error context and logs |
| Slack | Triage notifications and discussion |
| Intercom / Zendesk | Customer-reported issue intake |
| Notion | Issue categorization rules and playbooks |
| PagerDuty | Critical issue escalation |

## Escalation Path

| Trigger | Action |
|---------|--------|
| Security vulnerability reported | Immediate escalation, mark as confidential |
| Data loss or corruption issue | P0 alert with all available context |
| Issue affecting >10% of users | Escalate as incident with scope estimate |
| Issue unsolvable within 30 minutes | Escalate with what was tried and ruled out |
| Customer-reported issue from enterprise account | Priority flag regardless of severity assessment |
| Same issue reported 5+ times in 24h | Alert as emerging pattern, consider incident |
| Issue requires architecture decision | Queue for tech lead review |
