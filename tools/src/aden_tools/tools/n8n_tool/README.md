# n8n Workflow Automation Tool

Trigger and monitor n8n workflow automations from Hive agents.

## Overview

This tool enables agents to:
- **Trigger workflow execution** via API or webhook
- **Check execution status** (success/failed/running)
- **List and discover workflows** for dynamic triggering
- **Activate/deactivate workflows** programmatically

## Setup

### Environment Variables

```bash
# Required
export N8N_API_URL="https://your-n8n-instance.com"
export N8N_API_KEY="your-api-key"

# Alternative URL variable (also supported)
export N8N_URL="https://your-n8n-instance.com"
```

### Credential Store

Alternatively, configure via the credential store with key `n8n`:

```json
{
  "api_url": "https://your-n8n-instance.com",
  "api_key": "your-api-key"
}
```

### Getting an API Key

1. In n8n, go to **Settings** → **API**
2. Create a new API key with appropriate permissions
3. Copy the key and set it as `N8N_API_KEY`

## Tools

### n8n_execute_workflow

Execute a workflow directly by ID.

```python
result = n8n_execute_workflow(
    workflow_id="123",
    data={"input": "value"}  # Optional input data
)
# Returns: {"success": True, "execution_id": "exec-456", "status": "success"}
```

### n8n_trigger_webhook

Trigger a workflow via its webhook URL. Preferred for production workflows.

```python
# Using webhook path
result = n8n_trigger_webhook(
    webhook_path="my-workflow-hook",
    data={"event": "new_order", "order_id": 12345}
)

# Using full URL
result = n8n_trigger_webhook(
    webhook_path="https://n8n.example.com/webhook/custom-path",
    data={"payload": "data"}
)

# Using GET method
result = n8n_trigger_webhook(
    webhook_path="status-check",
    method="GET"
)
```

### n8n_get_execution_status

Check the status of a workflow execution.

```python
result = n8n_get_execution_status(execution_id="exec-123")
# Returns:
# {
#   "success": True,
#   "execution": {
#     "id": "exec-123",
#     "status": "success",  # or "error", "running", "waiting"
#     "startedAt": "2024-01-15T10:00:00Z",
#     "stoppedAt": "2024-01-15T10:00:05Z",
#     "finished": True,
#     "data": {...}  # Output data
#   }
# }
```

### n8n_list_executions

List recent executions with optional filters.

```python
# List all recent executions
result = n8n_list_executions(limit=20)

# Filter by workflow
result = n8n_list_executions(workflow_id="wf-123")

# Filter by status
result = n8n_list_executions(status="error")  # success, error, waiting, running
```

### n8n_list_workflows

Discover available workflows.

```python
# List all workflows
result = n8n_list_workflows()

# List only active workflows
result = n8n_list_workflows(active_only=True)
```

### n8n_get_workflow

Get detailed information about a specific workflow.

```python
result = n8n_get_workflow(workflow_id="wf-123")
# Returns workflow details including nodes, name, active status
```

### n8n_activate_workflow

Enable or disable a workflow.

```python
# Activate
result = n8n_activate_workflow(workflow_id="wf-123", active=True)

# Deactivate
result = n8n_activate_workflow(workflow_id="wf-123", active=False)
```

## Use Cases

### Agent-Triggered Automation

When an agent classifies a ticket as urgent:

```python
# Trigger paging workflow
n8n_trigger_webhook(
    webhook_path="urgent-ticket",
    data={
        "ticket_id": ticket.id,
        "priority": "urgent",
        "summary": ticket.summary
    }
)
```

### Workflow Status Monitoring

Check if a background workflow completed:

```python
# Execute workflow
exec_result = n8n_execute_workflow(workflow_id="data-sync")
execution_id = exec_result["execution_id"]

# Later, check status
status = n8n_get_execution_status(execution_id)
if status["execution"]["status"] == "success":
    print("Sync completed!")
elif status["execution"]["status"] == "error":
    print("Sync failed - check n8n logs")
```

### Dynamic Workflow Discovery

Find and trigger workflows by name pattern:

```python
workflows = n8n_list_workflows(active_only=True)
for wf in workflows["workflows"]:
    if "notification" in wf["name"].lower():
        n8n_execute_workflow(workflow_id=wf["id"])
```

## Error Handling

All tools return a consistent error format:

```python
{
    "error": "Error message",
    "help": "Helpful suggestion for resolution"  # When applicable
}
```

Common errors:
- `n8n API URL not configured` - Set `N8N_API_URL` environment variable
- `n8n API key not configured` - Set `N8N_API_KEY` environment variable
- `Invalid n8n API key` - Check your API key is correct
- `Resource not found` - Workflow or execution ID doesn't exist

## API Reference

Based on the [n8n Public API](https://docs.n8n.io/api/):
- `POST /api/v1/workflows/{id}/execute` - Execute workflow
- `GET /api/v1/executions/{id}` - Get execution details
- `GET /api/v1/executions` - List executions
- `GET /api/v1/workflows` - List workflows
- `GET /api/v1/workflows/{id}` - Get workflow details
- `PATCH /api/v1/workflows/{id}` - Update workflow (activate/deactivate)
- `POST /webhook/{path}` - Trigger webhook
