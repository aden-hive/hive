# HubSpot Tool

Manage contacts, companies, deals, and associations using the HubSpot CRM API v3/v4.

## Tools

| Tool | Description |
|------|-------------|
| `hubspot_search_contacts` | Search contacts by name, email, phone |
| `hubspot_get_contact` | Get a contact by ID |
| `hubspot_create_contact` | Create a new contact |
| `hubspot_update_contact` | Update a contact's properties |
| `hubspot_search_companies` | Search companies by name, domain |
| `hubspot_get_company` | Get a company by ID |
| `hubspot_create_company` | Create a new company |
| `hubspot_update_company` | Update a company's properties |
| `hubspot_search_deals` | Search deals by name |
| `hubspot_get_deal` | Get a deal by ID |
| `hubspot_create_deal` | Create a new deal |
| `hubspot_update_deal` | Update a deal's properties |
| `hubspot_delete_object` | Delete (archive) a contact, company, or deal |
| `hubspot_list_associations` | List associations between CRM objects |
| `hubspot_create_association` | Create an association between two objects |

## Setup

Set the following environment variable or use Aden OAuth:

| Variable | Description |
|----------|-------------|
| `HUBSPOT_ACCESS_TOKEN` | HubSpot private app access token |

Alternatively, configure credentials in the Aden credential store:
- `hubspot`

Get a token at: [HubSpot Developer Portal](https://developers.hubspot.com/docs/api/creating-an-app)

Supports multi-account via `account` parameter for Aden OAuth users.

## Usage Examples

### Search contacts
```python
hubspot_search_contacts(query="jane@example.com", properties=["email", "firstname", "lastname"])
```

### Create a deal
```python
hubspot_create_deal(properties={"dealname": "New Partnership", "amount": "50000"})
```

### Link a contact to a company
```python
hubspot_create_association(
    from_object_type="contacts",
    from_object_id="101",
    to_object_type="companies",
    to_object_id="202",
    association_type_id=1,
)
```

### Delete a contact
```python
hubspot_delete_object(object_type="contacts", object_id="101")
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "HubSpot credentials not configured", "help": "Set HUBSPOT_ACCESS_TOKEN or configure via credential store"}
{"error": "Invalid or expired HubSpot access token"}
{"error": "HubSpot rate limit exceeded. Try again later."}
{"error": "Request timed out"}
```
