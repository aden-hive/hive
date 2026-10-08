# Google Search Console Tool

Analyze search performance, manage sitemaps, and inspect URLs using the Google Search Console API.

## Tools

| Tool | Description |
|------|-------------|
| `gsc_search_analytics` | Query search analytics data with dimension and date filters |
| `gsc_list_sites` | List all verified sites in the account |
| `gsc_list_sitemaps` | List sitemaps for a site |
| `gsc_inspect_url` | Inspect a URL's indexing status |
| `gsc_submit_sitemap` | Submit a sitemap URL for a site |
| `gsc_delete_sitemap` | Delete a submitted sitemap |
| `gsc_top_queries` | Get top search queries for a site |
| `gsc_top_pages` | Get top pages by clicks for a site |

## Setup

Requires Google OAuth2 via Aden:

1. Connect your Google account at [hive.adenhq.com](https://hive.adenhq.com)
2. The `GOOGLE_SEARCH_CONSOLE_TOKEN` is managed automatically by the Aden credential system

Or set manually:

| Variable | Description |
|----------|-------------|
| `GOOGLE_SEARCH_CONSOLE_TOKEN` | Google OAuth2 access token |

Required OAuth scopes: `https://www.googleapis.com/auth/webmasters.readonly` (read) or `https://www.googleapis.com/auth/webmasters` (read/write).

## Usage Examples

### Get top queries for the last 7 days
```python
gsc_top_queries(site_url="https://example.com", days=7, limit=20)
```

### Check a URL's index status
```python
gsc_inspect_url(site_url="https://example.com", inspection_url="https://example.com/page")
```

### Submit a sitemap
```python
gsc_submit_sitemap(site_url="https://example.com", sitemap_url="https://example.com/sitemap.xml")
```

### Query search analytics with filters
```python
gsc_search_analytics(
    site_url="https://example.com",
    start_date="2026-01-01",
    end_date="2026-01-31",
    dimensions=["query", "page"],
    row_limit=50,
)
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "GOOGLE_SEARCH_CONSOLE_TOKEN not set", "help": "Set GOOGLE_SEARCH_CONSOLE_TOKEN or connect via hive.adenhq.com"}
{"error": "Unauthorized. Check your GOOGLE_SEARCH_CONSOLE_TOKEN."}
{"error": "Request timed out"}
```
