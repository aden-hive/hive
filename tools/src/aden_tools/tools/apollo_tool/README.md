# Apollo.io Tool

B2B contact and company data enrichment via the Apollo.io API.

## Tools

| Tool | Description |
|------|-------------|
| `apollo_enrich_person` | Enrich a contact by email, LinkedIn URL, or name+domain |
| `apollo_enrich_company` | Enrich a company by domain |
| `apollo_search_people` | Search contacts with filters (titles, seniorities, locations, etc.) |
| `apollo_search_companies` | Search companies with filters (industries, employee counts, etc.) |

## Authentication

Requires an Apollo.io API key passed via `APOLLO_API_KEY` environment variable or the credential store.

**How to get an API key:**

1. Sign up or log in at https://app.apollo.io/
2. Go to Settings > Integrations > API
3. Click "Connect" to generate your API key
4. Copy the API key

## Pricing

| Plan | Price | Export Credits/month |
|------|-------|---------------------|
| Free | $0 | 10 |
| Basic | $49/user/mo | 1,000 |
| Professional | $79/user/mo | 2,000 |
| Overage | - | $0.20/credit |

## Error Handling

Returns error dicts for common failure modes:

- `401` - Invalid API key
- `403` - Insufficient credits or permissions
- `404` - Resource not found
- `422` - Invalid parameters
- `429` - Rate limit exceeded
