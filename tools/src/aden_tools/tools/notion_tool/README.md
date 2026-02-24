# Notion Tool

Integration with Notion for workspace management, page creation, database queries, and content automation.

## Overview

This tool enables Hive agents to interact with Notion's workspace API for:
- Creating, reading, updating, and archiving pages
- Querying and managing databases
- Reading and appending block content
- Searching across the workspace
- Listing workspace users
- Creating and listing comments

## Available Tools

This integration provides 17 MCP tools for comprehensive workspace operations:

**Pages**
- `notion_create_page` - Create a new page in a database or as a child of another page
- `notion_get_page` - Retrieve a page by ID
- `notion_update_page` - Update page properties, icon, cover, or archive status
- `notion_archive_page` - Archive (soft-delete) a page

**Databases**
- `notion_query_database` - Query a database with filters and sorting
- `notion_get_database` - Retrieve a database schema and metadata
- `notion_create_database` - Create a new database as a child of a page
- `notion_update_database` - Update a database title or property schema

**Blocks**
- `notion_get_block` - Retrieve a single block by ID
- `notion_get_block_children` - Retrieve content blocks (children) of a page or block
- `notion_append_block_children` - Append content blocks to a page or block
- `notion_delete_block` - Delete (archive) a block

**Search**
- `notion_search` - Search across all pages and databases in the workspace

**Users**
- `notion_list_users` - List all users in the workspace
- `notion_get_user` - Retrieve a user by ID

**Comments**
- `notion_create_comment` - Add a comment to a page or reply to a discussion
- `notion_list_comments` - List comments on a page or block

## Setup

### 1. Create a Notion Integration

1. Go to [My Integrations](https://www.notion.so/my-integrations)
2. Click **"New integration"**
3. Give it a name (e.g., "Hive Agent")
4. Select the workspace to connect
5. Copy the **Internal Integration Secret** (starts with `ntn_` or `secret_`)

### 2. Share Pages with the Integration

Notion integrations can only access pages they've been explicitly shared with:

1. Open a Notion page or database
2. Click **"..."** in the top-right corner
3. Select **"Add connections"**
4. Find and select your integration

### 3. Configure Environment Variables
```bash
export NOTION_API_KEY="ntn_your_integration_secret"
```

## Usage

### notion_search
```python
notion_search(query="Meeting Notes", filter_object="page")
```

### notion_query_database
```python
notion_query_database(
    database_id="abc123def456...",
    filter={"property": "Status", "select": {"equals": "In Progress"}},
    sorts=[{"property": "Due Date", "direction": "ascending"}]
)
```

### notion_create_page
```python
# Create a page in a database
notion_create_page(
    parent_type="database_id",
    parent_id="abc123def456...",
    properties={"Name": {"title": [{"text": {"content": "New Task"}}]}}
)

# Create a sub-page under an existing page
notion_create_page(
    parent_type="page_id",
    parent_id="abc123def456...",
    properties={"title": {"title": [{"text": {"content": "Sub Page"}}]}}
)
```

### notion_update_page
```python
notion_update_page(
    "abc123def456...",
    properties={"Status": {"select": {"name": "Done"}}}
)
```

### notion_append_block_children
```python
notion_append_block_children(
    "abc123def456...",
    children=[
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Section Title"}}]
            }
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": "Paragraph content here."}}]
            }
        }
    ]
)
```

### notion_create_comment
```python
notion_create_comment("abc123def456...", text="Looks good, approved!")
```

## Authentication

Notion uses Bearer token authentication. The tool passes your `NOTION_API_KEY` to all API requests via the `Authorization` header, along with the required `Notion-Version` header. A single `httpx.Client` instance is created per `_NotionClient` and reused across all calls.

## Error Handling

All tools return error dicts on failure so agents can handle errors without raising exceptions:
```json
{
  "error": "Notion API error (object_not_found): Could not find page with ID: abc123..."
}
```

Common errors:
- Invalid API key - check `NOTION_API_KEY` is set correctly
- Object not found - verify the ID exists and the integration has access
- Validation error - check property names and value formats match the schema
- Rate limit exceeded - reduce request frequency (Notion allows ~3 requests/second)

All IDs are validated as UUIDs before making API calls.

## Testing

Use a dedicated test workspace or test pages:
1. Create a Notion integration for testing
2. Share test pages/databases with the integration
3. Use the integration secret as `NOTION_API_KEY`

## API Reference

- [Notion API Docs](https://developers.notion.com/reference)
- [Authentication](https://developers.notion.com/docs/authorization)
- [Pages API](https://developers.notion.com/reference/page)
- [Databases API](https://developers.notion.com/reference/database)
- [Blocks API](https://developers.notion.com/reference/block)
- [Search API](https://developers.notion.com/reference/post-search)
- [Comments API](https://developers.notion.com/reference/create-a-comment)
