# HubSpot CRM Tool

The HubSpot tool provides Aden Hive agents with the ability to manage Contacts, Companies, and Deals within the HubSpot CRM using the [HubSpot API v3](https://developers.hubspot.com/docs/api/crm).

## Features

- **Multi-Object Support**: Full CRUD (Create, Read, Update, Delete/Search) operations for Contacts, Companies, and Deals.
- **Advanced Search**: Search for CRM objects using queries across multiple properties.
- **Flexible Authentication**: Supports HubSpot Private App access tokens and OAuth2 tokens via the Hive credential store.
- **Multi-Account Support**: Manage multiple HubSpot accounts by using aliases in the credential store.

## Configuration

The tool requires a HubSpot access token. You can provide it in two ways:

1. **Environment Variable**: Set `HUBSPOT_ACCESS_TOKEN` in your environment for a single default account.
2. **Credential Store**: Add a credential named `hubspot` to the Hive credential store. 
   - To support multiple accounts, use aliases (e.g., `hubspot:prod`, `hubspot:sandbox`).

## Tools

### Contacts
- `hubspot_search_contacts`: Search for contacts by name, email, or phone.
- `hubspot_get_contact`: Retrieve a specific contact by ID.
- `hubspot_create_contact`: Create a new contact with custom properties.
- `hubspot_update_contact`: Update existing contact properties.

### Companies
- `hubspot_search_companies`: Search for companies by name or domain.
- `hubspot_get_company`: Retrieve a specific company by ID.
- `hubspot_create_company`: Create a new company record.
- `hubspot_update_company`: Update existing company properties.

### Deals
- `hubspot_search_deals`: Search for deals by name or stage.
- `hubspot_get_deal`: Retrieve a specific deal by ID.
- `hubspot_create_deal`: Create a new deal with amount and stage.
- `hubspot_update_deal`: Update existing deal properties.

## Usage Notes

When searching or creating objects, you can specify which `properties` to return in the response. By default, the tool returns standard properties like `email`, `firstname`, and `lastname` for contacts.
