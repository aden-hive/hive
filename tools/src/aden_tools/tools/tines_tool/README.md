# Tines Tool

Manage Tines automation stories and actions via the Tines API.

## Tools

| Tool | Description |
|------|-------------|
| `tines_list_stories` | List stories with optional status filter |
| `tines_get_story` | Get details of a specific story |
| `tines_list_actions` | List actions in a story |
| `tines_get_action` | Get details of a specific action |
| `tines_get_action_logs` | Get execution logs for an action |

## Setup

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `TINES_API_KEY` | Tines API key |
| `TINES_DOMAIN` | Tines tenant URL (e.g., `https://your-tenant.tines.com`) |

Get an API key at: Settings → API Keys in your Tines account.

## Usage Examples

### List all stories
```python
tines_list_stories()
```

### Get story details
```python
tines_get_story(story_id=12345)
```

### List actions in a story
```python
tines_list_actions(story_id=12345)
```

### Get action logs
```python
tines_get_action_logs(action_id=67890)
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "TINES_DOMAIN and TINES_API_KEY are required", "help": "Set TINES_DOMAIN and TINES_API_KEY environment variables"}
{"error": "Tines API error (HTTP 404): Story not found"}
{"error": "Request timed out"}
```
