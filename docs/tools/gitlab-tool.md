# GitLab Tool

The GitLab tool provides comprehensive integration with the GitLab API, enabling agents to automate DevOps workflows across projects, issues, merge requests, and CI/CD pipelines.

## Use Cases

- **Automated Triage**: Scan new issues, apply labels, and assign to milestones
- **Pipeline Recovery**: Analyze failed pipelines and post diagnostic comments
- **Merge Request Summaries**: Review MRs and summarize changes for reviewers
- **Cross-Platform Automation**: Bridge GitLab with other tools in your workflow

### Example Workflow

> "When a CI/CD pipeline fails, analyze the job logs, identify the error, and post a summary comment on the Merge Request."

## Available Tools

### `gitlab_list_projects`

Lists accessible GitLab projects with optional search and filtering.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `search` | string | No | Search term to filter projects by name |
| `owned` | boolean | No | If true, only return projects owned by the authenticated user |
| `limit` | int | No | Maximum projects to return (default: 20, max: 100) |

**Example Response:**
```json
{
  "projects": [
    {
      "id": 123,
      "name": "my-project",
      "path_with_namespace": "mygroup/my-project",
      "web_url": "https://gitlab.com/mygroup/my-project"
    }
  ]
}
```

### `gitlab_list_issues`

Lists issues for a project with optional state and label filtering.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | string | Yes | Project ID or path (e.g., `mygroup/myproject`) |
| `state` | string | No | Filter by state (`opened`, `closed`, `all`) |
| `labels` | string | No | Comma-separated label names to filter by |
| `limit` | int | No | Maximum issues to return (default: 20, max: 100) |

**Example Usage:**
```python
# List open bugs in a project
gitlab_list_issues(
    project_id="mygroup/myproject",
    state="opened",
    labels="bug,critical",
    limit=50
)
```

### `gitlab_get_merge_request`

Retrieves details of a specific merge request.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | string | Yes | Project ID or path |
| `mr_iid` | int | Yes | Merge request internal ID (the number in the UI) |

**Returns:**
- Full MR details including state, author, reviewers, and diff stats

### `gitlab_create_issue`

Creates a new issue in a GitLab project.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | string | Yes | Project ID or path |
| `title` | string | Yes | Issue title |
| `description` | string | No | Issue description (markdown supported) |
| `labels` | string | No | Comma-separated label names to apply |

**Example:**
```python
gitlab_create_issue(
    project_id="mygroup/myproject",
    title="Bug: Login fails on mobile",
    description="## Steps to Reproduce\n1. Open app on mobile\n2. Try to login",
    labels="bug,mobile"
)
```

### `gitlab_trigger_pipeline`

Triggers a new CI/CD pipeline for a specific branch or tag.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | string | Yes | Project ID or path |
| `ref` | string | Yes | Branch name or tag (e.g., `main`, `v1.0.0`) |

**Returns:**
- Pipeline object with ID, status, and web URL

**Example:**
```python
gitlab_trigger_pipeline(
    project_id="mygroup/myproject",
    ref="main"
)
```

## Authentication

### Personal Access Token (Recommended)

1. Go to GitLab → User Settings → Access Tokens
2. Create a new token with the `api` scope
3. Add the token to your `.env` file:

```bash
GITLAB_ACCESS_TOKEN=glpat-XXXXXXXXXXXXXXXX
```

### Self-Hosted GitLab Instances

For self-hosted GitLab instances, set the base URL:

```bash
GITLAB_URL=https://gitlab.mycompany.com
```

If not set, defaults to `https://gitlab.com`.

### Required Scopes

| Scope | Required For |
|-------|--------------|
| `api` | All GitLab tools |

## Credential Specification

```python
from aden_tools.credentials import GITLAB_CREDENTIALS

# Credential specs
GITLAB_CREDENTIALS = {
    "gitlab_access_token": CredentialSpec(
        env_var="GITLAB_ACCESS_TOKEN",
        tools=[...],  # All 5 GitLab tools
        required=True,
        description="Personal Access Token for GitLab API (Scope: api)",
        help_url="https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html",
    ),
    "gitlab_url": CredentialSpec(
        env_var="GITLAB_URL",
        tools=[...],  # All 5 GitLab tools
        required=False,  # Optional - defaults to gitlab.com
        description="Base URL for self-hosted GitLab instances",
    ),
}
```

## Error Handling

All tools return JSON responses. Errors are formatted as:

```json
{
  "error": "GitLab API error: 403",
  "details": "Insufficient permissions to perform this action"
}
```

Common error codes:
- `401` - Invalid or expired access token
- `403` - Insufficient permissions (check token scope)
- `404` - Project, issue, or MR not found
- `422` - Invalid request parameters

## Rate Limits

GitLab enforces rate limits:
- **gitlab.com**: 2000 requests per minute per user
- **Self-hosted**: Configurable by administrator

The tool does not implement automatic rate limiting. For high-volume operations, consider adding delays between requests.

## Project ID Formats

GitLab accepts project identifiers in two formats:

1. **Numeric ID**: `12345`
2. **Path with namespace**: `mygroup/myproject`

Path format is automatically URL-encoded by the tool.

## Limitations

- **Repository Access**: The MVP focuses on metadata (Issues/MRs/Pipelines) rather than direct file manipulation or git operations
- **Permissions**: Actions are limited by the permissions of the Access Token user
- **Pagination**: Results are capped at 100 items per request
