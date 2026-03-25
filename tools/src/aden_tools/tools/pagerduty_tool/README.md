# PagerDuty Tool

Incident management and on-call operations via the PagerDuty REST API v2.

## Supported Actions

- **pagerduty_list_incidents** / **pagerduty_get_incident** / **pagerduty_create_incident** / **pagerduty_update_incident** – Incident lifecycle management
- **pagerduty_list_services** – List monitored services
- **pagerduty_list_oncalls** – List current on-call schedules
- **pagerduty_add_incident_note** – Add a note to an incident timeline
- **pagerduty_list_escalation_policies** – List escalation policies

## Setup

1. Create an API key in PagerDuty (Integrations → API Access Keys).

2. Set the required environment variables:
   ```bash
   export PAGERDUTY_API_KEY=your-api-key
   export PAGERDUTY_FROM_EMAIL=your-email@example.com   # required for write operations
   ```

## Use Case

Example: "List all triggered incidents on the 'Production API' service, acknowledge them, add a note with initial triage findings, and page the current on-call if any are P1."
