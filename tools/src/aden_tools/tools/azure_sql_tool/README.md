# Azure SQL Tool

Manage Azure SQL servers, databases, and firewall rules via the Azure Management REST API.

## Tools

| Tool | Description |
|------|-------------|
| `azure_sql_list_servers` | List SQL servers in a subscription or resource group |
| `azure_sql_get_server` | Get details of a specific SQL server |
| `azure_sql_list_databases` | List databases on a SQL server |
| `azure_sql_get_database` | Get details of a specific database |
| `azure_sql_list_firewall_rules` | List firewall rules for a SQL server |

## Setup

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |
| `AZURE_SQL_ACCESS_TOKEN` | Azure Management API bearer token |

To obtain a token:
1. Register an app in Azure AD (Entra ID)
2. Assign SQL DB Contributor or Reader role
3. Obtain a token via client credentials flow with scope `https://management.azure.com/.default`

See: [Azure SQL REST API](https://learn.microsoft.com/en-us/rest/api/sql/)

Note: Access tokens typically expire within 1 hour and require refresh.

## Usage Examples

### List all SQL servers
```python
azure_sql_list_servers()
```

### List servers in a resource group
```python
azure_sql_list_servers(resource_group="my-rg")
```

### Get databases on a server
```python
azure_sql_list_databases(resource_group="my-rg", server_name="my-server")
```

### Check firewall rules
```python
azure_sql_list_firewall_rules(resource_group="my-rg", server_name="my-server")
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "AZURE_SQL_ACCESS_TOKEN and AZURE_SUBSCRIPTION_ID are required"}
{"error": "Azure API error (HTTP 404): Resource not found"}
{"error": "Request timed out"}
```
