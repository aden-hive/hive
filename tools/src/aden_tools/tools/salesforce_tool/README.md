# Salesforce Tool

A Model Context Protocol (MCP) tool for interacting with Salesforce CRM.

## Setup

To use this tool, you need a Salesforce Access Token and your Salesforce Instance URL.

### Environment Variables

Set the following environment variables:

- `SALESFORCE_ACCESS_TOKEN`: Your Salesforce OAuth2 access token.
- `SALESFORCE_INSTANCE_URL`: Your Salesforce instance URL (e.g., `https://your-domain.my.salesforce.com`).

## Tools

### `salesforce_search_objects`
Executes a SOQL query.
- `query`: The SOQL query string.

### `salesforce_get_object`
Retrieves a record by ID.
- `object_type`: The API name of the object (e.g., `Account`).
- `object_id`: The 15 or 18-character Salesforce ID.

### `salesforce_create_object`
Creates a new record.
- `object_type`: The API name of the object.
- `data`: A dictionary of field-value pairs.

### `salesforce_update_object`
Updates an existing record.
- `object_type`: The API name of the object.
- `object_id`: The record ID.
- `data`: A dictionary of fields to update.
