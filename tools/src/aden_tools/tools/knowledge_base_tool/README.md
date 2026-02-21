# Knowledge Base Tool

Access external knowledge bases, company wikis, and documentation portals in real-time.

## Overview

This tool enables Hive agents to search, retrieve, and use information from popular knowledge sources:

- **Confluence**: Search and retrieve content from Atlassian Confluence wikis
- **Notion**: Search and retrieve content from Notion workspaces  
- **Documentation Portals**: Crawl and search generic documentation websites

## Use Cases

- Look up company policies and procedures from internal wikis
- Search product documentation for technical specifications
- Retrieve information from knowledge bases during customer support workflows
- Access API documentation during development tasks
- Find answers from internal knowledge repositories

## Available Tools

### Confluence Tools

| Tool | Description |
|------|-------------|
| `confluence_search` | Search Confluence wiki using CQL |
| `confluence_get_page` | Retrieve a specific page by ID |

### Notion Tools

| Tool | Description |
|------|-------------|
| `notion_search` | Search Notion workspace for pages and databases |
| `notion_get_page` | Retrieve a specific page with content |

### Documentation Portal Tools

| Tool | Description |
|------|-------------|
| `docs_search` | Crawl and search a documentation website |
| `docs_get_page` | Retrieve content from a documentation page |

### Utility Tools

| Tool | Description |
|------|-------------|
| `knowledge_base_list_sources` | List available sources and their configuration status |

## Environment Variables

### Confluence

```bash
# Required for Confluence access
export CONFLUENCE_API_TOKEN="your-api-token"
export CONFLUENCE_URL="https://your-company.atlassian.net/wiki"
```

Get your API token from: https://id.atlassian.com/manage-profile/security/api-tokens

### Notion

```bash
# Required for Notion access
export NOTION_API_KEY="your-integration-token"
```

Create an integration at: https://www.notion.so/my-integrations

## Usage Examples

### Search Confluence

```json
{
  "query": "vacation policy",
  "limit": 10,
  "space_key": "HR"
}
```

### Get Confluence Page

```json
{
  "page_id": "123456789",
  "include_attachments": true
}
```

### Search Notion

```json
{
  "query": "project roadmap",
  "filter_type": "page",
  "page_size": 10
}
```

### Search Documentation Portal

```json
{
  "base_url": "https://docs.python.org/3/",
  "query": "async await",
  "search_paths": ["/reference/", "/tutorial/"],
  "max_pages": 20
}
```

## Response Format

All tools return structured responses:

### Successful Response

```json
{
  "query": "search query",
  "source": "confluence|notion|url",
  "results": [
    {
      "title": "Page Title",
      "url": "https://...",
      "excerpt": "Matching content preview...",
      "relevance_score": 5
    }
  ],
  "total": 1
}
```

### Error Response

```json
{
  "error": "Description of the error",
  "help": "Instructions for resolving the error"
}
```

## Error Handling

The tool returns helpful error messages when:

- Credentials are missing or invalid
- Resources are not found
- Rate limits are exceeded
- Network errors occur

Always check for the `"error"` key in responses before processing results.

## Best Practices

1. **Use specific queries**: Narrow searches with space keys, content types, or paths
2. **Limit results**: Use appropriate `limit`/`page_size` parameters to avoid large responses
3. **Cache when possible**: For frequently accessed content, consider caching results
4. **Handle pagination**: For large result sets, use pagination parameters

## Rate Limits

| Source | Notes |
|--------|-------|
| Confluence | Rate limits vary by plan; retry logic included |
| Notion | 3 requests/second; pagination supported |
| Documentation | Respect site-specific rate limits |

## Security Notes

- API tokens are read from environment variables, never logged
- Only publicly accessible documentation portals can be crawled
- Confluence/Notion access requires proper authentication setup
