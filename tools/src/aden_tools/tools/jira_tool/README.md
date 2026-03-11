# Jira Tool

Manage Jira Cloud issues, comments, projects, and workflow transitions from the Aden agent framework.

## Setup

```bash
export JIRA_DOMAIN=your-domain.atlassian.net
export JIRA_EMAIL=you@example.com
export JIRA_API_TOKEN=your-api-token
```

**Get your API token:**
1. Go to https://id.atlassian.com/manage/api-tokens
2. Create a new API token for your Atlassian account
3. Copy the token and keep it secure
4. Set `JIRA_DOMAIN`, `JIRA_EMAIL`, and `JIRA_API_TOKEN`

Alternatively, configure Jira credentials through the Aden credential store.

## Tools (9)

| Tool | Description |
|------|-------------|
| `jira_search_issues` | Search issues with JQL |
| `jira_get_issue` | Get issue details by key |
| `jira_create_issue` | Create a new Jira issue |
| `jira_list_projects` | List accessible Jira projects |
| `jira_get_project` | Get project details by key |
| `jira_add_comment` | Add a comment to an issue |
| `jira_update_issue` | Update issue fields like summary, description, priority, labels, or assignee |
| `jira_list_transitions` | List available status transitions for an issue |
| `jira_transition_issue` | Move an issue to a new workflow state |

## Usage

### Search issues with JQL

```python
result = jira_search_issues(
    jql="project = ENG AND status = 'In Progress'",
    max_results=10,
)
```

### Create an issue

```python
result = jira_create_issue(
    project_key="ENG",
    summary="Add retry budget visibility to worker runs",
    issue_type="Task",
    description="Track retries and expose them in observability views.",
)
```

### Transition an issue

```python
result = jira_transition_issue(
    issue_key="ENG-123",
    transition_id="31",
    comment="Moving this issue into review.",
)
```

## Scope

- JQL-based issue search and issue detail retrieval
- Issue creation, updates, comments, and workflow transitions
- Project discovery for planning and routing workflows

## API Reference

- [Jira Cloud REST API v3](https://developer.atlassian.com/cloud/jira/platform/rest/v3/)
