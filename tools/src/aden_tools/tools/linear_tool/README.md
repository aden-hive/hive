# Linear Tool

Manage issues, projects, teams, and workflows via the Linear GraphQL API.

## Supported Actions

### Issues
- **linear_issue_create** / **linear_issue_get** / **linear_issue_update** / **linear_issue_delete**
- **linear_issue_search** – Full-text search across issues
- **linear_issue_add_comment** / **linear_issue_comments_list**
- **linear_issue_relation_create** – Link related issues

### Projects & Teams
- **linear_project_create** / **linear_project_get** / **linear_project_update** / **linear_project_list**
- **linear_teams_list** / **linear_team_get**

### Workflow & Organization
- **linear_workflow_states_get** – List workflow states for a team
- **linear_label_create** / **linear_labels_list**
- **linear_cycles_list** – List sprint cycles
- **linear_users_list** / **linear_user_get** / **linear_viewer** – User management

## Setup

1. Create a Personal API Key at [Linear Settings → API](https://linear.app/settings/api).

2. Set the environment variable:
   ```bash
   export LINEAR_API_KEY=lin_api_xxxxxxxxxxxx
   ```

## Use Case

Example: "Find all issues in the 'Backend' team that are blocked, add a comment asking for an update, and move any older than 7 days to the 'Needs Triage' state."
