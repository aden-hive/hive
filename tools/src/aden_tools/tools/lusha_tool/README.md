# Lusha Tool

B2B contact and company enrichment via the Lusha API.

## Tools

| Tool | Description |
|------|-------------|
| `lusha_enrich_person` | Enrich a contact by email or LinkedIn URL |
| `lusha_enrich_company` | Enrich a company by domain |
| `lusha_search_people` | Search prospects using role/location filters |
| `lusha_search_companies` | Search companies using firmographic filters |
| `lusha_get_signals` | Retrieve contact/company signals from IDs |
| `lusha_get_account_usage` | Retrieve current API credit usage |

## Authentication

Requires a Lusha API key passed via `LUSHA_API_KEY` environment variable or the credential store.

OpenAPI docs: https://docs.lusha.com/apis/openapi

## Endpoints Used

- `GET /v2/person`
- `GET /v2/company`
- `POST /prospecting/contact/search`
- `POST /prospecting/company/search`
- `POST /api/signals/contacts` (signals by contact IDs)
- `POST /api/signals/companies` (signals by company IDs)

## Error Handling

Returns error dicts for common failure modes:

- `401` - Invalid API key
- `403` - Insufficient permissions/plan access
- `404` - Resource not found
- `429` - Rate limit or credit limit reached
