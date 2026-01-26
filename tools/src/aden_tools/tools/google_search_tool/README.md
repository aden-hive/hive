# Google Search Tool

Search the web using the Google Custom Search API.

## Description

Returns titles, URLs, and snippets for search results. Use when you need current information, research topics, or find websites. Optimized for Indonesian market searches.

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `query` | str | Yes | - | The search query (1-500 chars) |
| `num_results` | int | No | `10` | Number of results to return (1-10) |
| `language` | str | No | `id` | Language code (id=Indonesian, en=English) |
| `country` | str | No | `id` | Country code for localized results |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | Yes | API key from [Google Cloud Console](https://console.cloud.google.com/) |
| `GOOGLE_CSE_ID` | Yes | Search Engine ID from [Programmable Search Engine](https://programmablesearchengine.google.com/) |

## Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable "Custom Search API"
3. Create an API key
4. Go to [Programmable Search Engine](https://programmablesearchengine.google.com/)
5. Create a search engine (select "Search the entire web")
6. Copy the Search Engine ID

## Error Handling

Returns error dicts for common issues:
- `GOOGLE_API_KEY environment variable not set` - Missing API key
- `GOOGLE_CSE_ID environment variable not set` - Missing CSE ID
- `Query must be 1-500 characters` - Empty or too long query
- `Invalid API key` - API key rejected (HTTP 401)
- `API key not authorized or quota exceeded` - Permissions issue (HTTP 403)
- `Rate limit exceeded. Try again later.` - Too many requests (HTTP 429)
- `Search request timed out` - Request exceeded 30s timeout
