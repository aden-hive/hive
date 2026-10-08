# Power BI Tool

Manage Power BI workspaces, datasets, and reports via the Power BI REST API.

## Tools

| Tool | Description |
|------|-------------|
| `powerbi_list_workspaces` | List workspaces with optional name filter |
| `powerbi_list_datasets` | List datasets in a workspace |
| `powerbi_list_reports` | List reports in a workspace |
| `powerbi_refresh_dataset` | Trigger a dataset refresh |
| `powerbi_get_refresh_history` | Get refresh history for a dataset |

## Setup

Set the following environment variable:

| Variable | Description |
|----------|-------------|
| `POWERBI_ACCESS_TOKEN` | Power BI REST API bearer token |

Get a token via Azure AD: [Power BI REST API](https://learn.microsoft.com/en-us/power-bi/developer/embedded/register-app)

Required permissions: `Dataset.ReadWrite.All`, `Workspace.Read.All`

## Usage Examples

### List workspaces
```python
powerbi_list_workspaces()
```

### List datasets in a workspace
```python
powerbi_list_datasets(workspace_id="abc-123")
```

### Trigger a dataset refresh
```python
powerbi_refresh_dataset(workspace_id="abc-123", dataset_id="def-456")
```

### Check refresh history
```python
powerbi_get_refresh_history(workspace_id="abc-123", dataset_id="def-456")
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "POWERBI_ACCESS_TOKEN is required", "help": "Set POWERBI_ACCESS_TOKEN environment variable"}
{"error": "Power BI API error (HTTP 403): Insufficient permissions"}
{"error": "Request timed out"}
```
