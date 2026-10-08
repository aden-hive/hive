# DuckDuckGo Tool

Search the web, news, and images using DuckDuckGo. No API key required.

## Tools

| Tool | Description |
|------|-------------|
| `duckduckgo_search` | Search the web for pages and results |
| `duckduckgo_news` | Search for recent news articles |
| `duckduckgo_images` | Search for images |

## Setup

No credentials required. DuckDuckGo searches are free and unauthenticated.

## Usage Examples

### Web search
```python
duckduckgo_search(query="python async best practices", max_results=5)
```

### Search with optional parameters
```python
duckduckgo_search(
    query="AI frameworks",
    max_results=10,
    region="us-en",
    safesearch="moderate",
    timelimit="m",  # past month
)
```

### News search
```python
duckduckgo_news(query="AI agents 2026", max_results=10, region="us-en")
```

### Image search
```python
duckduckgo_images(query="neural network diagram", max_results=5, size="Large")
```

## Optional Parameters

| Parameter | Tools | Description |
|-----------|-------|-------------|
| `region` | All | Region code (default: `us-en`) |
| `safesearch` | search, images | `off`, `moderate`, `strict` (default: `moderate`) |
| `timelimit` | search, news | `d` (day), `w` (week), `m` (month), `y` (year) |
| `size` | images | `Small`, `Medium`, `Large`, `Wallpaper` |

## Error Handling

All tools return error dicts on failure:
```python
{"error": "Search failed: connection timeout"}
```

When no results are found, tools return a successful response with an empty list:
```python
{"query": "obscure search", "results": [], "count": 0}
```
