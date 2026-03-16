# Notion Tool

Manage Notion pages and databases via the Notion API (search, read pages/databases, create/update/archive pages, append blocks).

## Setup

```bash
export NOTION_API_TOKEN=secret_your_integration_token
```

**Get your token:**
1. Create an internal integration: `https://www.notion.so/my-integrations`
2. Copy the integration token
3. Share the target page/database with the integration (otherwise Notion returns 403/404)

Alternatively, configure credentials via the Aden credential store using the key `notion_token`.

## Tools (8)

| Tool | Description |
|------|-------------|
| `notion_search` | Search pages/databases by title text |
| `notion_get_page` | Fetch a page by ID (returns simplified properties + title) |
| `notion_create_page` | Create a page in a database |
| `notion_update_page` | Update an existing page (properties/title) |
| `notion_archive_page` | Archive (soft-delete) a page |
| `notion_append_blocks` | Append text blocks to a page |
| `notion_get_database` | Fetch a database by ID |
| `notion_query_database` | Query a database with filters/sorts |

## Usage

### Search

```python
result = notion_search(query="runbook", filter_type="page", page_size=10)
```

### Create a page in a database

```python
result = notion_create_page(
    parent_database_id="database_id",
    title="Incident Review",
    properties_json='{"Status": {"select": {"name": "Todo"}}}',
    content="Notes:\n- Timeline\n- Root cause\n",
)
```

### Query a database

```python
result = notion_query_database(
    database_id="database_id",
    filter_json='{"property":"Status","status":{"equals":"Todo"}}',
    page_size=20,
)
```

## API Reference

- Notion API docs: `https://developers.notion.com/reference`

