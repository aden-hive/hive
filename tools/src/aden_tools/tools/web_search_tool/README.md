# Web Search Tool

Search the web using multiple providers with automatic detection.

## Description

Returns titles, URLs, and snippets for search results. Use when you need current information, research topics, or find websites.

Supports multiple search providers:
- **Brave Search API** (default, for backward compatibility)
- **Google Custom Search API** (fallback)

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `query` | str | Yes | - | The search query (1-500 chars) |
| `num_results` | int | No | `10` | Number of results (1-10 for Google, 1-20 for Brave) |
| `country` | str | No | `us` | Country code for localized results |
| `language` | str | No | `en` | Language code (Google only) |
| `provider` | str | No | `auto` | Provider: "auto", "google", or "brave" |

## Environment Variables

Set credentials for at least one provider:

### Option 1: Google Custom Search
| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | Yes | API key from [Google Cloud Console](https://console.cloud.google.com/) |
| `GOOGLE_CSE_ID` | Yes | Search Engine ID from [Programmable Search Engine](https://programmablesearchengine.google.com/) |

### Option 2: Brave Search
| Variable | Required | Description |
|----------|----------|-------------|
| `BRAVE_SEARCH_API_KEY` | Yes | API key from [Brave Search API](https://brave.com/search/api/) |

## Provider Selection

- `provider="auto"` (default): Uses Brave if available, otherwise Google (backward compatible)
- `provider="brave"`: Force Brave Search
- `provider="google"`: Force Google Custom Search

## Example Usage

```python
# Auto-detect provider based on available credentials
result = web_search(query="climate change effects")

# Force specific provider
result = web_search(query="python tutorial", provider="google")
result = web_search(query="local news", provider="brave", country="id")
```

## Error Handling

Returns error dicts for common issues:
- `No search credentials configured` - No API keys set
- `Google credentials not configured` - Missing Google keys when provider="google"
- `Brave credentials not configured` - Missing Brave key when provider="brave"
- `Query must be 1-500 characters` - Empty or too long query
- `Invalid API key` - API key rejected
- `Rate limit exceeded` - Too many requests
- `Search request timed out` - Request exceeded 30s timeout
