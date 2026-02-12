# Microsoft Dynamics 365 Tools

This toolset allows Aden agents to interact with Microsoft Dynamics 365 (CRM/ERP) via the Dataverse Web API (OData v4).

## Configuration

The integration requires Azure AD OAuth2 Client Credentials.

### Credentials Setup
1. Go to the [Azure Portal](https://portal.azure.com/) -> **App Registrations**.
2. Create a **New registration**.
3. Note the **Application (client) ID** and **Directory (tenant) ID**.
4. Go to **Certificates & secrets** and create a new **Client secret**. Note its value.
5. Go to **API permissions**, add **Dynamics CRM**, and select `user_impersonation`.
6. Identity your environment URL (e.g., `https://orgb1234.crm.dynamics.com`).

### Environment Variable
Set the following environment variable in your `.env` file:
```bash
DYNAMICS365_CREDENTIALS="tenant_id:client_id:client_secret:environment_url"
```

## Available Tools

- `dynamics365_search_accounts`: Find accounts using OData filters.
- `dynamics365_get_account`: Retrieve a specific account by GUID.
- `dynamics365_create_account`: Create a new account.
- `dynamics365_update_account`: Update account fields.
- `dynamics365_delete_account`: Remove an account.
- `dynamics365_search_contacts`: Find contacts.
- `dynamics365_create_contact`: Add a new contact.
- `dynamics365_search_opportunities`: Search for sales opportunities.
- `dynamics365_create_opportunity`: Create a sales opportunity.
- `dynamics365_check_inventory`: View product details and inventory.
- `dynamics365_search_invoices`: Search billing invoices.

## Implementation Details

- **API**: Dataverse Web API v9.2.
- **Authentication**: Azure AD OAuth2 `client_credentials` flow.
- **Protocol**: OData v4.
- **Returns**: JSON objects representing Dynamics 365 entities.
