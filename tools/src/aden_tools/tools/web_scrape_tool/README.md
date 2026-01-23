# Web Scrape Tool

Scrape and extract text content from webpages.

## Description

Use when you need to read the content of a specific URL, extract data from a website, or read articles/documentation. Automatically removes noise elements (scripts, navigation, footers) and extracts the main content.

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `url` | str | Yes | - | URL of the webpage to scrape |
| `selector` | str | No | `None` | CSS selector to target specific content (e.g., 'article', '.main-content') |
| `include_links` | bool | No | `False` | Include extracted links in the response |
| `max_length` | int | No | `50000` | Maximum length of extracted text (1000-500000) |

## Environment Variables

This tool does not require any environment variables.

## Error Handling

Returns error dicts for common issues:
- `HTTP <status>: Failed to fetch URL` - Server returned error status
- `No elements found matching selector: <selector>` - CSS selector matched nothing
- `Request timed out` - Request exceeded 30s timeout
- `Network error: <error>` - Connection or DNS issues
- `Scraping failed: <error>` - HTML parsing or other error

## Notes

- URLs without protocol are automatically prefixed with `https://`
- Follows redirects automatically
- Removes script, style, nav, footer, header, aside, noscript, and iframe elements
- Auto-detects main content using article, main, or common content class selectors
