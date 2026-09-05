# Jira Tool

Search, create, update, and transition Jira issues and projects via the Jira Cloud REST API v3.

## Tools

| Tool | Description |
|------|-------------|
| `jira_search_issues` | Search issues using JQL |
| `jira_get_issue` | Get full details of a specific issue |
| `jira_create_issue` | Create a new issue in a project |
| `jira_update_issue` | Update fields on an existing issue |
| `jira_list_transitions` | List available status transitions for an issue |
| `jira_transition_issue` | Move an issue to a new status |
| `jira_add_comment` | Add a comment to an issue |
| `jira_list_projects` | List all projects in the workspace |
| `jira_get_project` | Get details about a specific project |

## Setup

Requires Jira Cloud credentials:

```bash
export JIRA_DOMAIN="your-org.atlassian.net"
export JIRA_EMAIL="you@example.com"
export JIRA_API_TOKEN="your_api_token"
```

> Create an API token at https://id.atlassian.com/manage/api-tokens

Alternatively, configure credentials in the Aden credential store:
- `jira_domain`
- `jira_email`
- `jira_token`

## Usage Examples

### Search issues with JQL
```python
jira_search_issues(
    jql="project = PROJ AND status = 'In Progress'",
    max_results=25
)
```

### Get issue details
```python
jira_get_issue(issue_key="PROJ-123")
```

### Create a new issue
```python
jira_create_issue(
    project_key="PROJ",
    summary="Fix login bug",
    issue_type="Bug",
    description="Users cannot log in with SSO.",
    priority="High",
    labels="auth,sso"
)
```

### Update an issue
```python
jira_update_issue(
    issue_key="PROJ-123",
    summary="Updated title",
    priority="Medium"
)
```

### Transition an issue to a new status
```python
# Step 1: find available transitions
jira_list_transitions(issue_key="PROJ-123")

# Step 2: apply the transition
jira_transition_issue(
    issue_key="PROJ-123",
    transition_id="31",
    comment="Moving to done after review."
)
```

### Add a comment
```python
jira_add_comment(
    issue_key="PROJ-123",
    body="This has been fixed in the latest deploy."
)
```

### List all projects
```python
jira_list_projects(max_results=50, query="backend")
```

### Get project details
```python
jira_get_project(project_key="PROJ")
```

## Issue Types

| Type | Description |
|------|-------------|
| `Task` | Standard work item (default) |
| `Bug` | Defect or problem |
| `Story` | User story |
| `Epic` | Large body of work |

## Priority Levels

| Priority | Description |
|----------|-------------|
| `Highest` | Critical |
| `High` | Important |
| `Medium` | Normal |
| `Low` | Minor |
| `Lowest` | Trivial |

## Error Handling

All tools return error dicts on failure:

```python
{"error": "JIRA_DOMAIN, JIRA_EMAIL, and JIRA_API_TOKEN not set", "help": "Create an API token at https://id.atlassian.com/manage/api-tokens"}
{"error": "Unauthorized. Check your Jira credentials."}
{"error": "Forbidden. Check your Jira permissions."}
{"error": "Rate limited. Try again shortly."}
{"error": "Not found."}
```
