# MSSQL Tool

Professional SQL Server database operations for Aden Hive.

## Overview

The MSSQL tool provides secure database access to Microsoft SQL Server with comprehensive operations for querying, updating, schema inspection, and stored procedure execution.

## Features

- **Execute Queries**: Run SELECT statements with automatic result formatting
- **Execute Updates**: Perform INSERT/UPDATE/DELETE with transaction support
- **Schema Inspection**: Get database structure, table metadata, and relationships
- **Stored Procedures**: Execute procedures with parameter passing
- **Secure Credentials**: Uses CredentialStoreAdapter for environment-based auth
- **Connection Pooling**: Efficient connection management
- **Error Handling**: Clear, actionable error messages

## Environment Setup

### Required Variables

```bash
# SQL Server connection details
MSSQL_SERVER=your-server-name        # e.g., "localhost\SQLEXPRESS" or "localhost"
MSSQL_DATABASE=your-database-name    # e.g., "AdenTestDB"

# Authentication (Option 1: SQL Server Authentication)
MSSQL_USERNAME=your-username         # e.g., "sa"
MSSQL_PASSWORD=your-password

# Authentication (Option 2: Windows Authentication)
# Leave MSSQL_USERNAME and MSSQL_PASSWORD empty to use Windows Auth
```

### Setup Methods

#### 1. Using .env file (Recommended for development)

Create a `.env` file in your project root:

```bash
MSSQL_SERVER=localhost\SQLEXPRESS
MSSQL_DATABASE=AdenTestDB
MSSQL_USERNAME=sa
MSSQL_PASSWORD=yourpassword
```

#### 2. Using environment variables

```bash
# Windows PowerShell
$env:MSSQL_SERVER = "localhost\SQLEXPRESS"
$env:MSSQL_DATABASE = "AdenTestDB"
$env:MSSQL_USERNAME = "sa"
$env:MSSQL_PASSWORD = "yourpassword"

# Linux/Mac bash
export MSSQL_SERVER="localhost"
export MSSQL_DATABASE="AdenTestDB"
export MSSQL_USERNAME="sa"
export MSSQL_PASSWORD="yourpassword"
```

### Server Connection Formats

The MSSQL_SERVER variable supports multiple connection formats:

| Format | Example | Use Case |
|--------|---------|----------|
| Local named instance | `localhost\SQLEXPRESS` | Development on local machine |
| Local default | `localhost` | Local SQL Server, default instance |
| Remote IP | `192.168.1.100` | Remote server, default port (1433) |
| Remote IP + Port | `192.168.1.100,1433` | Remote server, custom port |
| Remote named instance | `PRODUCTION\INSTANCE01` | Remote named instance |
| Domain name | `sql-prod.company.com` | Production domain server |
| Domain + Port | `sql-prod.company.com,1433` | Production with custom port |
| Azure SQL | `yourserver.database.windows.net` | Azure SQL Database |
| AWS RDS | `instance.region.rds.amazonaws.com,1433` | AWS RDS for SQL Server |

**Important Notes:**
- Use **comma (`,`)** for ports, not colon - e.g., `server,1433`
- Use **backslash (`\`)** for named instances - e.g., `SERVER\INSTANCE`
- Default port is `1433` - can be omitted when using default
- Named instances discover their port automatically

### Prerequisites


1. **MSSQL Server**: Ensure SQL Server is installed and running
2. **ODBC Driver**: Install [ODBC Driver 17 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
3. **Python Package**: Install the tool with MSSQL support:
   ```bash
   pip install -e ".[mssql]"
   ```

## Tool Functions

### 1. mssql_execute_query

Execute SELECT queries and retrieve results.

**Parameters:**
- `query` (str): SQL SELECT query
- `max_rows` (int, optional): Maximum rows to return (1-10000, default: 1000)

**Returns:**
```python
{
    "columns": ["id", "name", "email"],
    "rows": [
        {"id": 1, "name": "John", "email": "john@example.com"},
        {"id": 2, "name": "Jane", "email": "jane@example.com"}
    ],
    "row_count": 2,
    "truncated": false
}
```

**Example:**
```python
from fastmcp import FastMCP
from aden_tools.tools.mssql_tool import register_tools
from aden_tools.credentials import CredentialStoreAdapter

mcp = FastMCP("my-server")
credentials = CredentialStoreAdapter.with_env_storage()
register_tools(mcp, credentials=credentials)

# Now use via MCP
result = mssql_execute_query(
    query="SELECT * FROM Employees WHERE department_id = 1"
)
```

### 2. mssql_execute_update

Execute INSERT, UPDATE, DELETE, or MERGE operations.

**Parameters:**
- `query` (str): SQL modification query
- `commit` (bool, optional): Whether to commit transaction (default: True)

**Returns:**
```python
{
    "success": true,
    "affected_rows": 5,
    "message": "Successfully affected 5 row(s)"
}
```

**Safety Features:**
- Prevents DELETE without WHERE clause
- Transaction support with automatic rollback on error
- Returns affected row count

**Example:**
```python
result = mssql_execute_update(
    query="""
    UPDATE Employees
    SET salary = salary * 1.1
    WHERE department_id = 2
    """,
    commit=True
)
```

### 3. mssql_get_schema

Inspect database schema and table structure.

**Parameters:**
- `table_name` (str, optional): Specific table to inspect (None = list all tables)
- `include_indexes` (bool, optional): Include index information (default: False)

**Returns (all tables):**
```python
{
    "tables": ["Departments", "Employees"],
    "table_count": 2
}
```

**Returns (specific table):**
```python
{
    "table": "Employees",
    "columns": [
        {
            "name": "employee_id",
            "type": "int",
            "nullable": False,
            "primary_key": True
        },
        {
            "name": "first_name",
            "type": "nvarchar(50)",
            "nullable": False,
            "primary_key": False
        }
    ],
    "column_count": 7,
    "foreign_keys": [
        {
            "column": "department_id",
            "references": "Departments(department_id)"
        }
    ]
}
```

**Example:**
```python
# List all tables
result = mssql_get_schema()

# Get specific table schema
result = mssql_get_schema(
    table_name="Employees",
    include_indexes=True
)
```

### 4. mssql_execute_procedure

Execute stored procedures with parameters.

**Parameters:**
- `procedure_name` (str): Name of stored procedure
- `parameters` (dict, optional): Parameter name-value pairs

**Returns:**
```python
{
    "success": True,
    "procedure": "GetEmployeesByDepartment",
    "result_sets": [
        {
            "columns": ["employee_id", "name", "salary"],
            "rows": [
                {"employee_id": 1, "name": "John", "salary": 75000}
            ]
        }
    ],
    "result_set_count": 1
}
```

**Example:**
```python
result = mssql_execute_procedure(
    procedure_name="GetEmployeesByDepartment",
    parameters={"department_id": 1}
)
```

## Error Handling

All tools return error information in a consistent format:

```python
{
    "error": "Descriptive error message",
    "committed": False  # For update operations
}
```

Common errors:
- **Authentication Failed**: Check MSSQL_USERNAME and MSSQL_PASSWORD
- **Cannot Access Database**: Verify database name and permissions
- **Server Not Found**: Check MSSQL_SERVER value
- **Connection Failed**: Ensure SQL Server is running and ODBC driver is installed

## Security Best Practices

1. **Never hardcode credentials** - Always use environment variables or .env files
2. **Use least privilege** - Grant only necessary database permissions
3. **Validate inputs** - The tool includes query validation and SQL injection prevention
4. **Use transactions** - All updates are wrapped in transactions with automatic rollback
5. **Secure .env files** - Add `.env` to `.gitignore` to prevent credential exposure

## Testing

Test your connection:

```bash
cd tools
python test_mssql_connection.py
```

Expected output shows successful connection, query execution, and data retrieval.

## Integration Example

```python
from fastmcp import FastMCP
from aden_tools.tools import register_all_tools
from aden_tools.credentials import CredentialStoreAdapter

# Create MCP server
mcp = FastMCP("aden-server")

# Set up credentials
credentials = CredentialStoreAdapter.with_env_storage()

# Register all tools (includes MSSQL)
register_all_tools(mcp, credentials=credentials)

# Start server
mcp.run()
```

## Troubleshooting

### ODBC Driver Not Found

Error: `[Microsoft][ODBC Driver Manager] Data source name not found`

Solution: Install ODBC Driver 17 for SQL Server from Microsoft

### Connection Timeout

Error: `Connection timed out`

Solutions:
- Verify SQL Server is running
- Check firewall settings
- Ensure TCP/IP protocol is enabled in SQL Server Configuration Manager
- Verify server name format (use `\\` for instance names)

### Authentication Issues

Error: `Login failed for user`

Solutions:
- Verify username/password are correct
- Ensure SQL Server authentication is enabled
- Check user has access to the specified database
- For Windows Auth, leave USERNAME and PASSWORD empty

## License

This tool is part of the Aden Hive project.
