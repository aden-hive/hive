# Jira Tool

Issue tracking and project management via the Jira Cloud REST API v3.

## Supported Actions

- **jira_search_issues** – Search issues using JQL queries
- **jira_get_issue** / **jira_create_issue** / **jira_update_issue** – Issue CRUD
- **jira_list_projects** / **jira_get_project** – Browse projects
- **jira_add_comment** – Add comments to issues
- **jira_list_transitions** / **jira_transition_issue** – Move issues through workflow states

## Setup

1. Generate an API token at [Atlassian API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens).

2. Set the required environment variables:
   ```bash
   export JIRA_URL=https://your-domain.atlassian.net
   export JIRA_EMAIL=your-email@example.com
   export JIRA_API_TOKEN=your-api-token
   ```

## Use Case

Example: "Search for all P1 bugs assigned to me in the PLATFORM project and transition any that have a linked PR to 'In Review'."
