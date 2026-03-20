# Notion Tool

Search pages, retrieve and update page content, create pages, manage databases, and manipulate blocks via the Notion API.

## Setup

```bash
# Required - Internal Integration Token
export NOTION_API_TOKEN=your-notion-integration-token
```

**Get your token:**
1. Go to https://www.notion.so/my-integrations
2. Click "New integration" and give it a name
3. Copy the "Internal Integration Secret"
4. Set `NOTION_API_TOKEN` environment variable

**Important:** You must share each page or database with your integration. Open the page in Notion, click the `...` menu, select "Connections", and add your integration.

Alternatively, configure via the credential store (`CredentialStoreAdapter`) using the key `notion_token`.

## Tools (13)

| Tool | Description |
|------|-------------|
| `notion_search` | Search Notion pages and databases by title |
| `notion_get_page` | Get a page by ID with simplified properties |
| `notion_create_page` | Create a new page in a database |
| `notion_update_page` | Update a page's properties or archive/unarchive it |
| `notion_query_database` | Query rows/pages from a database with filters, sorts, and pagination |
| `notion_get_database` | Get a database schema (property names and types) |
| `notion_create_database` | Create a new database as a child of a page |
| `notion_update_database` | Update a database's title, properties, or archive it |
| `notion_get_block_children` | Get child blocks (content) of a page or block |
| `notion_get_block` | Retrieve a single block by ID |
| `notion_update_block` | Update a block's content or archive it |
| `notion_delete_block` | Delete a block (moves to trash) |
| `notion_append_blocks` | Append content blocks (paragraphs, headings, lists, todos, quotes) to a page or block |

## Usage

### Search pages and databases

```python
# Search by title text
result = notion_search(query="Meeting Notes")

# Filter to only databases
result = notion_search(query="Tasks", filter_type="database")

# List all accessible pages (empty query)
result = notion_search(page_size=50)
```

### Get a page

```python
# Retrieve page details with simplified properties
result = notion_get_page(page_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890")
# Returns id, title, url, properties (title, rich_text, select, multi_select,
# number, checkbox, date, status)
```

### Create a page

When creating a page in a database, you must provide `title_property` (the
name of the database's title column). Use `notion_get_database` to find it
first. The `title_property` parameter is ignored when using `parent_page_id`.

```python
# Step 1: Find the database's title property name
schema = notion_get_database(database_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890")
# schema["properties"] -> {"Task name": {"type": "title"}, "Status": {"type": "status"}, ...}

# Step 2: Create a page using the correct title property
result = notion_create_page(
    title="Weekly Standup Notes",
    parent_database_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    title_property="Task name",
)

# Create with additional properties and body content
result = notion_create_page(
    title="Bug Report: Login Timeout",
    parent_database_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    title_property="Task name",
    properties_json='{"Status": {"select": {"name": "Open"}}}',
    content="Users are experiencing timeouts when logging in during peak hours.",
)

# Create a page as a child of another page (no title_property needed)
result = notion_create_page(
    title="Meeting Notes - March 10",
    parent_page_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    content="Discussion points and action items.",
)
```

### Update a page

```python
# Update properties
result = notion_update_page(
    page_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    properties_json='{"Status": {"select": {"name": "Done"}}}'
)

# Archive a page
result = notion_update_page(
    page_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    archived=True
)
```

### Query a database

```python
# Get all rows from a database
result = notion_query_database(
    database_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890"
)

# Query with a filter
result = notion_query_database(
    database_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    filter_json='{"property": "Status", "select": {"equals": "In Progress"}}',
    page_size=25
)

# Sort results
result = notion_query_database(
    database_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    sorts_json='[{"property": "Created", "direction": "descending"}]'
)

# Paginate through results
result = notion_query_database(
    database_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    start_cursor=previous_result["next_cursor"]
)
```

### Get a database schema

```python
# Retrieve property names and types for a database
result = notion_get_database(
    database_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890"
)
# Returns id, title, url, properties (each with type and id)
```

### Create a database

```python
# Create a database with default Name column
result = notion_create_database(
    parent_page_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    title="Project Tasks"
)

# Create with custom columns
result = notion_create_database(
    parent_page_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    title="Bug Tracker",
    properties_json='{"Status": {"select": {"options": [{"name": "Open"}, {"name": "Closed"}]}}, "Priority": {"number": {}}}'
)
```

### Update or delete a database

```python
# Rename a database
result = notion_update_database(
    database_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    title="Renamed Database"
)

# Add a new column
result = notion_update_database(
    database_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    properties_json='{"Priority": {"number": {}}}'
)

# Archive (delete) a database
result = notion_update_database(
    database_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    archived=True
)
```

### Read page content (block tree)

```python
# Get the body content (blocks) of a page
result = notion_get_block_children(
    block_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890"
)
# Returns blocks with type, text content, and has_children indicator
```

### Get, update, or delete a block

```python
# Get a single block
result = notion_get_block(block_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890")
# Returns id, type, text, has_children, archived

# Update block content (must specify the block's type)
result = notion_update_block(
    block_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    content="Updated paragraph text",
    block_type="paragraph"
)

# Archive a block (soft-delete)
result = notion_update_block(
    block_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    archived=True
)

# Delete a block (moves to trash)
result = notion_delete_block(block_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890")
```

### Append content to a page

```python
# Add paragraphs to a page (newlines create separate blocks)
result = notion_append_blocks(
    block_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    content="First paragraph\nSecond paragraph"
)

# Add a heading
result = notion_append_blocks(
    block_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    content="Section Title",
    block_type="heading_1"
)

# Add a to-do list
result = notion_append_blocks(
    block_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    content="Buy groceries\nClean the house\nWalk the dog",
    block_type="to_do"
)

# Supported block types: paragraph, heading_1, heading_2, heading_3,
# bulleted_list_item, numbered_list_item, to_do, quote, callout
# Max 100 blocks per request
```

## Error Handling

| Error | Cause |
|-------|-------|
| `Unauthorized` | Invalid or missing integration token |
| `Forbidden` | Page/database not shared with the integration |
| `Not found` | Page/database does not exist or is not shared |
| `Rate limited` | Too many requests, retry after a short wait |
| `Request timed out` | Request exceeded the 30-second timeout |

## Rate Limits

The Notion API enforces rate limits of approximately 3 requests per second per integration. When rate limited, the tool returns `{"error": "Rate limited. Try again shortly."}`. Callers should wait a few seconds before retrying.

## API Reference

- [Notion API Docs](https://developers.notion.com/reference)
