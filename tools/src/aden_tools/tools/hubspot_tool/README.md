# HubSpot Tool

Manage contacts, companies, and deals via the HubSpot CRM API v3.

## Supported Actions

### Contacts
- **hubspot_search_contacts** / **hubspot_get_contact** / **hubspot_create_contact** / **hubspot_update_contact**

### Companies
- **hubspot_search_companies** / **hubspot_get_company** / **hubspot_create_company** / **hubspot_update_company**

### Deals
- **hubspot_search_deals** / **hubspot_get_deal** / **hubspot_create_deal** / **hubspot_update_deal**

### Associations & Cleanup
- **hubspot_list_associations** / **hubspot_create_association** – Link objects together
- **hubspot_delete_object** – Delete any CRM object by type and ID

## Setup

1. Create a Private App in HubSpot (Settings → Integrations → Private Apps).

2. Set the environment variable:
   ```bash
   export HUBSPOT_ACCESS_TOKEN=your-private-app-token
   ```

## Use Case

Example: "Find all contacts who signed up in the last 7 days, create a deal for each, and associate them with the 'Onboarding' pipeline."
