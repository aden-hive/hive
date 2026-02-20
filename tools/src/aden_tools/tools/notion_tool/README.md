# Notion Tool

Interact with Notion databases and pages within the Aden agent framework.

## Installation

The Notion tool uses `httpx` which is already included in the base dependencies. No additional installation required.

## Setup

You need a Notion Integration Token to use this tool.

### Getting a Notion Token

1. Go to [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click "+ New integration"
3. Give your integration a name (e.g., "Aden Agent")
4. Select the workspace you want to use it in
5. Click "Submit" to create the integration
6. Copy the "Internal Integration Token" (starts with `secret_`)

**Important:** You must share specific databases or pages with your integration for it to access them. In Notion, go to the database/page, click "...", and select "Add connections".

### Configuration

Set the token as an environment variable:

```bash
export NOTION_TOKEN=secret_your_token_here
```

Or configure via the credential store.

## Available Functions

### `notion_search`

Search for pages, databases, or blocks.

**Parameters:**
- `query` (str, optional): The search text
- `filter_type` (str, optional): Filter by object type ("page" or "database")
- `limit` (int, optional): Maximum number of results (1-100, default 30)

### `notion_get_database`

Retrieve a database's schema and information.

**Parameters:**
- `database_id` (str): The ID of the database to retrieve

### `notion_query_database`

Query a database for specific pages based on filters.

**Parameters:**
- `database_id` (str): The ID of the database to query
- `filter_params` (dict, optional): Notion filter object
- `limit` (int, optional): Maximum number of results

### `notion_create_database_page`

Create a new page in a Notion database.

**Parameters:**
- `database_id` (str): The ID of the parent database
- `properties` (dict): Properties for the new page (must match database schema)
- `content` (list[dict], optional): Optional blocks representing the page content

### `notion_get_page_content`

Retrieve the content (blocks) of a Notion page.

**Parameters:**
- `page_id` (str): The ID of the page to retrieve content from
- `limit` (int, optional): Maximum number of blocks to return

### `notion_update_page`

Update the properties of an existing Notion page.

**Parameters:**
- `page_id` (str): The ID of the page to update
- `properties` (dict): The new properties for the page
