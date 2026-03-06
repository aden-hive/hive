# Notion Tool

A comprehensive tool for interacting with Notion pages, databases, and search via the Notion API.

## Features

- **Search:** Find pages and databases by title.
- **Pages:** Retrieve page details and properties.
- **Database Support:** Query database rows and retrieve database schemas.
- **Creation:** Create new pages in existing databases with custom properties and content.

## Setup

### 1. Create a Notion Integration

1. Go to [My Integrations](https://www.notion.so/my-integrations) in your Notion account.
2. Click **+ New integration**.
3. Give it a name and select the workspace you want to use it in.
4. Go to the **Capabilities** tab and ensure the integration has "Read content", "Update content", and "Insert content" permissions.
5. Copy the **Internal Integration Token**.

### 2. Share Pages/Databases with your Integration

By default, an integration doesn't have access to any pages or databases. You must explicitly share them:

1. Open the page or database in Notion.
2. Click the **...** menu in the top right corner.
3. Click **Add connections**.
4. Search for and select your integration.

### 3. Configure Environment Variables

Set the following environment variable:

```bash
export NOTION_API_TOKEN="ntn_..."
```

Alternatively, if you are using Aden Sync, ensure your Notion credential is connected.

## Available Tools

### `notion_search`
Search for Notion pages and databases that the integration has access to.
- **Arguments:**
  - `query` (optional): Search text to match against titles.
  - `filter_type` (optional): Filter by object type (`page` or `database`).
  - `page_size` (optional): Maximum number of results (default: 20, max: 100).

### `notion_get_page`
Retrieve detailed information about a specific Notion page.
- **Arguments:**
  - `page_id` (required): The unique ID of the Notion page.

### `notion_create_page`
Create a new page within a specified Notion database.
- **Arguments:**
  - `parent_database_id` (required): The ID of the database where the page will be created.
  - `title` (required): The title of the new page.
  - `properties_json` (optional): A JSON string representing additional properties (e.g., Select, Date, Checkbox).
  - `content` (optional): Plain text content for the page body.

### `notion_query_database`
Query rows/pages from a Notion database with optional filtering.
- **Arguments:**
  - `database_id` (required): The ID of the database to query.
  - `filter_json` (optional): A JSON string representing a Notion filter object.
  - `page_size` (optional): Maximum number of results (default: 50, max: 100).

### `notion_get_database`
Retrieve the schema and metadata of a Notion database.
- **Arguments:**
  - `database_id` (required): The unique ID of the Notion database.

## Example: Creating a Page with Properties

To create a page with custom properties, use `properties_json`:

```json
{
  "Status": { "status": { "name": "In progress" } },
  "Priority": { "select": { "name": "High" } }
}
```

Pass this as a string to the `properties_json` argument of `notion_create_page`.
