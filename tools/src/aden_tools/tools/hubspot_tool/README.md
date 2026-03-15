# HubSpot Tool

Manage HubSpot CRM contacts, companies, deals, and associations using the HubSpot API v3/v4.

## Credentials

| Credential key | Description |
|---|---|
| `hubspot_access_token` | Private App access token from your HubSpot developer account |

### Getting an Access Token

1. Go to [HubSpot Developer Portal](https://developers.hubspot.com/)
2. Create or open a Private App under **Settings → Integrations → Private Apps**
3. Grant the required scopes (see below)
4. Copy the generated access token

Alternatively, set the `HUBSPOT_ACCESS_TOKEN` environment variable directly.

### Required Scopes

| Operation | Scopes needed |
|---|---|
| Read contacts/companies/deals | `crm.objects.contacts.read`, `crm.objects.companies.read`, `crm.objects.deals.read` |
| Create/update/delete | `crm.objects.contacts.write`, `crm.objects.companies.write`, `crm.objects.deals.write` |
| Associations | `crm.objects.contacts.read`, `crm.objects.companies.read` |

## Available Tools

### `hubspot_search`
Search for CRM objects (contacts, companies, deals, etc.) by keyword.

```
hubspot_search(object_type="contacts", query="Acme Corp", limit=10)
```

### `hubspot_get`
Retrieve a single CRM object by its ID.

```
hubspot_get(object_type="contacts", object_id="12345")
```

### `hubspot_create`
Create a new CRM object with specified properties.

```
hubspot_create(
  object_type="contacts",
  properties={"firstname": "Jane", "lastname": "Doe", "email": "jane@example.com"}
)
```

### `hubspot_update`
Update properties on an existing CRM object.

```
hubspot_update(
  object_type="contacts",
  object_id="12345",
  properties={"phone": "+1-555-0100"}
)
```

### `hubspot_delete`
Archive (soft-delete) a CRM object.

```
hubspot_delete(object_type="contacts", object_id="12345")
```

### `hubspot_list_associations`
List all objects associated with a given object.

```
hubspot_list_associations(
  from_object_type="contacts",
  from_object_id="12345",
  to_object_type="companies"
)
```

## Supported Object Types

`contacts`, `companies`, `deals`, `tickets`, `products`, `line_items`, `quotes`

## Example Agent Prompt

```
Search HubSpot for all contacts at "Acme Corp", then create a new deal
linked to the company with a close date of 2025-12-31 and an amount of $50,000.
```

## API Reference

- [CRM Objects API v3](https://developers.hubspot.com/docs/api/crm/crm-custom-objects)
- [Associations API v4](https://developers.hubspot.com/docs/api/crm/associations)
