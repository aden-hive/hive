# GitLab Tool

Manage projects, issues, and merge requests via the GitLab REST API v4. Supports both GitLab.com and self-hosted instances.

## Supported Actions

### Projects
- **gitlab_list_projects** / **gitlab_get_project** – Browse and inspect projects

### Issues
- **gitlab_list_issues** / **gitlab_get_issue** / **gitlab_create_issue** / **gitlab_update_issue** – Issue CRUD with filtering

### Merge Requests
- **gitlab_list_merge_requests** / **gitlab_get_merge_request** – Browse MRs
- **gitlab_create_merge_request_note** – Add comments to merge requests

## Setup

1. Create a Personal Access Token at GitLab (Settings → Access Tokens) with `api` scope.

2. Set the required environment variables:
   ```bash
   export GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
   export GITLAB_URL=https://gitlab.com   # or your self-hosted instance
   ```

## Use Case

Example: "List all open merge requests in the platform project that have been waiting for review for more than 3 days and add a comment requesting an update."
