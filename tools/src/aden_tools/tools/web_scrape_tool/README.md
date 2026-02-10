# Web Scrape Tool

Scrape and extract text content from webpages using a headless browser.

## Quick Start

    from aden_tools.tools.web_scrape_tool import web_scrape_tool
    
    result = web_scrape_tool.run(
        url="https://example.com"
    )
    print(result["content"])

Use this tool when you need to extract text from web pages that rely on
JavaScript rendering or dynamic content.

## Description

Use when you need to read the content of a specific URL, extract data from a website, or read articles/documentation. Uses Playwright with stealth to render JavaScript-heavy pages and evade bot detection. Automatically removes noise elements (scripts, navigation, footers) and extracts the main content.

## When to Use

- Extracting text from JavaScript-rendered or dynamic websites
- Scraping articles, blogs, or documentation pages
- Reading content not available through a public API

## When Not to Use

- When a structured public API already exists
- For bulk or high-frequency web crawling
- For scraping websites that explicitly disallow automated access


## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `url` | str | Yes | - | URL of the webpage to scrape |
| `selector` | str | No | `None` | CSS selector to target specific content (e.g., 'article', '.main-content') |
| `include_links` | bool | No | `False` | Include extracted links in the response |
| `max_length` | int | No | `50000` | Maximum length of extracted text (1000-500000) |

## URL Handling

- URLs without a protocol are automatically prefixed with `https://`
- Redirects are followed automatically
- Only successful HTTP 200 responses are processed



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
- `Request timed out` - Page load exceeded 60s timeout
- `Browser error: <error>` - Playwright/Chromium error
- `Scraping failed: <error>` - HTML parsing or other error
- 
## Limitations

- Page load timeout is capped at 60 seconds
- Maximum of 50 links are extracted when `include_links=True`
- Extracted content may be truncated using `max_length`
- Some websites may still block headless browsers
- Not intended for large-scale or high-frequency crawling


## Notes

- Uses Playwright (Chromium) with playwright-stealth for bot detection evasion
- Renders JavaScript content before extraction (works with SPAs and dynamic pages)
- Waits for DOM content to load before extracting content
- Removes `script`, `style`, `nav`, `footer`, `header`, `aside`, `noscript`, and `iframe` elements
- Attempts to auto-detect main content using `article`, `main`, or common content containers

