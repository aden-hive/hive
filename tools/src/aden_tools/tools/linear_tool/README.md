# Linear Tool

Manage issues, projects, teams, labels, cycles, and users via the Linear GraphQL API.

## Tools

| Tool | Description |
|------|-------------|
| `linear_issue_create` | Create a new issue |
| `linear_issue_get` | Get issue details by ID or identifier |
| `linear_issue_update` | Update an existing issue |
| `linear_issue_delete` | Delete an issue |
| `linear_issue_search` | Search issues with filters |
| `linear_issue_add_comment` | Add a comment to an issue |
| `linear_issue_comments_list` | List comments on an issue |
| `linear_issue_relation_create` | Create a relation between two issues |
| `linear_project_create` | Create a new project |
| `linear_project_get` | Get project details |
| `linear_project_update` | Update a project |
| `linear_project_list` | List projects with optional filters |
| `linear_teams_list` | List all teams in the workspace |
| `linear_team_get` | Get team details including states and members |
| `linear_workflow_states_get` | Get workflow states for a team |
| `linear_label_create` | Create a new label for a team |
| `linear_labels_list` | List all labels |
| `linear_users_list` | List all users in the workspace |
| `linear_user_get` | Get user details and assigned issues |
| `linear_viewer` | Get details about the authenticated user |
| `linear_cycles_list` | List cycles (sprints) for a team |

## Setup

Requires a Linear personal API key:

```bash
export LINEAR_API_KEY="lin_api_your_api_key"
```

> Get your API key at https://linear.app/settings/api

## Usage Examples

### Create an issue
```python
linear_issue_create(
    title="Fix login bug",
    team_id="TEAM_UUID",
    description="Users cannot log in with SSO.",
    priority=1
)
```

### Get an issue
```python
linear_issue_get(issue_id="ENG-123")
```

### Search issues
```python
linear_issue_search(
    query="login bug",
    team_id="TEAM_UUID",
    limit=20
)
```

### Update an issue
```python
linear_issue_update(
    issue_id="ENG-123",
    state_id="STATE_UUID",
    priority=2
)
```

### Add a comment
```python
linear_issue_add_comment(
    issue_id="ENG-123",
    body="Fixed in PR #456. Ready for review."
)
```

### Create a relation between issues
```python
linear_issue_relation_create(
    issue_id="ENG-123",
    related_issue_id="ENG-456",
    relation_type="blocks"
)
```

### List teams
```python
linear_teams_list()
```

### Get workflow states for a team
```python
linear_workflow_states_get(team_id="TEAM_UUID")
```

### List cycles (sprints)
```python
linear_cycles_list(team_id="TEAM_UUID", limit=10)
```

### Get authenticated user
```python
linear_viewer()
```

## Priority Levels

| Value | Description |
|-------|-------------|
| `0` | No priority |
| `1` | Urgent |
| `2` | High |
| `3` | Medium |
| `4` | Low |

## Project States

| State | Description |
|-------|-------------|
| `planned` | Not yet started |
| `started` | In progress |
| `paused` | On hold |
| `completed` | Done |
| `canceled` | Canceled |

## Issue Relation Types

| Type | Description |
|------|-------------|
| `related` | Generally related (default) |
| `blocks` | This issue blocks the other |
| `duplicate` | Duplicate of the other issue |

## Error Handling

All tools return error dicts on failure:

```python
{"error": "Linear credentials not configured", "help": "Set LINEAR_API_KEY environment variable or configure via credential store. Get an API key at https://linear.app/settings/api"}
{"error": "Invalid or expired Linear API key"}
{"error": "Insufficient permissions. Check your Linear API key scopes."}
{"error": "Linear rate limit exceeded. Try again later."}
{"error": "Request timed out"}
```