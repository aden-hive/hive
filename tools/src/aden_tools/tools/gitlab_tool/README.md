# GitLab Tool

Manage GitLab projects, issues, and merge requests via the GitLab REST API v4.

## Tools

| Tool | Description |
|------|-------------|
| `gitlab_list_projects` | List projects with optional search and visibility filters |
| `gitlab_get_project` | Get details of a specific project |
| `gitlab_list_issues` | List issues with state, label, and assignee filters |
| `gitlab_get_issue` | Get details of a specific issue |
| `gitlab_create_issue` | Create a new issue in a project |
| `gitlab_update_issue` | Update an existing issue (title, description, state, labels, assignee) |
| `gitlab_list_merge_requests` | List merge requests with state and label filters |
| `gitlab_get_merge_request` | Get details of a specific merge request |
| `gitlab_create_merge_request_note` | Add a comment to a merge request |

## Setup

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `GITLAB_TOKEN` | GitLab personal access token |
| `GITLAB_URL` | GitLab instance URL (optional, defaults to `https://gitlab.com`) |

Get a token at: [GitLab Access Tokens](https://gitlab.com/-/user_settings/personal_access_tokens)

Required scopes: `api` (full API access) or `read_api` + `read_repository` for read-only.

Alternatively, configure credentials in the Aden credential store:
- `gitlab_token`

## Usage Examples

### List your projects

```python
gitlab_list_projects(membership=True, per_page=10)
```

### Search for issues

```python
gitlab_list_issues(project_id="12345", state="opened", labels="bug")
```

### Create an issue

```python
gitlab_create_issue(project_id="12345", title="Fix login bug", description="Steps to reproduce...")
```

### Add a comment to a merge request

```python
gitlab_create_merge_request_note(project_id="12345", merge_request_iid=42, body="LGTM!")
```

## Error Handling

All tools return error dicts on failure:

```python
{"error": "GITLAB_TOKEN not set", "help": "Create a personal access token at https://gitlab.com/-/user_settings/personal_access_tokens"}
{"error": "Unauthorized. Check your GitLab token."}
{"error": "Forbidden. Insufficient permissions."}
{"error": "Request to GitLab timed out"}
```
