# n8n Tool

Manage n8n workflows and executions via the n8n REST API.

## Tools

| Tool | Description |
|------|-------------|
| `n8n_list_workflows` | List workflows with optional status and tag filters |
| `n8n_get_workflow` | Get details of a specific workflow |
| `n8n_activate_workflow` | Activate a workflow |
| `n8n_deactivate_workflow` | Deactivate a workflow |
| `n8n_list_executions` | List workflow executions with optional status filter |
| `n8n_get_execution` | Get details of a specific execution |

## Setup

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `N8N_API_KEY` | n8n API key |
| `N8N_BASE_URL` | n8n instance URL (e.g., `https://your-n8n.example.com`) |

Get an API key at: Settings → API → Create API Key in your n8n instance.

## Usage Examples

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
{"error": "n8n credentials not configured", "help": "Set N8N_API_KEY and N8N_BASE_URL environment variables or configure via credential store"}
{"error": "n8n API error (HTTP 404): Workflow not found"}
{"error": "Request timed out"}
```
