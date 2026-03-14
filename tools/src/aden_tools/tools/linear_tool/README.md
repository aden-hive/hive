# Linear Tool

Manage Linear issues, projects, teams, users, labels, and cycles from the Aden agent framework.

## Setup

```bash
export LINEAR_API_KEY=lin_api_your_key
```

**Get your key:**
1. Go to https://linear.app/developers
2. Open your Linear settings and create a Personal API key
3. Grant the permissions your workflow needs
4. Copy the key and set `LINEAR_API_KEY`

Alternatively, configure Linear through the Aden credential store.

## Tools (21)

| Tool | Description |
|------|-------------|
| `linear_issue_create` | Create a new Linear issue |
| `linear_issue_get` | Fetch an issue by UUID or identifier like `ENG-123` |
| `linear_issue_update` | Update issue fields such as title, description, assignee, or state |
| `linear_issue_delete` | Delete an existing issue |
| `linear_issue_search` | Search issues with filters for team, assignee, state, labels, or project |
| `linear_issue_add_comment` | Add a comment to a Linear issue |
| `linear_project_create` | Create a Linear project |
| `linear_project_get` | Get a project with issue and milestone details |
| `linear_project_update` | Update an existing project |
| `linear_project_list` | List projects with optional team or state filters |
| `linear_teams_list` | List teams in the workspace |
| `linear_team_get` | Get team details, members, labels, and workflow metadata |
| `linear_workflow_states_get` | List workflow states for a team |
| `linear_label_create` | Create a new team label |
| `linear_labels_list` | List labels, optionally filtered by team |
| `linear_users_list` | List users in the workspace |
| `linear_user_get` | Get a user and their assigned issues |
| `linear_viewer` | Get the authenticated Linear user |
| `linear_cycles_list` | List cycles for a team |
| `linear_issue_comments_list` | List comments on an issue |
| `linear_issue_relation_create` | Create a relation between two issues |

## Usage

### Create an issue

```python
result = linear_issue_create(
    title="Add retry logic to worker executor",
    team_id="team_uuid",
    description="Retries should respect failure budgets.",
    priority=2,
)
```

### Search issues

```python
result = linear_issue_search(
    query="retry",
    team_id="team_uuid",
    limit=10,
)
```

### Inspect your Linear identity

```python
result = linear_viewer()
```

## Scope

- Issue CRUD, search, comments, and issue relationships
- Project creation, retrieval, updates, and listing
- Team, workflow state, label, user, and cycle discovery

## API Reference

- [Linear API Docs](https://linear.app/developers)
