# Notion Tool

<!-- One-liner: what this tool does and what it enables agents to do. -->

Notion Tool enables agents to interact with Notion workspaces via the Notion API. Agents can search pages and databases, retrieve page content, create new pages, query databases, and manage existing pages.

## Setup

```bash
# Required
export NOTION_API_TOKEN=your-notion-integration-token
```

**Get your key:**
1. Go to https://www.notion.so/my-integrations
2. Click "New integration"
3. Give it a name (e.g., "Agent Tool")
4. Copy the "Internal Integration Token"
5. Set `NOTION_API_TOKEN` environment variable

**Share with Integration:**
After creating the token, go to your Notion page or database → Click "..." → "Connect to" → Select your integration.

Alternatively, configure via the credential store (`CredentialStoreAdapter`).

## Tools (8)

| Tool | Description |
|------|-------------|
| `notion_search` | Search pages and databases by query |
| `notion_get_page` | Retrieve a page by ID |
| `notion_create_page` | Create a new page in a database |
| `notion_query_database` | Query a database with optional filters |
| `notion_get_database` | Retrieve a database schema by ID |
| `notion_update_page` | Update properties on an existing page |
| `notion_archive_page` | Archive or unarchive a page |
| `notion_append_blocks` | Append content blocks to a page |

## Usage

### Search Notion

```python
result = notion_search(
    query="project notes",
    filter_type="page",
    page_size=20,
)
# Returns: {"results": [...], "count": 5, "has_more": False}
```

### Get a Page

```python
result = notion_get_page(
    page_id="your-page-id-here",
)
# Returns: {"id": "...", "title": "...", "url": "...", "properties": {...}}
```

### Create a Page

```python
result = notion_create_page(
    parent_database_id="your-database-id",
    title="New Project Page",
    properties_json='{"Status": {"select": {"name": "In Progress"}}}',
    content="Initial project notes here",
)
# Returns: {"id": "...", "url": "...", "status": "created"}
```

### Query a Database

```python
result = notion_query_database(
    database_id="your-database-id",
    filter_json='{"property": "Status", "select": {"equals": "Done"}}',
    page_size=50,
)
# Returns: {"pages": [...], "count": 10, "has_more": False}
```

### Get Database Schema

```python
result = notion_get_database(
    database_id="your-database-id",
)
# Returns: {"id": "...", "title": "...", "properties": {...}}
```

### Update a Page

```python
result = notion_update_page(
    page_id="your-page-id",
    properties_json='{"Status": {"select": {"name": "Done"}}',
)
# Returns: {"id": "...", "url": "...", "status": "updated"}
```

### Archive a Page

```python
result = notion_archive_page(
    page_id="your-page-id",
    archived=True,
)
# Returns: {"id": "...", "archived": True, "status": "archived"}
```

### Append Content to a Page

```python
result = notion_append_blocks(
    page_id="your-page-id",
    content="This is a new paragraph.\nThis is another line.",
    block_type="paragraph",
)
# Returns: {"page_id": "...", "blocks_added": 2, "status": "appended"}
```

## Scope

- Full CRUD operations for Notion pages and databases
- Search across workspace content
- Database querying with filters
- Page content manipulation via blocks
- Archive/restore functionality

## Rate Limits

| Tier | Limit |
|------|-------|
| Free | 3 requests/second |
| Paid | 90 requests/second |

## API Reference

- [Notion API Docs](https://developers.notion.com/reference)
- [Notion SDKs](https://developers.notion.com/reference/sdks)
