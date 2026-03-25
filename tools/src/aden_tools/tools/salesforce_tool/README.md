# Salesforce Tool

Manage Leads, Contacts, Opportunities, and run SOQL queries via the Salesforce REST API.

## Supported Actions

- **salesforce_soql_query** – Execute SOQL queries against any object
- **salesforce_get_record** / **salesforce_create_record** / **salesforce_update_record** / **salesforce_delete_record** – Record CRUD
- **salesforce_describe_object** – Get object schema (fields, types, relationships)
- **salesforce_list_objects** – List all available SObjects
- **salesforce_search_records** – Full-text SOSL search across objects
- **salesforce_get_record_count** – Count records matching a filter

## Setup

1. Create a Connected App in Salesforce and obtain an OAuth2 access token.

2. Set the required environment variables:
   ```bash
   export SALESFORCE_ACCESS_TOKEN=your-oauth2-access-token
   export SALESFORCE_INSTANCE_URL=https://your-instance.salesforce.com
   ```

## Use Case

Example: "Query all Opportunities closing this quarter with amount over $50K, update their stage to 'Negotiation', and create a summary report."
