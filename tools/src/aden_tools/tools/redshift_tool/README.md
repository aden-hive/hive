# Redshift Tool

Query and manage Amazon Redshift data warehouse within the Aden agent framework.

## Overview

Amazon Redshift is a widely used cloud-based data warehouse that supports large-scale analytics and fast SQL querying. This tool enables Hive agents to:

- Execute SQL queries for analytics and reporting
- List schemas, tables, and inspect table metadata
- Export query results in JSON or CSV format
- Automate workflows based on data insights

## Installation

The Redshift tool requires `boto3` (AWS SDK for Python):

```bash
# Install boto3
pip install boto3

# Or add to your project dependencies
uv add boto3
```

## Setup

### AWS Credentials

You need AWS credentials with permissions to access Redshift Data API.

#### Option 1: Environment Variables (Quick Start)

```bash
export AWS_ACCESS_KEY_ID="your-access-key-id"
export AWS_SECRET_ACCESS_KEY="your-secret-access-key"
export AWS_REGION="us-east-1"  # Optional, defaults to us-east-1
export REDSHIFT_CLUSTER_IDENTIFIER="your-cluster-name"
export REDSHIFT_DATABASE="your-database-name"
export REDSHIFT_DB_USER="your-db-user"  # Optional, uses IAM if not provided
```

#### Option 2: Credential Store (Recommended for Production)

Configure via Hive's credential store:

```python
from framework.credentials import CredentialStore

store = CredentialStore()
store.set("redshift", {
    "aws_access_key_id": "your-access-key-id",
    "aws_secret_access_key": "your-secret-access-key",
    "cluster_identifier": "your-cluster-name",
    "database": "your-database-name",
    "region": "us-east-1",
    "db_user": "your-db-user"  # Optional
})
```

### AWS IAM Permissions

Your IAM user or role needs the following permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "redshift-data:ExecuteStatement",
        "redshift-data:DescribeStatement",
        "redshift-data:GetStatementResult",
        "redshift:GetClusterCredentials"
      ],
      "Resource": "*"
    }
  ]
}
```

**Security Best Practice**: Create a dedicated IAM user with read-only database permissions for agent access.

### Getting AWS Credentials

1. Sign in to [AWS Console](https://console.aws.amazon.com/)
2. Go to **IAM** → **Users**
3. Create a new user or select an existing one
4. Go to **Security credentials** tab
5. Click **Create access key**
6. Choose "Application running outside AWS"
7. Copy the Access Key ID and Secret Access Key

**Important**: Store credentials securely. Never commit them to version control.

## Available Functions

### Schema Discovery

#### `redshift_list_schemas`

List all schemas in the Redshift database (excluding system schemas).

**Parameters:** None

**Returns:**
```python
{
    "schemas": ["public", "sales", "analytics", "marketing"],
    "count": 4
}
```

**Example:**
```python
schemas = redshift_list_schemas()
print(f"Found {schemas['count']} schemas")
for schema in schemas['schemas']:
    print(f"  - {schema}")
```

---

#### `redshift_list_tables`

List all tables in a specific schema.

**Parameters:**
- `schema` (str): Schema name (e.g., "public", "sales")

**Returns:**
```python
{
    "schema": "sales",
    "tables": [
        {"name": "customers", "type": "BASE TABLE"},
        {"name": "orders", "type": "BASE TABLE"},
        {"name": "products", "type": "BASE TABLE"}
    ],
    "count": 3
}
```

**Example:**
```python
# List all tables in the sales schema
tables = redshift_list_tables(schema="sales")
print(f"Tables in {tables['schema']}:")
for table in tables['tables']:
    print(f"  - {table['name']} ({table['type']})")
```

---

#### `redshift_get_table_schema`

Get detailed schema and metadata for a specific table.

**Parameters:**
- `schema` (str): Schema name
- `table` (str): Table name

**Returns:**
```python
{
    "schema": "sales",
    "table": "customers",
    "columns": [
        {
            "name": "customer_id",
            "type": "integer",
            "max_length": null,
            "nullable": false,
            "default": null
        },
        {
            "name": "email",
            "type": "character varying",
            "max_length": 255,
            "nullable": false,
            "default": null
        },
        {
            "name": "created_at",
            "type": "timestamp without time zone",
            "max_length": null,
            "nullable": true,
            "default": "now()"
        }
    ],
    "column_count": 3
}
```

**Example:**
```python
# Inspect table structure
schema_info = redshift_get_table_schema(schema="sales", table="customers")
print(f"Table: {schema_info['schema']}.{schema_info['table']}")
print(f"Columns ({schema_info['column_count']}):")
for col in schema_info['columns']:
    nullable = "NULL" if col['nullable'] else "NOT NULL"
    print(f"  - {col['name']}: {col['type']} {nullable}")
```

---

### Query Execution

#### `redshift_execute_query`

Execute a read-only SQL query (SELECT statements only for security).

**Parameters:**
- `sql` (str): SQL SELECT query to execute
- `format` (str, optional): Output format - "json" (default) or "csv"
- `timeout` (int, optional): Query timeout in seconds (default: 30)

**Returns (JSON format):**
```python
{
    "format": "json",
    "columns": ["customer_id", "email", "total_orders"],
    "rows": [
        {"customer_id": 1, "email": "john@example.com", "total_orders": 5},
        {"customer_id": 2, "email": "jane@example.com", "total_orders": 3},
        {"customer_id": 3, "email": "alice@example.com", "total_orders": 8}
    ],
    "row_count": 3,
    "statement_id": "abc-123-xyz"
}
```

**Returns (CSV format):**
```python
{
    "format": "csv",
    "data": "customer_id,email,total_orders\n1,john@example.com,5\n2,jane@example.com,3\n3,alice@example.com,8",
    "row_count": 3,
    "statement_id": "abc-123-xyz"
}
```

**Example:**
```python
# Execute a simple query
result = redshift_execute_query(
    sql="SELECT customer_id, email, COUNT(*) as order_count FROM orders GROUP BY customer_id, email LIMIT 10",
    format="json"
)

if "error" not in result:
    print(f"Retrieved {result['row_count']} rows")
    for row in result['rows']:
        print(f"Customer {row['customer_id']}: {row['order_count']} orders")
else:
    print(f"Error: {result['error']}")
```

**Security Note**: This function only accepts SELECT queries by default to prevent accidental data modifications. INSERT, UPDATE, DELETE, and other DML/DDL statements will be rejected.

---

#### `redshift_export_query_results`

Execute a query and export results optimized for downstream workflows.

**Parameters:**
- `sql` (str): SQL SELECT query to execute
- `format` (str, optional): Export format - "csv" (default) or "json"

**Returns:**
```python
{
    "format": "csv",
    "data": "product_id,product_name,inventory_count\n101,Widget A,150\n102,Widget B,75\n103,Widget C,220",
    "row_count": 3,
    "statement_id": "xyz-789"
}
```

**Example:**
```python
# Export inventory data for processing
result = redshift_export_query_results(
    sql="SELECT product_id, product_name, inventory_count FROM inventory WHERE inventory_count < 100",
    format="csv"
)

if "error" not in result:
    # Save to file or send to another system
    with open("low_inventory.csv", "w") as f:
        f.write(result['data'])
    print(f"Exported {result['row_count']} products with low inventory")
```

---

## Error Handling

All functions return a dict with an `error` key if something goes wrong:

```python
{
    "error": "AWS credentials not configured",
    "help": "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables..."
}
```

Common errors:
- `AWS credentials not configured` - Missing AWS access keys
- `Redshift cluster identifier not configured` - Missing cluster name
- `Redshift database not configured` - Missing database name
- `Query failed` - SQL execution error (check syntax, permissions, table names)
- `Query timeout after N seconds` - Query took too long to execute
- `Only SELECT queries are allowed` - Attempted to run non-SELECT statement

## Use Cases

### Automated Reporting

Generate daily sales reports and send via email:

```python
# Query today's sales
sql = """
SELECT
    product_category,
    SUM(revenue) as total_revenue,
    COUNT(DISTINCT customer_id) as unique_customers
FROM sales
WHERE date = CURRENT_DATE
GROUP BY product_category
ORDER BY total_revenue DESC
"""

result = redshift_execute_query(sql=sql, format="json")

if "error" not in result:
    # Generate email report
    report = "Daily Sales Report\\n\\n"
    for row in result['rows']:
        report += f"{row['product_category']}: ${row['total_revenue']:,.2f} ({row['unique_customers']} customers)\\n"

    send_email(
        to="team@company.com",
        subject="Daily Sales Report",
        html=f"<pre>{report}</pre>"
    )
```

### Inventory Monitoring with Slack Alerts

Monitor inventory levels and alert team when thresholds are exceeded:

```python
# Check low inventory across warehouses
sql = """
SELECT
    warehouse_name,
    product_name,
    current_stock,
    minimum_stock
FROM inventory_view
WHERE current_stock < minimum_stock
"""

result = redshift_execute_query(sql=sql)

if result['row_count'] > 0:
    # Send Slack alert
    message = f"⚠️ Low Inventory Alert: {result['row_count']} products below minimum stock\\n\\n"
    for item in result['rows']:
        message += f"• {item['product_name']} at {item['warehouse_name']}: {item['current_stock']}/{item['minimum_stock']}\\n"

    slack_send_message(channel="#inventory", text=message)
```

### Data Pipeline Integration

Export query results for downstream data processing:

```python
# Export customer cohort data
sql = """
SELECT
    customer_id,
    signup_date,
    total_lifetime_value,
    last_purchase_date,
    CASE
        WHEN total_lifetime_value > 1000 THEN 'High Value'
        WHEN total_lifetime_value > 500 THEN 'Medium Value'
        ELSE 'Low Value'
    END as customer_segment
FROM customer_analytics
WHERE signup_date >= DATEADD(month, -6, CURRENT_DATE)
"""

result = redshift_export_query_results(sql=sql, format="csv")

# Upload to S3, Google Sheets, or other systems
upload_to_s3(
    bucket="analytics-exports",
    key="cohorts/latest.csv",
    data=result['data']
)
```

### Schema Documentation

Automatically generate database documentation:

```python
# Get all schemas
schemas = redshift_list_schemas()

documentation = "# Database Schema Documentation\\n\\n"

for schema_name in schemas['schemas']:
    documentation += f"## Schema: {schema_name}\\n\\n"

    # Get tables in schema
    tables = redshift_list_tables(schema=schema_name)

    for table in tables['tables']:
        documentation += f"### Table: {table['name']}\\n\\n"

        # Get table schema
        schema_info = redshift_get_table_schema(schema=schema_name, table=table['name'])

        documentation += "| Column | Type | Nullable | Default |\\n"
        documentation += "|--------|------|----------|---------|\\n"

        for col in schema_info['columns']:
            nullable = "Yes" if col['nullable'] else "No"
            default = col['default'] or "-"
            documentation += f"| {col['name']} | {col['type']} | {nullable} | {default} |\\n"

        documentation += "\\n"

# Save documentation
with open("database_schema.md", "w") as f:
    f.write(documentation)
```

### Analytics Dashboard Data

Fetch metrics for dashboard visualization:

```python
# Get key business metrics
queries = {
    "daily_revenue": "SELECT SUM(amount) as revenue FROM orders WHERE date = CURRENT_DATE",
    "active_users": "SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE date = CURRENT_DATE",
    "conversion_rate": "SELECT (COUNT(DISTINCT purchaser_id)::float / COUNT(DISTINCT visitor_id)) * 100 as rate FROM funnel_view WHERE date = CURRENT_DATE"
}

metrics = {}
for metric_name, sql in queries.items():
    result = redshift_execute_query(sql=sql)
    if "error" not in result and result['row_count'] > 0:
        metrics[metric_name] = result['rows'][0]

print("Today's Metrics:")
print(f"  Revenue: ${metrics['daily_revenue']['revenue']:,.2f}")
print(f"  Active Users: {metrics['active_users']['count']:,}")
print(f"  Conversion Rate: {metrics['conversion_rate']['rate']:.2f}%")
```

## Security Best Practices

1. **Read-Only Access**: The MVP defaults to SELECT-only queries to prevent accidental data changes
2. **IAM Roles**: Use IAM roles with minimal required permissions
3. **Credential Storage**: Store credentials in Hive's encrypted credential store, not in code
4. **SQL Injection**: While the tool has basic validation, always sanitize user inputs before constructing queries
5. **Audit Logging**: Enable CloudTrail to log all Redshift Data API calls
6. **Network Security**: Use VPC endpoints for private connectivity to Redshift

## Performance Tips

1. **Use LIMIT**: Always use LIMIT clause for exploratory queries to avoid large result sets
2. **Optimize Queries**: Use appropriate WHERE clauses and indexes
3. **Timeout Settings**: Adjust timeout parameter for long-running queries
4. **Result Caching**: Cache frequently accessed query results in your agent
5. **Batch Operations**: Group related queries together to minimize API calls

## Troubleshooting

### "boto3 is required for Redshift integration"

Install boto3:
```bash
pip install boto3
# or
uv add boto3
```

### "AWS credentials not configured"

Ensure AWS credentials are set via environment variables or credential store. Verify with:
```bash
echo $AWS_ACCESS_KEY_ID
echo $AWS_SECRET_ACCESS_KEY
```

### "Query timeout after 30 seconds"

For long-running queries, increase the timeout:
```python
result = redshift_execute_query(sql=sql, timeout=120)  # 2 minutes
```

### "Query failed: permission denied for schema"

Your database user lacks permissions. Grant access:
```sql
GRANT USAGE ON SCHEMA sales TO your_db_user;
GRANT SELECT ON ALL TABLES IN SCHEMA sales TO your_db_user;
```

### "Resource not found" or "Cluster not available"

Verify your cluster identifier and region:
```python
import boto3
client = boto3.client('redshift', region_name='us-east-1')
clusters = client.describe_clusters()
for cluster in clusters['Clusters']:
    print(f"Cluster: {cluster['ClusterIdentifier']} - Status: {cluster['ClusterStatus']}")
```

## API Reference

- [Redshift Data API Documentation](https://docs.aws.amazon.com/redshift/latest/mgmt/data-api.html)
- [Boto3 Redshift Data Client](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/redshift-data.html)
- [AWS IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)

## Future Enhancements

Planned for future releases:
- Scheduled query execution
- Query result pagination for large datasets
- Materialized view support
- Query performance metrics
- Write operations (INSERT, UPDATE, DELETE) with explicit opt-in
- Parameterized queries
- Result set caching
- Integration with AWS Secrets Manager for credential management

## Related Tools

- `csv_tool` - Process CSV exports from Redshift
- `email_tool` - Send query results via email
- `web_search_tool` - Enrich Redshift data with web searches

## Support

For issues or questions:
- [GitHub Issues](https://github.com/adenhq/hive/issues)
- [Discord Community](https://discord.com/invite/MXE49hrKDk)
- Documentation: `/docs`
