# DuckDuckGo Tool

Search the web, news, and images through DuckDuckGo without requiring API credentials.

This integration wraps the `duckduckgo_search` Python package so agents can fetch public search results for lightweight research and discovery workflows.

## Setup

No API key is required.

The tool depends on the `duckduckgo_search` package that ships with the tools workspace. Once the Aden tools package is installed, the DuckDuckGo tools are ready to use.

## Tools (3)

| Tool | Description |
|------|-------------|
| `duckduckgo_search` | Search general web results and return titles, URLs, and snippets |
| `duckduckgo_news` | Search DuckDuckGo news results and return titles, source, date, URL, and snippet |
| `duckduckgo_images` | Search image results and return image URLs, thumbnails, source, and dimensions |

## Usage

### Web Search

```python
result = duckduckgo_search(
    query="latest AI agent frameworks",
    max_results=5,
    region="us-en",
    safesearch="moderate",
    timelimit="w",
)

# Returns:
# {
#   "query": "latest AI agent frameworks",
#   "results": [
#     {
#       "title": "...",
#       "url": "https://...",
#       "snippet": "..."
#     }
#   ],
#   "count": 5
# }
```

### News Search

```python
result = duckduckgo_news(
    query="OpenAI announcements",
    max_results=5,
    region="us-en",
    timelimit="d",
)
```

### Image Search

```python
result = duckduckgo_images(
    query="honey bee macro photo",
    max_results=8,
    region="us-en",
    safesearch="moderate",
    size="Large",
)
```

## Parameters

### `duckduckgo_search`

- `query`: Search query string. Required.
- `max_results`: Number of results to return. Clamped to `1-50`.
- `region`: Region code such as `us-en`, `uk-en`, or `de-de`.
- `safesearch`: One of `on`, `moderate`, or `off`.
- `timelimit`: Optional time filter: `d`, `w`, `m`, `y`, or empty for any time.

### `duckduckgo_news`

- `query`: News query string. Required.
- `max_results`: Number of results to return. Clamped to `1-50`.
- `region`: Region code such as `us-en`.
- `timelimit`: Optional time filter: `d`, `w`, `m`, or empty for any time.

### `duckduckgo_images`

- `query`: Image query string. Required.
- `max_results`: Number of results to return. Clamped to `1-50`.
- `region`: Region code such as `us-en`.
- `safesearch`: One of `on`, `moderate`, or `off`.
- `size`: Optional image size filter such as `Small`, `Medium`, `Large`, or `Wallpaper`.

## Error Handling

Each tool returns an error object instead of raising exceptions:

```python
{"error": "..."}
```

Common error cases:

- Missing `query`
- Temporary DuckDuckGo request failures
- Upstream library/runtime errors

## Scope

- Public web search without account setup
- News discovery with basic regional and time filtering
- Image lookup with safe search and size filtering

## API Reference

- [duckduckgo-search on PyPI](https://pypi.org/project/duckduckgo-search/)
