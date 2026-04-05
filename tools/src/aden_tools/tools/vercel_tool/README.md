# Vercel Tool

Manage deployments, projects, domains, and environment variables via the Vercel REST API.

## Tools

| Tool | Description |
|------|-------------|
| `vercel_list_deployments` | List deployments, optionally filtered by project or state |
| `vercel_get_deployment` | Get details of a specific deployment |
| `vercel_list_projects` | List all Vercel projects |
| `vercel_get_project` | Get details of a specific project |
| `vercel_list_project_domains` | List domains configured for a project |
| `vercel_list_env_vars` | List environment variables for a project |
| `vercel_create_env_var` | Create an environment variable for a project |

## Setup

Requires a Vercel access token:

```bash
export VERCEL_TOKEN="your_vercel_token"
```

> Get a token at https://vercel.com/account/tokens

## Usage Examples

### List recent deployments
```python
vercel_list_deployments(limit=10, state="READY")
```

### List deployments for a specific project
```python
vercel_list_deployments(project_id="my-project", limit=5)
```

### Get deployment details
```python
vercel_get_deployment(deployment_id="dpl_abc123")
```

### List all projects
```python
vercel_list_projects(limit=20)
```

### Get project details
```python
vercel_get_project(project_id="my-project")
```

### List domains for a project
```python
vercel_list_project_domains(project_id="my-project")
```

### List environment variables
```python
vercel_list_env_vars(project_id="my-project")
```

### Create an environment variable
```python
vercel_create_env_var(
    project_id="my-project",
    key="DATABASE_URL",
    value="postgresql://user:pass@host/db",
    target="production,preview",
    env_type="encrypted"
)
```

## Deployment States

| State | Description |
|-------|-------------|
| `BUILDING` | Currently building |
| `READY` | Live and serving traffic |
| `ERROR` | Build or runtime error |
| `QUEUED` | Waiting to build |
| `INITIALIZING` | Starting up |
| `CANCELED` | Manually canceled |

## Environment Variable Types

| Type | Description |
|------|-------------|
| `encrypted` | Encrypted at rest, not visible after creation (default) |
| `plain` | Plaintext, visible in dashboard |
| `sensitive` | Encrypted, never shown after creation |
| `system` | System-provided variable |

## Error Handling

All tools return error dicts on failure:

```python
{"error": "VERCEL_TOKEN not set", "help": "Get a token at https://vercel.com/account/tokens"}
{"error": "Unauthorized. Check your VERCEL_TOKEN."}
{"error": "Forbidden: ..."}
{"error": "Vercel API error 404: ..."}
{"error": "Request to Vercel timed out"}
```