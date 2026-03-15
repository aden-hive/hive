# DuckDuckGo Tool

Privacy-respecting web, news, and image search — no API key required.

Uses the [`duckduckgo_search`](https://pypi.org/project/duckduckgo-search/) Python library.

---

## Tools

### `duckduckgo_search`

Search the web using DuckDuckGo.

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | required | Search query |
| `max_results` | `int` | `10` | Number of results to return (1–50) |
| `region` | `str` | `"us-en"` | Region code, e.g. `us-en`, `uk-en`, `de-de` |
| `safesearch` | `str` | `"moderate"` | Safety filter: `on`, `moderate`, or `off` |
| `timelimit` | `str` | `""` | Time filter: `d` (day), `w` (week), `m` (month), `y` (year), or `""` (any) |

**Returns**

```json
{
  "query": "your search query",
  "results": [
    {
      "title": "Page title",
      "url": "https://example.com/page",
      "snippet": "Brief excerpt from the page"
    }
  ],
  "count": 10
}
```

---

### `duckduckgo_news`

Search recent news articles using DuckDuckGo.

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | required | News search query |
| `max_results` | `int` | `10` | Number of results to return (1–50) |
| `region` | `str` | `"us-en"` | Region code, e.g. `us-en`, `uk-en`, `de-de` |
| `timelimit` | `str` | `""` | Time filter: `d` (day), `w` (week), `m` (month), or `""` (any) |

**Returns**

```json
{
  "query": "your news query",
  "results": [
    {
      "title": "Article headline",
      "url": "https://news.example.com/article",
      "source": "Example News",
      "date": "2026-03-15T10:00:00",
      "snippet": "Brief article summary"
    }
  ],
  "count": 10
}
```

---

### `duckduckgo_images`

Search images using DuckDuckGo.

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | required | Image search query |
| `max_results` | `int` | `10` | Number of results to return (1–50) |
| `region` | `str` | `"us-en"` | Region code, e.g. `us-en`, `uk-en`, `de-de` |
| `safesearch` | `str` | `"moderate"` | Safety filter: `on`, `moderate`, or `off` |
| `size` | `str` | `""` | Size filter: `Small`, `Medium`, `Large`, `Wallpaper`, or `""` (any) |

**Returns**

```json
{
  "query": "your image query",
  "results": [
    {
      "title": "Image title",
      "image_url": "https://example.com/image.jpg",
      "thumbnail_url": "https://example.com/thumb.jpg",
      "source": "example.com",
      "width": 1920,
      "height": 1080
    }
  ],
  "count": 10
}
```

---

## Error Handling

All three tools return an `error` key on failure:

```json
{ "error": "DuckDuckGo search failed: <reason>" }
```

---

## Dependencies

```
duckduckgo-search>=6.0
```

No credentials or API keys are needed.
