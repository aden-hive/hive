# Web Scrape Tool

Scrape and extract text content from webpages using a headless browser.

## Description

Use when you need to read the content of a specific URL, extract data from a website, or read articles/documentation. Uses Playwright with stealth to render JavaScript-heavy pages and evade bot detection. Automatically removes noise elements (scripts, navigation, footers) and extracts the main content.

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `url` | str | Yes | - | URL of the webpage to scrape |
| `selector` | str | No | `None` | CSS selector to target specific content (e.g., 'article', '.main-content') |
| `include_links` | bool | No | `False` | Include extracted links in the response |
| `max_length` | int | No | `50000` | Maximum length of extracted text (1000-500000) |
| `respect_robots_txt` | bool | No | `True` | Whether to respect robots.txt rules |

## Setup

Requires Chromium browser binaries:

```bash
uv pip install playwright playwright-stealth
uv run playwright install chromium
```

## Environment Variables

This tool does not require any environment variables.

## Error Handling

Returns error dicts for common issues:
- `HTTP <status>: Failed to fetch URL` - Server returned error status
- `Navigation failed: no response received` - Browser could not navigate to URL
- `No elements found matching selector: <selector>` - CSS selector matched nothing
- `Request timed out` - Page load exceeded 30s timeout
- `Browser error: <error>` - Playwright/Chromium error
- `Scraping failed: <error>` - HTML parsing or other error

## Notes

- Uses Playwright (Chromium) with playwright-stealth for bot detection evasion
- Renders JavaScript before extracting content (works with SPAs and dynamic pages)
- URLs without protocol are automatically prefixed with `https://`
- Waits for `networkidle` before extracting content
- Removes script, style, nav, footer, header, aside, noscript, and iframe elements
- Auto-detects main content using article, main, or common content class selectors
- Respects robots.txt by default (uses httpx for lightweight robots.txt fetching)
