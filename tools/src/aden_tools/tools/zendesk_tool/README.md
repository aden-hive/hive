# Zendesk Tool

Ticket management, comments, user listing, and search via the Zendesk Support API.

## Tools

| Tool | Description |
|------|-------------|
| `zendesk_list_tickets` | List tickets in the account |
| `zendesk_get_ticket` | Get full details of a specific ticket |
| `zendesk_create_ticket` | Create a new support ticket |
| `zendesk_update_ticket` | Update ticket status, priority, or tags |
| `zendesk_search_tickets` | Search tickets using Zendesk query syntax |
| `zendesk_get_ticket_comments` | List all comments on a ticket |
| `zendesk_add_ticket_comment` | Add a public reply or internal note to a ticket |
| `zendesk_list_users` | List users filtered by role |

## Setup

Requires a Zendesk subdomain, agent email, and API token:

1. Log in to your Zendesk admin panel
2. Go to **Admin → Apps and integrations → APIs → Zendesk API**
3. Enable **Token Access** and create a new API token

```bash
ZENDESK_SUBDOMAIN=your-subdomain
ZENDESK_EMAIL=agent@yourcompany.com
ZENDESK_API_TOKEN=your-api-token
```

> `ZENDESK_SUBDOMAIN` is the part before `.zendesk.com`. For `https://acme.zendesk.com`, use `acme`.

## Usage Examples

### List open tickets

```python
zendesk_list_tickets(page_size=25)
```

### Get a specific ticket

```python
zendesk_get_ticket(ticket_id=12345)
```

### Create a new ticket

```python
zendesk_create_ticket(
    subject="Login button not working",
    body="Users are reporting that the login button on mobile is unresponsive.",
    priority="high",
    ticket_type="incident",
    tags="mobile,login,bug",
)
```

### Update a ticket status

```python
zendesk_update_ticket(
    ticket_id=12345,
    status="pending",
    priority="urgent",
)
```

### Add a public reply to a ticket

```python
zendesk_add_ticket_comment(
    ticket_id=12345,
    body="We have identified the issue and a fix is being deployed.",
    public=True,
)
```

### Add an internal note

```python
zendesk_add_ticket_comment(
    ticket_id=12345,
    body="Escalated to the backend team via Slack #incidents.",
    public=False,
)
```

### Search tickets

```python
zendesk_search_tickets(
    query="status:open priority:urgent",
    sort_by="updated_at",
    sort_order="desc",
)
```

### Search by assignee and tag

```python
zendesk_search_tickets(query="assignee:agent@company.com tags:billing")
```

### List all agents

```python
zendesk_list_users(role="agent", page_size=50)
```

## Ticket Status Values

| Status | Meaning |
|--------|---------|
| `new` | Newly created, unassigned |
| `open` | Assigned and being worked on |
| `pending` | Waiting for requester response |
| `hold` | Waiting on a third party |
| `solved` | Resolved by agent |
| `closed` | Permanently closed |

## Error Handling

All tools return error dicts on failure:

```python
[
    {"error": "ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, and ZENDESK_API_TOKEN not set", "help": "Create an API token in Zendesk Admin > Apps and integrations > APIs > Zendesk API"},
    {"error": "Unauthorized. Check your Zendesk credentials."},
    {"error": "Forbidden. Check your Zendesk permissions."},
    {"error": "Rate limited. Try again shortly."},
]
```
