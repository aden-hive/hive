# HubSpot Tool

Manage HubSpot CRM contacts, companies, deals, and associations from the Aden agent framework.

## Setup

```bash
export HUBSPOT_ACCESS_TOKEN=your-private-app-token
```

**Get your token:**
1. Go to https://developers.hubspot.com/docs/api/private-apps
2. Create a HubSpot private app
3. Enable the CRM scopes your workflow needs
4. Copy the access token and set `HUBSPOT_ACCESS_TOKEN`

Alternatively, configure HubSpot credentials through the Aden credential store.

## Tools (15)

| Tool | Description |
|------|-------------|
| `hubspot_search_contacts` | Search CRM contacts |
| `hubspot_get_contact` | Get a contact by ID |
| `hubspot_create_contact` | Create a new contact |
| `hubspot_update_contact` | Update an existing contact |
| `hubspot_search_companies` | Search CRM companies |
| `hubspot_get_company` | Get a company by ID |
| `hubspot_create_company` | Create a new company |
| `hubspot_update_company` | Update an existing company |
| `hubspot_search_deals` | Search CRM deals |
| `hubspot_get_deal` | Get a deal by ID |
| `hubspot_create_deal` | Create a new deal |
| `hubspot_update_deal` | Update an existing deal |
| `hubspot_delete_object` | Archive a CRM object by type and ID |
| `hubspot_list_associations` | List associations between CRM objects |
| `hubspot_create_association` | Create an association between CRM objects |

## Usage

### Search contacts

```python
result = hubspot_search_contacts(
    query="alice",
    properties=["email", "firstname", "lastname"],
    limit=10,
)
```

### Create a company

```python
result = hubspot_create_company(
    properties={
        "name": "Aden Labs",
        "domain": "adenhq.com",
    },
)
```

### Create a deal

```python
result = hubspot_create_deal(
    properties={
        "dealname": "Enterprise Expansion",
        "pipeline": "default",
        "dealstage": "appointmentscheduled",
    },
)
```

## Scope

- Contact, company, and deal search and record retrieval
- CRM object creation, updates, and archival
- Association management across CRM records

## API Reference

- [HubSpot CRM API](https://developers.hubspot.com/docs/api/crm)
