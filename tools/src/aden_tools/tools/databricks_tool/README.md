# Databricks Tool

Query Databricks SQL Warehouses and interact with Databricks managed MCP servers.

## Tools

### Custom SQL Tools (Read-Only)

| Tool | Description |
|------|-------------|
| `run_databricks_sql` | Execute read-only SQL queries against a Databricks SQL Warehouse |
| `describe_databricks_table` | Fetch table schema/metadata from Unity Catalog |

### Managed MCP Server Tools

| Tool | Description |
|------|-------------|
| `databricks_mcp_query_sql` | Execute SQL via the managed SQL MCP server |
| `databricks_mcp_query_uc_function` | Execute a Unity Catalog function |
| `databricks_mcp_vector_search` | Query a Vector Search index |
| `databricks_mcp_query_genie` | Query a Genie space with natural language |
| `databricks_mcp_list_tools` | Discover tools on any managed MCP server endpoint |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABRICKS_HOST` | Yes | Workspace URL (e.g., `https://dbc-xxx.cloud.databricks.com`) |
| `DATABRICKS_TOKEN` | Yes | Personal access token (`dapi...`) |
| `DATABRICKS_WAREHOUSE_ID` | No | Default SQL Warehouse ID |

## Usage Examples

### Execute a Read-Only SQL Query

```python
run_databricks_sql(
    sql="SELECT name, COUNT(*) as cnt FROM main.default.users GROUP BY name",
    warehouse_id="abc123def456",
    max_rows=100
)
```

### Describe a Unity Catalog Table

```python
describe_databricks_table(
    catalog="main",
    schema="default",
    table="users"
)
```

### Query via Managed MCP SQL Server

```python
databricks_mcp_query_sql(
    sql="SELECT * FROM main.default.orders LIMIT 10"
)
```

### Execute a Unity Catalog Function

```python
databricks_mcp_query_uc_function(
    catalog="main",
    schema="analytics",
    function_name="get_revenue_summary",
    arguments={"start_date": "2024-01-01"}
)
```

### Search a Vector Index

```python
databricks_mcp_vector_search(
    catalog="prod",
    schema="knowledge_base",
    index_name="docs_index",
    query="How to configure authentication?",
    num_results=5
)
```

### Query a Genie Space

```python
databricks_mcp_query_genie(
    genie_space_id="abc123",
    question="What was the total revenue last quarter?"
)
```

### Discover Available MCP Tools

```python
databricks_mcp_list_tools(
    server_type="functions",
    resource_path="system/ai"
)
```

## Safety Features

- **Read-only enforcement** on `run_databricks_sql`: INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, MERGE, and REPLACE are blocked
- **Row limits**: Configurable max_rows (1–10,000) to prevent large result sets
- **Credential isolation**: Uses CredentialStoreAdapter pattern; secrets never logged

## Error Handling

All tools return structured error dicts with `error` and optional `help` fields. Common errors include:

- **Authentication failure**: Invalid or expired token
- **Permission denied**: Insufficient privileges on the target resource
- **Not found**: Invalid catalog, schema, table, or warehouse ID
- **Missing dependency**: `databricks-sdk` or `databricks-mcp` not installed

## Installation

```bash
pip install 'databricks-sdk>=0.30.0' 'databricks-mcp>=0.1.0'
```

Or via the project's optional dependencies:

```bash
pip install '.[databricks]'
```
