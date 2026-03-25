# Confluence Tool

Wiki and knowledge management via the Confluence Cloud REST API v2.

## Supported Actions

- **confluence_list_spaces** – List available spaces
- **confluence_list_pages** / **confluence_get_page** – Browse and read pages
- **confluence_create_page** / **confluence_update_page** / **confluence_delete_page** – Page CRUD
- **confluence_search** – Full-text search using CQL (Confluence Query Language)
- **confluence_get_page_children** – List child pages of a parent

## Setup

1. Generate an API token at [Atlassian API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens).

2. Set the required environment variables:
   ```bash
   export CONFLUENCE_URL=https://your-domain.atlassian.net
   export CONFLUENCE_EMAIL=your-email@example.com
   export CONFLUENCE_API_TOKEN=your-api-token
   ```

## Use Case

Example: "Search the Engineering space for all pages mentioning 'database migration', then update the runbook page with the latest procedure."
