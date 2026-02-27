# BigQuery Tool

Execute SQL queries and explore datasets in Google BigQuery.

## Features

- **`run_bigquery_query`**: Execute read-only SQL queries and return structured results
- **`describe_dataset`**: List tables and schemas in a dataset for query planning

## Setup

### 1. Install Dependencies

The BigQuery tool requires `google-cloud-bigquery`:

```bash
pip install google-cloud-bigquery>=3.0.0
```

### 2. Configure Authentication

Choose one of the following authentication methods:

#### Option A: Service Account (Recommended for Production)

1. Create a service account in Google Cloud Console
2. Grant the following roles:
   - `BigQuery Data Viewer` (to read data)
   - `BigQuery Job User` (to run queries)
3. Download the JSON key file
4. Set the environment variable:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

#### Option B: Application Default Credentials (For Local Development)

```bash
gcloud auth application-default login
```

### 3. Set Default Project (Optional)

If your queries don't specify a project, set a default:

```bash
export BIGQUERY_PROJECT_ID="your-project-id"
```

## Usage

### Run a Query

```python
result = run_bigquery_query(
    sql="SELECT name, COUNT(*) as count FROM `project.dataset.table` GROUP BY name",
    max_rows=100
)

if result.get("success"):
    for row in result["rows"]:
        print(row)
    print(f"Bytes processed: {result['bytes_processed']}")
else:
    print(f"Error: {result['error']}")
```

### Describe a Dataset

```python
result = describe_dataset(
    dataset_id="my_dataset",
    project_id="my-project"  # optional if BIGQUERY_PROJECT_ID is set
)

if result.get("success"):
    for table in result["tables"]:
        print(f"Table: {table['table_id']}")
        print(f"  Rows: {table['row_count']}")
        for col in table["columns"]:
            print(f"  - {col['name']}: {col['type']}")
else:
    print(f"Error: {result['error']}")
```

## Safety Features

### Read-Only Enforcement

The tool blocks write operations for safety. The following SQL keywords are rejected:

- `INSERT`
- `UPDATE`
- `DELETE`
- `DROP`
- `CREATE`
- `ALTER`
- `TRUNCATE`
- `MERGE`
- `REPLACE`

### Row Limits

- Default limit: 1000 rows
- Maximum limit: 10,000 rows
- Results include `query_truncated: true` if more rows exist

### Cost Awareness

Every query result includes `bytes_processed` so you can monitor BigQuery costs.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_APPLICATION_CREDENTIALS` | No* | Path to service account JSON file |
| `BIGQUERY_PROJECT_ID` | No | Default project ID for queries |

*Required if not using Application Default Credentials (ADC)

## Error Handling

The tool returns structured error responses with helpful messages:

```python
# Authentication error
{
    "error": "BigQuery authentication failed",
    "help": "Set GOOGLE_APPLICATION_CREDENTIALS to your service account JSON path, or run 'gcloud auth application-default login' for local development."
}

# Permission error
{
    "error": "BigQuery permission denied: ...",
    "help": "Ensure your service account has the 'BigQuery Data Viewer' and 'BigQuery Job User' roles."
}

# Write operation blocked
{
    "error": "Write operations are not allowed",
    "help": "Only SELECT queries are permitted. INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, and MERGE are blocked."
}
```

## Example Agent Use Cases

### Analytics Copilot

```python
# Agent receives: "What are the top 10 products by revenue last month?"

# Step 1: Explore the dataset
describe_dataset("sales_data")

# Step 2: Run the query
run_bigquery_query("""
    SELECT product_name, SUM(revenue) as total_revenue
    FROM `project.sales_data.transactions`
    WHERE DATE(transaction_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH)
    GROUP BY product_name
    ORDER BY total_revenue DESC
    LIMIT 10
""")
```

### Data Validation Agent

```python
# Check for data quality issues
run_bigquery_query("""
    SELECT 
        COUNT(*) as total_rows,
        COUNTIF(email IS NULL) as null_emails,
        COUNTIF(NOT REGEXP_CONTAINS(email, r'^[^@]+@[^@]+$')) as invalid_emails
    FROM `project.dataset.users`
""")
```

## Extending the Tool

Future enhancements (not in MVP):

- Natural language → SQL generation (use LLM nodes upstream)
- Write operations (requires additional safety controls)
- Query dry-run for cost estimation
- Result caching
- Pagination support for large results

## Troubleshooting

### "Could not automatically determine credentials"

- Set `GOOGLE_APPLICATION_CREDENTIALS` environment variable, or
- Run `gcloud auth application-default login`

### "Permission denied"

Ensure your service account has:
- `roles/bigquery.dataViewer` - to read tables
- `roles/bigquery.jobUser` - to run queries

### "Dataset not found"

- Check the dataset name is correct
- Verify the project ID is correct
- Ensure you have access to the dataset
