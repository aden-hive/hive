# Web Search Tool

Search the web using the Brave Search API.

## Description

Returns titles, URLs, and snippets for search results. Use when you need current information, research topics, or find websites.

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `query` | str | Yes | - | The search query (1-500 chars) |
| `num_results` | int | No | `10` | Number of results to return (1-20) |
| `country` | str | No | `us` | Country code for localized results (us, uk, de, etc.) |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BRAVE_SEARCH_API_KEY` | Yes | API key from [Brave Search API](https://brave.com/search/api/) |

## Error Handling

Returns error dicts for common issues:
- `BRAVE_SEARCH_API_KEY environment variable not set` - Missing API key
- `Query must be 1-500 characters` - Empty or too long query
- `Invalid API key` - API key rejected (HTTP 401)
- `Rate limit exceeded. Try again later.` - Too many requests (HTTP 429)
- `Search request timed out` - Request exceeded 30s timeout
- `Network error: <error>` - Connection or DNS issues
