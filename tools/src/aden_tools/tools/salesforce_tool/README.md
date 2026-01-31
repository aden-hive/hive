# Salesforce CRM Tool

MCP tool for Salesforce: search, get, create, and update **Leads**, **Contacts**, **Accounts**, and **Opportunities** via the Salesforce REST API.

## Configuration

Set both environment variables (or provide via credential store):

- **SALESFORCE_INSTANCE_URL** – e.g. `https://yourdomain.my.salesforce.com` or `https://na1.salesforce.com`
- **SALESFORCE_ACCESS_TOKEN** – Access token from a Connected App (OAuth2 or session)

To create a Connected App and get a token, see [Salesforce REST API](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/).

## Tools

| Tool | Description |
|------|-------------|
| `salesforce_search_leads` | Search leads by name (SOQL) |
| `salesforce_get_lead` | Get lead by ID |
| `salesforce_create_lead` | Create lead |
| `salesforce_update_lead` | Update lead |
| `salesforce_search_contacts` | Search contacts by name |
| `salesforce_get_contact` | Get contact by ID |
| `salesforce_create_contact` | Create contact |
| `salesforce_update_contact` | Update contact |
| `salesforce_search_accounts` | Search accounts by name |
| `salesforce_get_account` | Get account by ID |
| `salesforce_create_account` | Create account |
| `salesforce_update_account` | Update account |
| `salesforce_search_opportunities` | Search opportunities by name |
| `salesforce_get_opportunity` | Get opportunity by ID |
| `salesforce_create_opportunity` | Create opportunity |
| `salesforce_update_opportunity` | Update opportunity |

## Example

```python
# After registering with FastMCP and setting env vars:
# salesforce_search_leads(query="acme", limit=5)
# salesforce_create_lead(properties={"LastName": "Smith", "Company": "Acme", "Email": "j@acme.com"})
```
