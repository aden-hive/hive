# Browser Automation Tool

Browser automation capabilities for interacting with JavaScript-rendered pages, filling forms, taking screenshots, and extracting dynamic content.

## Setup

Playwright is already included as a dependency. You only need to install browser binaries:

```bash
playwright install chromium
```

No environment variables are required.

## Available Tools

| Tool | Description |
|------|-------------|
| `browser_get_page_content` | Navigate to a URL and return fully rendered HTML |
| `browser_screenshot` | Capture a screenshot of a webpage |
| `browser_extract_text` | Extract visible text content from a page |
| `browser_click_and_extract` | Click an element and extract the resulting content |
| `browser_inspect_form` | Inspect form fields and discover CSS selectors |
| `browser_fill_form` | Fill form fields and optionally submit |

**When to use Browser Automation vs. `web_scrape_tool`:**

- **Use `web_scrape_tool`** for simple, static HTML pages (faster, lighter)
- **Use Browser Automation tools** when:
  - Content is rendered by JavaScript (SPAs, React, Vue, Angular)
  - You need to interact with the page (click, fill forms)
  - You need screenshots
  - Static scraping returns empty or incomplete results

## Tool Details

### `browser_get_page_content`

Navigate to a URL and return fully rendered HTML content.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | str | Yes | - | The URL to navigate to |
| `wait_for` | str | No | `None` | CSS selector to wait for before extracting content |
| `timeout` | int | No | `30000` | Maximum time in ms to wait (5000-300000) |

**Returns:**

```json
{
  "html": "<html>...</html>",
  "title": "Page Title",
  "url": "https://final-url-after-redirects.com"
}
```

---

### `browser_screenshot`

Capture a screenshot of a webpage.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | str | Yes | - | The URL to screenshot |
| `output_path` | str | No | `"screenshot.png"` | File path to save the screenshot (must be within working directory) |
| `full_page` | bool | No | `True` | If True, capture full scrollable page |
| `timeout` | int | No | `30000` | Maximum time in ms to wait (5000-300000) |

**Returns:**

```json
{
  "path": "screenshot.png",
  "width": 1920,
  "height": 1080
}
```

---

### `browser_extract_text`

Extract visible text content from a page (stripped of HTML tags).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | str | Yes | - | The URL to extract text from |
| `selector` | str | No | `None` | CSS selector for specific element (defaults to body) |
| `timeout` | int | No | `30000` | Maximum time in ms to wait (5000-300000) |

**Returns:**

```json
{
  "text": "Visible text content...",
  "title": "Page Title",
  "url": "https://final-url.com"
}
```

---

### `browser_click_and_extract`

Click an element on a page and extract the resulting content.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | str | Yes | - | The URL to navigate to |
| `click_selector` | str | Yes | - | CSS selector of element to click |
| `wait_for_selector` | str | No | `None` | CSS selector to wait for after clicking |
| `timeout` | int | No | `30000` | Maximum time in ms to wait (5000-300000) |

**Returns:**

```json
{
  "html": "<html>...</html>",
  "title": "Page Title",
  "url": "https://final-url.com",
  "clicked_element": "#button-id"
}
```

---

### `browser_inspect_form`

Inspect forms on a webpage and return human-readable field information with CSS selectors.

**Use this before `browser_fill_form`** to discover what fields are available. The returned selectors can be passed directly to `browser_fill_form`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | str | Yes | - | The URL to navigate to |
| `form_selector` | str | No | `None` | CSS selector for a specific form (if None, inspects all forms) |
| `timeout` | int | No | `30000` | Maximum time in ms to wait (5000-300000) |

**Returns:**

```json
{
  "forms": [
    {
      "form_index": 0,
      "form_selector": "form:nth-of-type(1)",
      "generated_form_selector": "form >> nth=0",
      "fields": [
        {
          "label": "Email Address",
          "name": "email",
          "type": "email",
          "selector": "#email",
          "required": true,
          "placeholder": "Enter your email"
        },
        {
          "label": "Country",
          "name": "country",
          "type": "select",
          "selector": "#country",
          "required": false,
          "placeholder": "",
          "options": [
            {"value": "us", "text": "United States"},
            {"value": "uk", "text": "United Kingdom"}
          ]
        }
      ],
      "submit_selector": "form >> nth=0 >> button[type=\"submit\"], input[type=\"submit\"] >> nth=0"
    }
  ],
  "forms_found": 1,
  "title": "Page Title",
  "url": "https://example.com/login"
}
```

**Workflow:**

1. **Call `browser_inspect_form`** — get human-readable field descriptions with selectors
2. **Ask user for values** — "I found a login form with email and password fields."
3. **User provides values** — "Email: user@example.com, Password: secret123"
4. **Map values to selectors** — use the `selector` field from the inspection results
5. **Call `browser_fill_form`** — pass the CSS selectors with user values

---

### `browser_fill_form`

Fill form fields and optionally submit the form.

**Note:** If you don't know the CSS selectors for form fields, use `browser_inspect_form` first to discover them.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | str | Yes | - | The URL to navigate to |
| `form_fields` | str | Yes | - | JSON string mapping CSS selectors to values |
| `submit` | bool | No | `False` | Whether to submit the form after filling |
| `submit_selector` | str | No | `None` | CSS selector of submit button (if different) |
| `wait_for_selector` | str | No | `None` | CSS selector to wait for after submission |
| `timeout` | int | No | `30000` | Maximum time in ms to wait (5000-300000) |

**Form Fields Format:**

```json
{
  "#username": "user@example.com",
  "#password": "secret123",
  "#remember-me": "true"
}
```

Supported field types:
- Text inputs (`input[type="text"]`, `textarea`)
- Select dropdowns (`<select>`)
- Checkboxes (`input[type="checkbox"]`)
- Radio buttons (`input[type="radio"]`)

**Returns:**

```json
{
  "html": "<html>...</html>",
  "title": "Page Title",
  "url": "https://final-url.com",
  "filled_fields": {
    "#username": "user@example.com",
    "#password": "secret123"
  },
  "submitted": true
}
```

## Example Usage

### Get rendered page content

```python
result = await browser_get_page_content(
    url="https://spa.example.com",
    wait_for=".dynamic-content",
    timeout=60000
)
```

### Take a screenshot

```python
result = await browser_screenshot(
    url="https://example.com/dashboard",
    output_path="dashboard.png",
    full_page=True
)
```

### Extract text from a specific element

```python
result = await browser_extract_text(
    url="https://example.com/article",
    selector="article"
)
```

### Click and extract

```python
result = await browser_click_and_extract(
    url="https://example.com/products",
    click_selector=".load-more-button",
    wait_for_selector=".product-list"
)
```

### Inspect and fill a form

```python
# Step 1: Discover form fields
result = await browser_inspect_form(url="https://example.com/login")

# Step 2: Fill and submit using discovered selectors
result = await browser_fill_form(
    url="https://example.com/login",
    form_fields='{"#email": "user@example.com", "#password": "secret123"}',
    submit=True,
    wait_for_selector=".dashboard"
)
```

## Error Handling

All tools return error dicts for common issues:

| Error | Cause |
|-------|-------|
| `Request timed out after {timeout}ms` | Page load exceeded timeout |
| `Browser error: {error}` | Playwright/Chromium error |
| `Failed to {action}: {error}` | General error during execution |
| `Element not found: {selector}` | CSS selector matched nothing |
| `Invalid JSON in form_fields: {error}` | Malformed form_fields JSON |
| `Timeout waiting for field: {selector}` | Form field not visible within timeout |

## Supported Features

- Single-page interactions with dynamic content
- Form inspection, filling, and submission
- Screenshot capture (viewport and full-page)
- Text and HTML content extraction
- Click-based interactions with wait support
- Automatic URL normalization and redirect handling

### Coming Soon

The following capabilities are planned for future releases:

- **File uploads** — support for file input fields in forms
- **Multi-page form workflows** — persistent sessions across sequential pages
- **PDF generation** — render pages to PDF
- **Persistent browser sessions** — cookie and session reuse across tool calls
- **Network interception** — request mocking and response modification
- **Video recording** — capture browser session recordings

## Resource Considerations

- **Memory**: Each browser instance uses ~100-200MB RAM
- **CPU**: Browser rendering is CPU-intensive
- **Disk**: Screenshots are saved to disk (PNG format)
- **Network**: Full page loads including all assets

**Best Practices:**

- Use `web_scrape_tool` first for simple pages — fall back to browser automation only when needed
- Set appropriate timeouts to avoid hanging
- Clean up screenshots periodically

## Related Tools

- **`web_scrape_tool`**: Fast text extraction from static HTML pages
- **`web_search_tool`**: Search the web for URLs (use with Browser Automation to scrape results)

## Notes

- Uses Chromium browser (headless mode)
- Automatically handles redirects
- Waits for network idle by default
- Supports all standard CSS selectors
- URLs without protocol are automatically prefixed with `https://`
