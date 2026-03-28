# DuckDuckGo Tool

Search the web, news, and images using DuckDuckGo — no API key or credentials required.

## Tools

### `duckduckgo_search`

Search the web for any query.

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Search query |
| `max_results` | int | 10 | Number of results (1–50) |
| `region` | string | `us-en` | Region code (e.g. `uk-en`, `de-de`) |
| `safesearch` | string | `moderate` | Safety filter: `on`, `moderate`, `off` |
| `timelimit` | string | `""` | Time filter: `d` (day), `w` (week), `m` (month), `y` (year), `""` (any) |

**Returns**
```json
{
  "query": "your search query",
  "count": 10,
  "results": [
    {
      "title": "Result title",
      "url": "https://example.com",
      "snippet": "Brief description of the result"
    }
  ]
}
```

---

### `duckduckgo_news`

Search recent news articles.

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | News search query |
| `max_results` | int | 10 | Number of results (1–50) |
| `region` | string | `us-en` | Region code |
| `timelimit` | string | `""` | Time filter: `d`, `w`, `m`, `""` |

**Returns**
```json
{
  "query": "your search query",
  "count": 10,
  "results": [
    {
      "title": "Article title",
      "url": "https://example.com/article",
      "source": "News Source",
      "date": "2026-03-22",
      "snippet": "Article summary"
    }
  ]
}
```

---

### `duckduckgo_images`

Search for images.

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Image search query |
| `max_results` | int | 10 | Number of results (1–50) |
| `region` | string | `us-en` | Region code |
| `safesearch` | string | `moderate` | Safety filter: `on`, `moderate`, `off` |
| `size` | string | `""` | Size filter: `Small`, `Medium`, `Large`, `Wallpaper`, `""` (any) |

**Returns**
```json
{
  "query": "your search query",
  "count": 10,
  "results": [
    {
      "title": "Image title",
      "image_url": "https://example.com/image.jpg",
      "thumbnail_url": "https://example.com/thumb.jpg",
      "source": "example.com",
      "width": 1920,
      "height": 1080
    }
  ]
}
```

---

## No credentials needed

Unlike most tools in this directory, the DuckDuckGo tool requires no API key or environment variables. It works out of the box.

## Dependencies

Uses the [`duckduckgo-search`](https://pypi.org/project/duckduckgo-search/) Python library, installed automatically with the tools package.