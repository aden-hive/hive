# Zendesk Tool

Ticket management and search via the Zendesk Support API.

## Supported Actions

- **zendesk_list_tickets** / **zendesk_get_ticket** / **zendesk_create_ticket** / **zendesk_update_ticket** – Ticket CRUD
- **zendesk_search_tickets** – Search tickets with Zendesk query syntax
- **zendesk_get_ticket_comments** / **zendesk_add_ticket_comment** – Ticket conversation management
- **zendesk_list_users** – List users in the account

## Setup

1. Generate an API token in Zendesk (Admin → Channels → API).

2. Set the required environment variables:
   ```bash
   export ZENDESK_SUBDOMAIN=your-subdomain          # from your-subdomain.zendesk.com
   export ZENDESK_EMAIL=your-email@example.com
   export ZENDESK_API_TOKEN=your-api-token
   ```

## Use Case

Example: "Search for all open tickets tagged 'billing' that have been unassigned for more than 48 hours, assign them to the billing team, and add an internal comment noting the SLA breach."
