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

Get a token at: [HubSpot Developer Portal](https://developers.hubspot.com/docs/api/private-apps)

### Option A: Environment variable (quickest)

```bash
export HUBSPOT_ACCESS_TOKEN=your-hubspot-access-token
```

### Option B: Aden Platform (OAuth)

If you prefer OAuth (auto-refresh + multi-account), set `ADEN_API_KEY`:

```bash
export ADEN_API_KEY=your-aden-api-key
```

Then connect HubSpot at https://hive.adenhq.com/connect/hubspot.
Hive will sync the token into the credential store at runtime.

### Option C: Credential store (local)

Alternatively, configure credentials in the credential store (`CredentialStoreAdapter`):
- credential id: `hubspot`
- key: `access_token`

Supports multi-account via the `account` parameter when using the credential store (Aden OAuth or local aliases).

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
