# Confluence Tool

Manage Confluence spaces and pages via the Confluence Cloud REST API.

## Setup

```bash
export CONFLUENCE_DOMAIN=your-domain.atlassian.net
export CONFLUENCE_EMAIL=you@company.com
export CONFLUENCE_API_TOKEN=your_token
```

Get your API token at https://id.atlassian.com/manage/api-tokens

Alternatively, configure credentials in the Aden credential store:
- `confluence_domain`
- `confluence_email`
- `confluence_token`

## Tools (8)

| Tool | Description |
|------|-------------|
| `confluence_list_spaces` | List Confluence spaces |
| `confluence_list_pages` | List pages, optionally filtered by space or title |
| `confluence_get_page` | Get a page by ID with body content |
| `confluence_create_page` | Create a new page in a space |
| `confluence_search` | Search pages using CQL text queries |
| `confluence_update_page` | Update an existing page (requires next version number) |
| `confluence_delete_page` | Delete a page by ID |
| `confluence_get_page_children` | List child pages of a parent page |

## Usage

### List spaces

```python
result = confluence_list_spaces(limit=50)
```

### Search pages

```python
result = confluence_search(query="runbook", space_key="ENG", limit=10)
```

### Create a page

```python
result = confluence_create_page(
    space_id="123456",
    title="Incident Runbook",
    body="<p>Steps go here.</p>",
)
```

### Update a page

```python
page = confluence_get_page(page_id="987654")
result = confluence_update_page(
    page_id="987654",
    title=page["title"],
    body="<p>Updated content</p>",
    version_number=page["version"] + 1,
)
```

## Scope

- Spaces listing
- Page listing, retrieval, search, creation, update, and delete
- Child page discovery

## API Reference

- Confluence Cloud REST API v2: https://developer.atlassian.com/cloud/confluence/rest/v2/intro/
