# Asana Tool

This tool allows agents to interact with Asana for project management and task automation.

## Features

- **Task Management**: Create, update, search, complete, and delete tasks.
- **Project Management**: Create, update, list projects and tasks within them.
- **Team & Workspace**: manage workspaces, list team members.
- **Organization**: Sections, tags, and custom fields.

## Setup

The tool uses a Personal Access Token (PAT) for authentication.

1. Generate a PAT at [https://app.asana.com/0/my-apps](https://app.asana.com/0/my-apps) -> "Manage Developer Apps" -> "Personal Access Tokens".
2. Set the environment variable `ASANA_ACCESS_TOKEN`.
3. Optionally set `ASANA_WORKSPACE_ID` to avoid specifying it in every call.

## Usage

### Create a Task

```python
result = asana_create_task(
    name="Fix login bug",
    notes="Users are getting 500 error on login",
    due_on="2026-02-15",
    assignee="me@example.com"
)
```

### Create a Project

```python
result = asana_create_project(
    name="Q1 Goals",
    notes="Objectives for this quarter",
    public=True
)
```

### Search Tasks

```python
tasks = asana_search_tasks(
    text="login",
    completed=False
)
```

## Tools

- `asana_create_task`
- `asana_update_task`
- `asana_get_task`
- `asana_search_tasks`
- `asana_delete_task`
- `asana_add_task_comment`
- `asana_complete_task`
- `asana_add_subtask`
- `asana_create_project`
- `asana_update_project`
- `asana_get_project`
- `asana_list_projects`
- `asana_get_project_tasks`
- `asana_add_task_to_project`
- `asana_get_workspace`
- `asana_list_workspaces`
- `asana_get_user`
- `asana_list_team_members`
- `asana_create_section`
- `asana_list_sections`
- `asana_move_task_to_section`
- `asana_create_tag`
- `asana_add_tag_to_task`
- `asana_list_tags`
- `asana_update_custom_field`
