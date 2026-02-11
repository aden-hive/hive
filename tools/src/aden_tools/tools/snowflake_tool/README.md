# Snowflake Tool

This tool integrates with Snowflake Data Cloud using the native SQL API and Key-Pair Authentication (JWT). It allows agents to execute SQL queries, describe objects, and insert data directly into Snowflake without requiring an external MCP server.

## Features

- **Query Execution**: Execute standard SQL queries (`snowflake_query`).
- **Schema Inspection**: Describe tables, views, and other objects (`snowflake_describe`).
- **Data Insertion**: Insert rows into tables (`snowflake_insert`).

## Configuration

Required credentials can be provided via environment variables or the Aden credential manager:

| Variable | Description | Required | Sourced From |
|----------|-------------|----------|--------------|
| `SNOWFLAKE_ACCOUNT` | Account Identifier (e.g. `xy12345.us-east-1`) | Yes | Env / Cred Store |
| `SNOWFLAKE_USER` | Snowflake Username | Yes | Env / Cred Store |
| `SNOWFLAKE_PRIVATE_KEY` | Private Key (PEM format) | Yes | Env / Cred Store |
| `SNOWFLAKE_DATABASE` | Default Database | No | Env / Cred Store |
| `SNOWFLAKE_SCHEMA` | Default Schema | No | Env / Cred Store |
| `SNOWFLAKE_WAREHOUSE` | Default Warehouse | No | Env / Cred Store |

### Setting up Key-Pair Authentication

1.  **Generate Key Pair locally**:
    ```bash
    openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
    openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
    ```

2.  **Assign Public Key to Snowflake User**:
    ```sql
    ALTER USER <user_name> SET RSA_PUBLIC_KEY='<public_key_content>';
    ```

3.  **Configure Agent**:
    Set `SNOWFLAKE_PRIVATE_KEY` to the content of `rsa_key.p8`.

## Usage

### In Agents
You can use these tools in your agent definition by referencing them in the `tools` list:

```json
{
  "tools": ["snowflake_query", "snowflake_describe"]
}
```

### Python Example
```python
from aden_tools.tools.snowflake_tool import register_tools
from fastmcp import FastMCP

mcp = FastMCP("my-agent")
register_tools(mcp)

# Tools are now registered and available to the agent
```
