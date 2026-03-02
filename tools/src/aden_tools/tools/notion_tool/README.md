# Notion Tool

Read, write, search and manage Notion pages and databases.

## Setup

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Create a new integration → copy the **Internal Integration Token**
3. Share your pages/databases with the integration (... → Connections → your integration)
4. Set the environment variable:
```bash
export NOTION_API_KEY=secret_your_token_here
```

## Tools

| Tool | Description |
|------|-------------|
| `notion_search` | Search pages/databases by keyword |
| `notion_read_page` | Read full page content as plain text |
| `notion_create_page` | Create a new page in a parent page or database |
| `notion_append_to_page` | Append paragraphs, headings, to-dos, bullets |
| `notion_query_database` | List all entries in a Notion database |

## Finding Page/Database IDs

Copy the URL of any Notion page — the ID is the 32-char string at the end:
```
https://notion.so/My-Page-abc123def456...
                          ^^^^^^^^^^^^^^^^  ← page_id
```
