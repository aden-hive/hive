# Freshdesk Tool

Ticket, contact, agent, and group management via the Freshdesk API v2.

## Description

This tool integrates with Freshdesk’s REST API v2 to list, create, and update tickets; manage contacts, agents, groups, and companies; and add public replies or private notes. Use it when an agent needs to query or modify support data in Freshdesk. Domain and API key are resolved from the credential store or environment; tools do not accept a domain parameter.

## Setup

Both API key and domain are required. Configure once via environment or credential store.

```bash
export FRESHDESK_API_KEY=your-freshdesk-api-key
export FRESHDESK_DOMAIN=acme.freshdesk.com
```

- **API key:** Profile → Profile Settings → Your API Key. Set `FRESHDESK_API_KEY` (or store as `freshdesk` in the credential store).
- **Domain:** Your Freshdesk hostname (e.g. `acme.freshdesk.com`). Set `FRESHDESK_DOMAIN` (or store as `freshdesk_domain`).

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FRESHDESK_API_KEY` | Yes | API key from Freshdesk profile settings |
| `FRESHDESK_DOMAIN` | Yes | Freshdesk hostname (e.g. `acme.freshdesk.com`) |

## Tools (17)

| Tool | Description |
|------|-------------|
| `freshdesk_list_tickets` | List tickets with optional filter and `updated_since` |
| `freshdesk_filter_tickets` | Search tickets by query (e.g. priority:3, status:2; pages 1-10 only per Freshdesk search API) |
| `freshdesk_list_ticket_conversations` | List replies and notes for a ticket |
| `freshdesk_get_ticket` | Get a single ticket by ID |
| `freshdesk_create_ticket` | Create a ticket from requester email, subject, description |
| `freshdesk_update_ticket` | Update ticket status/priority/tags; optionally add a note (via Notes API) |
| `freshdesk_add_ticket_reply` | Add a public reply (customer-visible) or private note (internal only) |
| `freshdesk_list_contacts` | List contacts, optionally filtered by email |
| `freshdesk_get_contact` | Get a contact by ID or email |
| `freshdesk_create_contact` | Create a contact with email/name/phone/company_id |
| `freshdesk_update_contact` | Update a contact (name, email, phone, company_id) |
| `freshdesk_list_agents` | List agents for routing/assignment logic |
| `freshdesk_get_agent` | Get a single agent by ID |
| `freshdesk_list_groups` | List groups for routing/assignment logic |
| `freshdesk_get_group` | Get a single group by ID |
| `freshdesk_list_companies` | List companies (with optional updated_since) |
| `freshdesk_get_company` | Get a single company by ID |

## Usage Examples

```python
freshdesk_list_tickets(
    page=1,
    per_page=30,
    updated_since="2026-03-01T00:00:00Z",
)
freshdesk_get_ticket(ticket_id=123)
freshdesk_create_ticket(
    email="user@example.com",
    subject="Cannot log in",
    description="User reports login failure on Chrome",
    priority=2,
    status=2,
    tags="login,bug",
)
freshdesk_update_ticket(
    ticket_id=123,
    status=3,
    note="Waiting for user to confirm the fix",
    note_private=True,
)
freshdesk_add_ticket_reply(
    ticket_id=123,
    body="We've deployed a fix. Can you try again?",
    public=True,
)
freshdesk_list_contacts(email="user@example.com")
freshdesk_create_contact(
    email="user@example.com",
    name="Jane Doe",
    phone="+1-555-1234",
)
freshdesk_add_ticket_reply(
    ticket_id=123,
    body="Internal: escalated to L2.",
    public=False,
)
freshdesk_list_agents()
freshdesk_list_groups()
```

## API behavior (Freshdesk v2)

- Public replies use the Reply endpoint; private notes use the Notes endpoint (tool chooses by `public`).
- `freshdesk_update_ticket` with `note`: ticket fields via PUT, then note via POST `/tickets/{id}/notes` (PUT does not accept notes). If the note POST fails, the result includes `"note_error"`.
- `freshdesk_filter_tickets` page range is 1-10 (Freshdesk search API limit); values outside this range are clamped.

## Error Handling

Tools return a dict with an `"error"` key (and optional `"help"`) on failure. Common cases:

- **Missing API key:** `"error": "FRESHDESK_API_KEY environment variable not set"` — set `FRESHDESK_API_KEY` or configure `freshdesk` in the credential store.
- **Missing domain:** `"error": "FRESHDESK_DOMAIN is required"` — set `FRESHDESK_DOMAIN` or configure `freshdesk_domain`.
- **Missing ID:** `"error": "ticket_id is required"` (or similar) — required ID parameter omitted.
- **No updates:** `"error": "At least one field (status, priority, tags, note) is required"` — `freshdesk_update_ticket` called with no updates.
- **API error:** `"error": "Freshdesk API error <status>: <message>"` — upstream Freshdesk error; see status and message for details.

See the [Freshdesk API v2 docs](https://developers.freshdesk.com/api/) for field semantics.
