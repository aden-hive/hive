# Attio Tool

CRM integration for Attio via the V2 REST API.

## Authentication

Set your Attio API key:

```bash
export ATTIO_API_KEY="your_api_key_here"
```

Get an API key at: https://attio.com/help/apps/other-apps/generating-an-api-key

### Required Scopes

- `record_permission:read-write`
- `object_configuration:read`
- `list_entry:read-write`
- `list_configuration:read`
- `task:read-write`
- `user_management:read`

## Tools

### Records (5 tools)

| Tool | Description |
|------|-------------|
| `attio_record_list` | List/filter records within an object (people, companies, etc.) |
| `attio_record_get` | Get a specific record by ID |
| `attio_record_create` | Create a new record |
| `attio_record_update` | Update an existing record (appends multiselect values) |
| `attio_record_assert` | Upsert a record by matching attribute |

### Lists (4 tools)

| Tool | Description |
|------|-------------|
| `attio_list_lists` | List all lists in the workspace |
| `attio_list_entries_get` | List entries in a specific list |
| `attio_list_entry_create` | Add a record to a list |
| `attio_list_entry_delete` | Remove an entry from a list |

### Tasks (4 tools)

| Tool | Description |
|------|-------------|
| `attio_task_create` | Create a task linked to records |
| `attio_task_list` | List all tasks |
| `attio_task_get` | Get a task by ID |
| `attio_task_delete` | Delete a task |

### Workspace Members (2 tools)

| Tool | Description |
|------|-------------|
| `attio_members_list` | List all workspace members |
| `attio_member_get` | Get a member by ID |

## API Reference

Base URL: `https://api.attio.com/v2`

Documentation: https://developers.attio.com/reference
