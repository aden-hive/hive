# GitLab Tool

Manage GitLab projects, issues, and merge requests via the GitLab REST API v4.

## Setup

```bash
# Optional for self-hosted instances (defaults to gitlab.com)
export GITLAB_URL=https://gitlab.com

# Required
export GITLAB_TOKEN=your_personal_access_token
```

Create a personal access token at https://gitlab.com/-/user_settings/personal_access_tokens

Alternatively, configure credentials in the Aden credential store:
- `gitlab_token`

Note: The GitLab URL should be set via the `GITLAB_URL` environment variable
(defaults to `https://gitlab.com` if not set).
Tip: If you use GitLab.com, you can omit `GITLAB_URL`.

## Tools (9)

| Tool | Description |
|------|-------------|
| `gitlab_list_projects` | List projects you have access to |
| `gitlab_get_project` | Get project details by ID or path |
| `gitlab_list_issues` | List issues in a project |
| `gitlab_get_issue` | Get issue details |
| `gitlab_create_issue` | Create a new issue |
| `gitlab_update_issue` | Update an existing issue |
| `gitlab_list_merge_requests` | List merge requests in a project |
| `gitlab_get_merge_request` | Get merge request details |
| `gitlab_create_merge_request_note` | Add a note to a merge request |

## Usage

### List projects

```python
result = gitlab_list_projects(search="hive", per_page=10)
```

### Create an issue

```python
result = gitlab_create_issue(
    project_id="group%2Fproject",
    title="Add retry logic to worker executor",
    description="Retries should respect failure budgets.",
)
```

### List merge requests

```python
result = gitlab_list_merge_requests(
    project_id="group%2Fproject",
    state="opened",
)
```

## Scope

- Project discovery and details
- Issue listing, creation, retrieval, and updates
- Merge request listing, retrieval, and notes

## API Reference

- GitLab REST API v4: https://docs.gitlab.com/api/rest/
