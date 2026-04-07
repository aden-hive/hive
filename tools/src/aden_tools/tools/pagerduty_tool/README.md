# PagerDuty Tool

Manage incidents, services, on-calls, and escalation policies via the PagerDuty REST API v2.

## Tools

| Tool | Description |
|------|-------------|
| `pagerduty_list_incidents` | List incidents with status, urgency, and date filters |
| `pagerduty_get_incident` | Get details of a specific incident |
| `pagerduty_create_incident` | Create a new incident |
| `pagerduty_update_incident` | Update an incident's status or assignment |
| `pagerduty_list_services` | List services with optional name filter |
| `pagerduty_list_oncalls` | List current on-call schedules |
| `pagerduty_add_incident_note` | Add a note to an incident |
| `pagerduty_list_escalation_policies` | List escalation policies |

## Setup

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `PAGERDUTY_API_KEY` | PagerDuty REST API token |
| `PAGERDUTY_FROM_EMAIL` | Email address for write operations (used in `From` header) |

Get a token at: [PagerDuty API Access Keys](https://support.pagerduty.com/docs/api-access-keys)

## Usage Examples

### List triggered incidents
```python
pagerduty_list_incidents(statuses=["triggered", "acknowledged"], limit=10)
```

### Create an incident
```python
pagerduty_create_incident(
    title="Database connection pool exhausted",
    service_id="P1234AB",
    urgency="high",
)
```

### Acknowledge an incident
```python
pagerduty_update_incident(incident_id="P5678CD", status="acknowledged")
```

### Check who's on call
```python
pagerduty_list_oncalls()
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "PAGERDUTY_API_KEY is required", "help": "Set PAGERDUTY_API_KEY environment variable"}
{"error": "PagerDuty API error (HTTP 404): Incident not found"}
{"error": "Request timed out"}
```
