# Terraform Tool

Manage Terraform Cloud/Enterprise workspaces and runs via the Terraform API.

## Tools

| Tool | Description |
|------|-------------|
| `terraform_list_workspaces` | List workspaces in an organization |
| `terraform_get_workspace` | Get details of a specific workspace |
| `terraform_list_runs` | List runs for a workspace |
| `terraform_get_run` | Get details of a specific run |
| `terraform_create_run` | Trigger a new plan/apply run |

## Setup

Set the following environment variable:

| Variable | Description |
|----------|-------------|
| `TFC_TOKEN` | Terraform Cloud/Enterprise API token |
| `TFC_URL` | Terraform Enterprise URL (optional, defaults to Terraform Cloud) |

Get a token at: [Terraform Cloud Tokens](https://app.terraform.io/app/settings/tokens)

Note: The `organization` name is passed as a parameter to tools, not as an environment variable.

## Usage Examples

### List workspaces
```python
terraform_list_workspaces(organization="my-org")
```

### Get workspace details
```python
terraform_get_workspace(workspace_id="ws-abc123")
```

### List runs for a workspace
```python
terraform_list_runs(workspace_id="ws-abc123")
```

### Trigger a new run
```python
terraform_create_run(workspace_id="ws-abc123", message="Deploy v2.1.0")
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "TFC_TOKEN is required", "help": "Set TFC_TOKEN environment variable"}
{"error": "organization is required"}
{"error": "Request timed out"}
```
