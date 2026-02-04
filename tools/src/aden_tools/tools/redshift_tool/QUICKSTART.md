# Redshift Tool - Quick Start Guide

Get up and running with the Redshift integration in 5 minutes.

## Prerequisites

- Python 3.11+
- AWS account with Redshift cluster
- AWS credentials with Redshift Data API access

## Installation

### 1. Install boto3

```bash
cd tools
uv add boto3

# Or using pip
pip install boto3
```

### 2. Configure AWS Credentials

**Quick setup (environment variables)**:

```bash
export AWS_ACCESS_KEY_ID="AKIAIOSFODNN7EXAMPLE"
export AWS_SECRET_ACCESS_KEY="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
export REDSHIFT_CLUSTER_IDENTIFIER="my-cluster"
export REDSHIFT_DATABASE="dev"
export AWS_REGION="us-east-1"
```

**Get your AWS credentials**:
1. Go to https://console.aws.amazon.com/iam/
2. Navigate to **Users** → Your user → **Security credentials**
3. Click **Create access key**
4. Save the Access Key ID and Secret Access Key

## Basic Usage

### List Database Schemas

```python
from aden_tools.tools.redshift_tool import redshift_list_schemas

# List all schemas
schemas = redshift_list_schemas()
print(f"Found {schemas['count']} schemas:")
for schema in schemas['schemas']:
    print(f"  - {schema}")
```

Output:
```
Found 3 schemas:
  - public
  - sales
  - analytics
```

### List Tables in a Schema

```python
from aden_tools.tools.redshift_tool import redshift_list_tables

# List tables in 'sales' schema
tables = redshift_list_tables(schema="sales")
print(f"Tables in {tables['schema']}:")
for table in tables['tables']:
    print(f"  - {table['name']} ({table['type']})")
```

Output:
```
Tables in sales:
  - customers (BASE TABLE)
  - orders (BASE TABLE)
  - products (BASE TABLE)
```

### Inspect Table Structure

```python
from aden_tools.tools.redshift_tool import redshift_get_table_schema

# Get schema for 'customers' table
schema_info = redshift_get_table_schema(schema="sales", table="customers")
print(f"\nTable: {schema_info['schema']}.{schema_info['table']}")
print(f"Columns ({schema_info['column_count']}):")

for col in schema_info['columns']:
    nullable = "NULL" if col['nullable'] else "NOT NULL"
    print(f"  - {col['name']}: {col['type']} {nullable}")
```

Output:
```
Table: sales.customers
Columns (5):
  - customer_id: integer NOT NULL
  - email: character varying NOT NULL
  - name: character varying NULL
  - created_at: timestamp without time zone NULL
  - updated_at: timestamp without time zone NULL
```

### Execute SQL Queries

#### Simple Query (JSON format)

```python
from aden_tools.tools.redshift_tool import redshift_execute_query

# Query customer data
sql = """
SELECT customer_id, email, name
FROM sales.customers
LIMIT 5
"""

result = redshift_execute_query(sql=sql, format="json")

if "error" not in result:
    print(f"Retrieved {result['row_count']} rows:")
    for row in result['rows']:
        print(f"  {row['customer_id']}: {row['name']} ({row['email']})")
else:
    print(f"Error: {result['error']}")
```

Output:
```
Retrieved 5 rows:
  1: John Doe (john@example.com)
  2: Jane Smith (jane@example.com)
  3: Bob Johnson (bob@example.com)
  4: Alice Williams (alice@example.com)
  5: Charlie Brown (charlie@example.com)
```

#### Analytics Query (CSV format)

```python
sql = """
SELECT
    product_category,
    COUNT(*) as order_count,
    SUM(total_amount) as revenue
FROM sales.orders
WHERE order_date >= CURRENT_DATE - 7
GROUP BY product_category
ORDER BY revenue DESC
"""

result = redshift_execute_query(sql=sql, format="csv")

if "error" not in result:
    print(result['data'])
    # Save to file
    with open("weekly_sales.csv", "w") as f:
        f.write(result['data'])
```

Output:
```
product_category,order_count,revenue
Electronics,145,52340.50
Clothing,203,38920.25
Home & Garden,87,21450.75
```

### Export Query Results

```python
from aden_tools.tools.redshift_tool import redshift_export_query_results

# Export customer segments
sql = """
SELECT
    customer_id,
    total_orders,
    total_spent,
    CASE
        WHEN total_spent > 1000 THEN 'VIP'
        WHEN total_spent > 500 THEN 'Regular'
        ELSE 'Occasional'
    END as customer_tier
FROM customer_analytics
ORDER BY total_spent DESC
"""

result = redshift_export_query_results(sql=sql, format="csv")

if "error" not in result:
    # Upload to S3, send via email, etc.
    print(f"Exported {result['row_count']} customer records")
    # result['data'] contains the CSV string
```

## Using with Hive Agents

### In an Agent's tools.py

```python
from typing import Dict, Any
from aden_tools.tools.redshift_tool import redshift_execute_query

def get_daily_sales_summary() -> Dict[str, Any]:
    """
    Get today's sales summary from Redshift.

    Returns:
        Dictionary with sales metrics
    """
    sql = """
    SELECT
        COUNT(DISTINCT order_id) as total_orders,
        COUNT(DISTINCT customer_id) as unique_customers,
        SUM(total_amount) as total_revenue
    FROM sales.orders
    WHERE order_date = CURRENT_DATE
    """

    result = redshift_execute_query(sql=sql, format="json")

    if "error" in result:
        return {"error": result["error"]}

    if result["row_count"] > 0:
        return {
            "date": "today",
            "metrics": result["rows"][0]
        }

    return {"error": "No sales data found"}
```

### In an Agent's agent.json

```json
{
  "nodes": [
    {
      "node_id": "check_inventory",
      "name": "Check Low Inventory",
      "node_type": "function",
      "tools": ["redshift_execute_query"],
      "system_prompt": "Query Redshift to find products with low inventory",
      "input_keys": ["threshold"],
      "output_keys": ["low_stock_products"]
    }
  ]
}
```

## Common Use Cases

### 1. Daily Report Generation

```python
# Generate and send daily sales report
sql = """
SELECT
    product_name,
    SUM(quantity) as units_sold,
    SUM(revenue) as total_revenue
FROM daily_sales_view
WHERE sale_date = CURRENT_DATE
GROUP BY product_name
ORDER BY total_revenue DESC
LIMIT 10
"""

result = redshift_execute_query(sql=sql, format="json")

# Send via email
from aden_tools.tools.email_tool import send_email

email_body = "<h2>Top 10 Products Today</h2><ul>"
for row in result['rows']:
    email_body += f"<li>{row['product_name']}: ${row['total_revenue']:,.2f} ({row['units_sold']} units)</li>"
email_body += "</ul>"

send_email(
    to="team@company.com",
    subject="Daily Sales Report",
    html=email_body
)
```

### 2. Inventory Alerts

```python
# Check for low inventory
sql = """
SELECT warehouse, product_name, current_stock, reorder_level
FROM inventory
WHERE current_stock < reorder_level
"""

result = redshift_execute_query(sql=sql)

if result['row_count'] > 0:
    # Send Slack notification
    message = f"⚠️ Low inventory alert: {result['row_count']} products need reordering"
    # ... send to Slack
```

### 3. Customer Analytics

```python
# Find high-value customers
sql = """
SELECT
    customer_id,
    customer_name,
    total_lifetime_value,
    last_purchase_date
FROM customer_analytics
WHERE total_lifetime_value > 5000
AND last_purchase_date >= CURRENT_DATE - 30
ORDER BY total_lifetime_value DESC
"""

result = redshift_execute_query(sql=sql, format="csv")

# Export to Google Sheets or CRM
```

## Error Handling

Always check for errors:

```python
result = redshift_execute_query(sql="SELECT * FROM my_table")

if "error" in result:
    print(f"Query failed: {result['error']}")
    if "help" in result:
        print(f"Suggestion: {result['help']}")
else:
    # Process results
    for row in result['rows']:
        print(row)
```

Common errors:
- `AWS credentials not configured` - Set environment variables or use credential store
- `Redshift cluster identifier not configured` - Set `REDSHIFT_CLUSTER_IDENTIFIER`
- `Only SELECT queries are allowed` - Use SELECT instead of INSERT/UPDATE/DELETE
- `Query timeout` - Increase timeout parameter or optimize query

## Security Best Practices

1. **Use read-only credentials** for agent access
2. **Never commit credentials** to version control
3. **Use credential store** in production (not environment variables)
4. **Limit schema access** via IAM policies
5. **Monitor query execution** via CloudTrail

## Performance Tips

1. **Use LIMIT** clause to avoid large result sets:
   ```sql
   SELECT * FROM large_table LIMIT 100
   ```

2. **Increase timeout** for complex queries:
   ```python
   result = redshift_execute_query(sql=sql, timeout=120)  # 2 minutes
   ```

3. **Filter early** with WHERE clauses:
   ```sql
   SELECT * FROM orders WHERE date >= CURRENT_DATE - 7
   ```

4. **Use appropriate format**:
   - Use CSV for large exports
   - Use JSON for small, structured data

## Troubleshooting

### "boto3 is required"
```bash
pip install boto3
```

### "AWS credentials not configured"
```bash
# Verify credentials are set
echo $AWS_ACCESS_KEY_ID
echo $AWS_SECRET_ACCESS_KEY
echo $REDSHIFT_CLUSTER_IDENTIFIER
echo $REDSHIFT_DATABASE
```

### "Query timeout after 30 seconds"
```python
# Increase timeout
result = redshift_execute_query(sql=sql, timeout=120)
```

### "Permission denied for schema"
```sql
-- Grant permissions to your DB user
GRANT USAGE ON SCHEMA sales TO myuser;
GRANT SELECT ON ALL TABLES IN SCHEMA sales TO myuser;
```

## Next Steps

- Read the full [README.md](README.md) for detailed documentation
- Check out [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) for technical details
- See example agents in `/examples`
- Join our [Discord community](https://discord.com/invite/MXE49hrKDk)

## Support

- **Issues**: https://github.com/adenhq/hive/issues
- **Discord**: https://discord.com/invite/MXE49hrKDk
- **Docs**: `/docs`

---

**Happy querying!** 🐝
