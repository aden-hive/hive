# Confluence Tool

Wiki and knowledge management via Confluence Cloud REST API v2.

## Available Functions

### Spaces & Pages

- `confluence_list_spaces(limit=25)`
  - `limit` (int, optional): Max results (1-250, default 25)
  - Returns: `{"spaces": [...], "count": N}` with id, key, name, type, status

- `confluence_list_pages(space_id="", title="", limit=25)`
  - `space_id` (str, optional): Filter by space ID
  - `title` (str, optional): Filter by exact page title
  - `limit` (int, optional): Max results (1-250)
  - Returns: `{"pages": [...], "count": N}` with id, title, space_id, version

- `confluence_get_page(page_id, body_format="storage")`
  - `page_id` (str): Page ID (required)
  - `body_format` (str, optional): `"storage"`, `"view"`, or `"atlas_doc_format"`
  - Returns: Full page details with body content (truncated to 5000 chars)

- `confluence_get_page_children(page_id, limit=25)`
  - `page_id` (str): Parent page ID (required)
  - `limit` (int, optional): Max results (1-250)
  - Returns: `{"children": [...], "count": N}`

### CRUD Operations

- `confluence_create_page(space_id, title, body, parent_id="")`
  - `space_id` (str): Space ID to create page in (required)
  - `title` (str): Page title (required)
  - `body` (str): Page content in Confluence storage format (XHTML) (required)
  - `parent_id` (str, optional): Parent page ID for child pages
  - Returns: `{"id": "...", "title": "...", "status": "created"}`

- `confluence_update_page(page_id, title, body, version_number)`
  - `page_id` (str): Page ID (required)
  - `title` (str): Page title (required, even if unchanged)
  - `body` (str): New content in storage format (required)
  - `version_number` (int): Current version + 1 (required)
  - Returns: `{"id": "...", "title": "...", "version": N, "status": "updated"}`

- `confluence_delete_page(page_id)`
  - `page_id` (str): Page ID to delete (required)
  - Returns: `{"page_id": "...", "status": "deleted"}`

### Search

- `confluence_search(query, space_key="", limit=25)`
  - `query` (str): Search text (used in CQL `text~` query) (required)
  - `space_key` (str, optional): Filter by space key (e.g., `"DEV"`)
  - `limit` (int, optional): Max results (1-50)
  - Returns: `{"results": [...], "count": N}` with title, excerpt, page_id, space

## Required Credentials

Set these environment variables:

```bash
# Your Confluence domain (e.g., your-company.atlassian.net)
export CONFLUENCE_DOMAIN="your-company.atlassian.net"

# Your Atlassian account email
export CONFLUENCE_EMAIL="you@company.com"

# Generate an API token at https://id.atlassian.com/manage/api-tokens
export CONFLUENCE_API_TOKEN="your_api_token_here"
```

> 💡 **Tip**: Make sure the user has permissions to access the spaces and pages you want to interact with.

## Example Usage

```python
# List all spaces
spaces = confluence_list_spaces(limit=10)
# Returns: {"spaces": [{"id": "123", "key": "DEV", "name": "Development", ...}], ...}

# List pages in a specific space
pages = confluence_list_pages(space_id="123", limit=20)

# Get a specific page's content
page = confluence_get_page(page_id="456", body_format="storage")
# Returns: {"id": "456", "title": "...", "body": "<p>Content...</p>", ...}

# Search for pages containing "API documentation"
results = confluence_search(query="API documentation", space_key="DEV")
# Returns: {"results": [{"title": "...", "excerpt": "...", "page_id": "..."}], ...}

# Create a new page
new_page = confluence_create_page(
    space_id="123",
    title="Meeting Notes 2026-03-31",
    body="<h1>Meeting Notes</h1><p>Attendees: Alice, Bob</p>",
    parent_id="456"  # Optional: make it a child page
)

# Update an existing page (must increment version number)
# First get current version
current = confluence_get_page(page_id="789")
current_version = current["version"]  # e.g., 5

confluence_update_page(
    page_id="789",
    title="Updated Title",
    body="<h1>Updated Content</h1>",
    version_number=current_version + 1  # Must be current + 1
)

# Get child pages of a parent
children = confluence_get_page_children(page_id="456")

# Delete a page
confluence_delete_page(page_id="789")
```

## Body Format (Storage Format)

The `body` parameter uses Confluence **storage format** (XHTML-like). Examples:

```python
# Simple paragraph
body = "<p>This is a paragraph.</p>"

# Heading and list
body = """
<h1>Meeting Notes</h1>
<h2>Attendees</h2>
<ul>
  <li>Alice</li>
  <li>Bob</li>
</ul>
<h2>Action Items</h2>
<ol>
  <li>Review PR #123</li>
  <li>Update documentation</li>
</ol>
"""

# Code block
body = """
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">python</ac:parameter>
  <ac:plain-text-body><![CDATA[
def hello():
    print("Hello, World!")
]]></ac:plain-text-body>
</ac:structured-macro>
"""
```

## Version Number Requirement

When updating a page, you **must** provide the next version number:

```python
# 1. Get current page
page = confluence_get_page(page_id="123")
current_version = page["version"]  # e.g., 5

# 2. Update with version + 1
confluence_update_page(
    page_id="123",
    title="Same Title",
    body="<p>Updated content</p>",
    version_number=current_version + 1  # 6 in this example
)
```

## Error Handling

All functions return error dicts on failure:

```python
# Missing credentials
{"error": "CONFLUENCE_DOMAIN, CONFLUENCE_EMAIL, and CONFLUENCE_API_TOKEN not set", "help": "Generate an API token at https://id.atlassian.com/manage/api-tokens"}

# Unauthorized
{"error": "Unauthorized. Check your Confluence credentials."}

# Not found
{"error": "Not found"}

# Wrong version number on update
{"error": "Confluence API error 409: Version mismatch"}

# Request timeout
{"error": "Request to Confluence timed out"}
```

## Reference

- [Confluence Cloud API v2 Docs](https://developer.atlassian.com/cloud/confluence/rest/v2/intro/)
- [Get API Token](https://id.atlassian.com/manage/api-tokens)
- [CQL (Confluence Query Language)](https://developer.atlassian.com/cloud/confluence/advanced-searching-using-cql/)
- [Storage Format Reference](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-content/#content-storage-format)