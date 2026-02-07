# Notion Tool

A tool for interacting with Notion workspaces - search, read, create, and update pages and databases.

## Features

- 🔍 Search pages and databases
- 📄 Retrieve page content and metadata
- ✍️ Create new pages (in pages or databases)
- ➕ Append content to existing pages

## Prerequisites

- A Notion Integration Token (API Key)
- The Integration must be shared with the specific pages/databases you want to access

## Configuration

### Getting a Notion Integration Token

1. Go to [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **"+ New integration"**
3. Give your integration a name (e.g., "Hive Agent")
4. Select the workspace where you want to use the integration
5. Click **"Submit"** to create the integration
6. Copy the **"Internal Integration Token"** (starts with `secret_`)

### Sharing Pages with Your Integration

⚠️ **Important:** The integration can only access pages/databases that are explicitly shared with it.

To share a page:
1. Open the page/database in Notion
2. Click the **"..."** menu (top right)
3. Click **"Connections"** (or **"+ Add connections"**)
4. Search for your integration name and select it

### Setting the API Key

```bash
export NOTION_API_KEY=secret_your_token_here
```

Or add to your `.env` file:
```
NOTION_API_KEY=secret_your_token_here
```

## Available Tools

### `notion_search`

Search for pages or databases in your Notion workspace.

**Arguments:**
- `query` (str): Text to search for
- `filter_type` (str, optional): Filter by type - `"page"` or `"database"`
- `limit` (int, optional): Maximum number of results (default: 10)

**Returns:**
```json
{
  "results": [
    {
      "object": "page",
      "id": "page-uuid",
      "properties": {...}
    }
  ],
  "has_more": false
}
```

**Example:**
```python
result = notion_search(query="Project Ideas", filter_type="page", limit=5)
```

---

### `notion_get_page`

Get page metadata and content blocks.

**Arguments:**
- `page_id` (str): The UUID of the page

**Returns:**
```json
{
  "page": {
    "id": "page-uuid",
    "properties": {...},
    "url": "https://notion.so/..."
  },
  "content": {
    "results": [
      {
        "type": "paragraph",
        "paragraph": {...}
      }
    ]
  }
}
```

**Example:**
```python
result = notion_get_page(page_id="1930a805-ec0b-80f3-bbb7-c6c6734ef13d")
```

---

### `notion_create_page`

Create a new page inside a parent page or database.

**Arguments:**
- `parent_id` (str): UUID of the parent page or database
- `title` (str): Title of the new page
- `body` (str, optional): Text content (added as a paragraph block)
- `parent_type` (str, optional): `"page_id"` (default) or `"database_id"`

**Returns:**
```json
{
  "id": "new-page-uuid",
  "url": "https://notion.so/...",
  "properties": {...}
}
```

**Example:**
```python
# Create a page under another page
result = notion_create_page(
    parent_id="parent-page-uuid",
    title="New Project",
    body="This is the project description.",
    parent_type="page_id"
)

# Create an entry in a database
result = notion_create_page(
    parent_id="database-uuid",
    title="New Task",
    body="Task details here.",
    parent_type="database_id"
)
```

---

### `notion_append_text`

Append a text paragraph to the end of a page.

**Arguments:**
- `page_id` (str): UUID of the page/block to append to
- `text` (str): Content of the paragraph

**Returns:**
```json
{
  "results": [
    {
      "id": "block-uuid",
      "type": "paragraph",
      "paragraph": {...}
    }
  ]
}
```

**Example:**
```python
result = notion_append_text(
    page_id="page-uuid",
    text="Additional note added by the agent."
)
```

## Error Handling

All tools return error dictionaries when something goes wrong:

```json
{
  "error": "Error message",
  "help": "Optional guidance"
}
```

Common errors:
- **"Notion credentials not configured"**: API key not set
- **"Authentication error"**: Invalid or expired token
- **"Resource not found"**: Page/database doesn't exist or isn't shared with integration

## Usage in Agents

```python
from fastmcp import FastMCP
from aden_tools.tools.notion_tool import register_tools
from aden_tools.credentials import CredentialStoreAdapter

mcp = FastMCP("notion-agent")
credentials = CredentialStoreAdapter.default()
register_tools(mcp, credentials=credentials)

# Now you can use the tools
result = mcp._tool_manager._tools["notion_search"].fn(query="Meeting Notes")
```

## API Reference

Official Notion API Documentation: [https://developers.notion.com/reference](https://developers.notion.com/reference)

## Limitations

- Integration tokens can only access pages/databases explicitly shared with them
- Rate limits apply (currently 3 requests per second)
- Some advanced block types are not yet supported for creation
- Database properties are simplified (default "Name" field for database rows)

## Contributing

See the main [BUILDING_TOOLS.md](../../BUILDING_TOOLS.md) guide for information on contributing to Aden tools.

