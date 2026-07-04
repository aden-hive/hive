# n8n Tool

Manage n8n workflows, executions, and trigger workflows via webhooks using the n8n REST API.

## Tools

| Tool | Description |
|------|-------------|
| `n8n_list_workflows` | List workflows with optional status and tag filters |
| `n8n_get_workflow` | Get details of a specific workflow |
| `n8n_activate_workflow` | Activate a workflow |
| `n8n_deactivate_workflow` | Deactivate a workflow |
| `n8n_list_executions` | List workflow executions with optional status filter |
| `n8n_get_execution` | Get details of a specific execution |
| `n8n_trigger_webhook` | Trigger a workflow via its webhook URL (no API key needed) |

## Setup

### API-based tools (workflow & execution management)

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `N8N_API_KEY` | n8n API key |
| `N8N_BASE_URL` | n8n instance URL (e.g., `https://your-n8n.example.com`) |

Get an API key at: Settings → API → Create API Key in your n8n instance.

### Webhook tool (`n8n_trigger_webhook`)

No API key or environment variable needed. The webhook URL is self-contained
and acts as the authentication token. Simply copy it from the Webhook node in
your n8n workflow editor and pass it directly as the `webhook_url` argument.

## Usage Examples

### Trigger a workflow via webhook
```python
n8n_trigger_webhook(
    webhook_url="https://my-n8n.example.com/webhook/order-alert",
    payload={"order_id": "ORD-999", "amount": 149.99},
)
```

### Trigger with custom headers
```python
n8n_trigger_webhook(
    webhook_url="https://my-n8n.example.com/webhook/abc123",
    payload={"event": "user_signup", "email": "user@example.com"},
    headers={"X-Source": "hive-agent"},
)
```

### Trigger via GET (for webhooks configured to accept GET requests)
```python
n8n_trigger_webhook(
    webhook_url="https://my-n8n.example.com/webhook/ping",
    method="GET",
    payload={"check": "health"},
)
```

### List active workflows
```python
n8n_list_workflows(active="true")
```

### Get workflow details
```python
n8n_get_workflow(workflow_id="123")
```

### Activate a workflow
```python
n8n_activate_workflow(workflow_id="123")
```

### List recent executions
```python
n8n_list_executions(status="success", limit=10)
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "webhook_url is required"}
{"error": "Webhook returned HTTP 404", "detail": "...", "triggered": false}
{"error": "Request timed out", "triggered": false}
{"error": "n8n credentials not configured", "help": "Set N8N_API_KEY and N8N_BASE_URL ..."}
{"error": "n8n API error (HTTP 404): Workflow not found"}
```
