# Salesforce Tool

Query, create, update, and manage Salesforce CRM records via the Salesforce REST API.

## Tools

| Tool | Description |
|------|-------------|
| `salesforce_soql_query` | Execute a SOQL query |
| `salesforce_get_record` | Get a record by object type and ID |
| `salesforce_create_record` | Create a new record |
| `salesforce_update_record` | Update an existing record |
| `salesforce_delete_record` | Delete a record |
| `salesforce_describe_object` | Get metadata and fields for an object type |
| `salesforce_list_objects` | List all available Salesforce objects |
| `salesforce_search_records` | Search records using SOSL |
| `salesforce_get_record_count` | Get the total count of records for an object |

## Setup

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `SALESFORCE_ACCESS_TOKEN` | OAuth2 access token |
| `SALESFORCE_INSTANCE_URL` | Salesforce instance URL (e.g., `https://yourorg.salesforce.com`) |

Get credentials at: [Salesforce Connected Apps](https://help.salesforce.com/s/articleView?id=sf.connected_app_overview.htm)

## Usage Examples

### Query contacts
```python
salesforce_soql_query(query="SELECT Id, Name, Email FROM Contact WHERE Email != null LIMIT 10")
```

### Create a lead
```python
salesforce_create_record(
    object_type="Lead",
    fields={"FirstName": "Jane", "LastName": "Doe", "Company": "Acme"},
)
```

### Update an opportunity
```python
salesforce_update_record(
    object_type="Opportunity",
    record_id="006xx000001234",
    fields={"StageName": "Closed Won", "Amount": 50000},
)
```

### Search across objects
```python
salesforce_search_records(search_query="FIND {Acme} IN ALL FIELDS RETURNING Account, Contact")
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "Salesforce credentials not configured", "help": "Set SALESFORCE_ACCESS_TOKEN and SALESFORCE_INSTANCE_URL environment variables or configure via credential store"}
{"error": "Salesforce API error (HTTP 400): MALFORMED_QUERY"}
{"error": "Request timed out"}
```
