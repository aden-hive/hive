# Pipedrive Tool

Manage deals, contacts, organizations, activities, and pipelines using the Pipedrive CRM API.

## Tools

| Tool | Description |
|------|-------------|
| `pipedrive_list_deals` | List deals with status, stage, and sort filters |
| `pipedrive_get_deal` | Get details of a specific deal |
| `pipedrive_create_deal` | Create a new deal |
| `pipedrive_update_deal` | Update a deal's properties |
| `pipedrive_list_persons` | List contacts with optional search |
| `pipedrive_search_persons` | Search contacts by name or email |
| `pipedrive_create_person` | Create a new contact |
| `pipedrive_list_organizations` | List organizations |
| `pipedrive_list_activities` | List activities with type and date filters |
| `pipedrive_create_activity` | Create a new activity |
| `pipedrive_list_pipelines` | List all sales pipelines |
| `pipedrive_list_stages` | List stages in a pipeline |
| `pipedrive_add_note` | Add a note to a deal, person, or organization |

## Setup

Set the following environment variable:

| Variable | Description |
|----------|-------------|
| `PIPEDRIVE_API_TOKEN` | Pipedrive API token |

Get a token at: Settings > Personal preferences > API in your Pipedrive account.

## Usage Examples

### List open deals
```python
pipedrive_list_deals(status="open", sort="update_time DESC", limit=20)
```

### Search for a contact
```python
pipedrive_search_persons(term="jane@example.com")
```

### Create a deal
```python
pipedrive_create_deal(title="Enterprise License", value=50000, currency="USD")
```

### Create a contact
```python
pipedrive_create_person(name="Jane Doe", email="jane@example.com")
```

### Create an activity
```python
pipedrive_create_activity(subject="Follow-up call", activity_type="call", due_date="2026-04-15")
```

### Add a note to a deal
```python
pipedrive_add_note(content="Follow up scheduled for next week.", deal_id=12345)
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "PIPEDRIVE_API_TOKEN not set", "help": "Get your API token from Pipedrive Settings > Personal preferences > API"}
{"error": "Pipedrive API error (HTTP 404): Deal not found"}
{"error": "Request timed out"}
```
