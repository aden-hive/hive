# Todoist Tool

Manage tasks and projects using the Todoist API.

## Features

- List, create, update, and delete tasks
- Complete tasks
- List and create projects
- Filter tasks by project, label, or custom filters
- Set due dates, priorities, and labels
- Support for natural language due dates

## Setup

### 1. Get Your API Token

1. Go to [Todoist Settings > Integrations > Developer](https://todoist.com/app/settings/integrations/developer)
2. Scroll to the "API token" section
3. Copy your API token

### 2. Configure Credentials

Set the environment variable:

```bash
export TODOIST_API_KEY=your-api-token-here
```

Or configure via Hive's credential store (recommended for production).

## Available Tools

### Task Management

#### `todoist_list_tasks`
List all active tasks with optional filtering.

**Parameters:**
- `project_id` (optional): Filter by project ID
- `label` (optional): Filter by label name
- `filter_query` (optional): Use Todoist filter syntax (e.g., "today | overdue")

**Example:**
```python
# List all tasks
todoist_list_tasks()

# List tasks for a specific project
todoist_list_tasks(project_id="2203306141")

# List tasks due today or overdue
todoist_list_tasks(filter_query="today | overdue")
```

#### `todoist_get_task`
Get details of a specific task.

**Parameters:**
- `task_id` (required): Task ID

**Example:**
```python
todoist_get_task(task_id="7654321")
```

#### `todoist_create_task`
Create a new task.

**Parameters:**
- `content` (required): Task title/content
- `description` (optional): Task description
- `project_id` (optional): Project ID to add task to
- `due_string` (optional): Natural language due date (e.g., "tomorrow", "next Monday at 3pm")
- `due_date` (optional): Due date in YYYY-MM-DD format
- `priority` (optional): Priority from 1 (normal) to 4 (urgent), default 1
- `labels` (optional): List of label names

**Example:**
```python
# Simple task
todoist_create_task(content="Buy groceries")

# Task with details
todoist_create_task(
    content="Finish project report",
    description="Include Q1 metrics and analysis",
    due_string="next Friday",
    priority=3,
    labels=["work", "urgent"]
)
```

#### `todoist_update_task`
Update an existing task.

**Parameters:**
- `task_id` (required): Task ID
- `content` (optional): New task title
- `description` (optional): New description
- `due_string` (optional): New natural language due date
- `due_date` (optional): New due date in YYYY-MM-DD format
- `priority` (optional): New priority (1-4)
- `labels` (optional): New list of labels

**Example:**
```python
todoist_update_task(
    task_id="7654321",
    priority=4,
    due_string="today"
)
```

#### `todoist_complete_task`
Mark a task as complete.

**Parameters:**
- `task_id` (required): Task ID

**Example:**
```python
todoist_complete_task(task_id="7654321")
```

#### `todoist_delete_task`
Delete a task permanently.

**Parameters:**
- `task_id` (required): Task ID

**Example:**
```python
todoist_delete_task(task_id="7654321")
```

### Project Management

#### `todoist_list_projects`
List all projects.

**Example:**
```python
todoist_list_projects()
```

#### `todoist_create_project`
Create a new project.

**Parameters:**
- `name` (required): Project name
- `color` (optional): Project color (e.g., "red", "blue", "green")
- `is_favorite` (optional): Mark as favorite, default False

**Example:**
```python
todoist_create_project(
    name="Work Projects",
    color="blue",
    is_favorite=True
)
```

## API Details

- **Base URL**: `https://api.todoist.com/api/v1`
- **Authentication**: Bearer token
- **Rate Limits**: 450 requests per 15 minutes
- **Documentation**: https://developer.todoist.com/api/v1/

## Priority Levels

Todoist uses priority levels 1-4:
- `1`: Normal (default)
- `2`: Medium
- `3`: High
- `4`: Urgent

## Natural Language Due Dates

The `due_string` parameter supports natural language:
- "today"
- "tomorrow"
- "next Monday"
- "in 3 days"
- "every day" (for recurring tasks)
- "every Monday at 9am"

## Filter Syntax

The `filter_query` parameter supports Todoist's filter syntax:
- `today` - Tasks due today
- `overdue` - Overdue tasks
- `p1` - Priority 1 tasks
- `@label` - Tasks with specific label
- `#project` - Tasks in specific project
- `today | overdue` - Combine with OR
- `today & p1` - Combine with AND

Examples:
```python
# High priority tasks due today
todoist_list_tasks(filter_query="today & p3")

# All urgent tasks
todoist_list_tasks(filter_query="p4")

# Tasks with work label
todoist_list_tasks(filter_query="@work")
```

## Error Handling

All tools return a dict with either:
- Success: `{"success": True, ...}`
- Error: `{"error": "error message"}`

Common errors:
- Missing credentials: `"Todoist credentials not configured"`
- Rate limit: `"Todoist rate limit exceeded"`
- Network issues: `"Request timed out"` or `"Network error: ..."`
- Invalid task/project: `"HTTP 404: ..."`

## Testing

Run tests:
```bash
cd tools
uv run pytest tests/tools/test_todoist_tool.py -v
```

## Use Cases

1. **Email to Task**: Extract action items from emails and create tasks
2. **Meeting Follow-ups**: Create follow-up tasks after meetings
3. **Content Pipeline**: Track content creation workflow
4. **Job Applications**: Track applications and follow-ups
5. **Learning Goals**: Manage learning resources and progress
6. **Personal CRM**: Track relationship follow-ups

## Notes

- Task IDs and Project IDs are strings, not integers
- Completed tasks are not returned by `list_tasks` (use filter_query for completed tasks)
- Labels must already exist in your Todoist account
- Colors must be valid Todoist color names
- The API uses Unified API v1 (launched 2024, base URL: `https://api.todoist.com/api/v1/`)
