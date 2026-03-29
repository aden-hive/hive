# PostgreSQL Tool

Provide **safe, read-only access** to PostgreSQL databases via MCP (FastMCP).  
Designed for **introspection, querying, and analysis** without allowing data mutation.

---

## Setup

Set the `DATABASE_URL` environment variable or configure it via the credential store:

```bash
export DATABASE_URL=postgresql://user:password@localhost:5432/mydb
```


## All Tools (5 Total)

### Queries (2)
| Tool | Description |
|------|-------------|
| `pg_query` | Execute a safe, parameterized read-only SQL query |
| `pg_explain` | Explain execution plan for a query |


### Schema Introspection (3)
| Tool | Description |
|------|-------------|
| `pg_list_schemas` | List all database schemas |
| `pg_list_tables` | List tables (optionally filtered by schema) |
| `pg_describe_table` | Describe columns of a table |


## Tool Details

`pg_query`

Safely execute a parameterized, read-only SQL query.
```
pg_query(
    sql="SELECT * FROM users WHERE id = %(id)s",
    params={"id": 1}
)
```
Returns

```
{
  "columns": ["id", "name"],
  "rows": [[123, "Alice"]],
  "row_count": 1,
  "max_rows": 1000,
  "duration_ms": 12,
  "success": true
}
```

`pg_list_schemas`

List all schemas in the database.

```
pg_list_schemas()
```
Returns

```
{
  "result": ["public", "information_schema"],
  "success": true
}
```
`pg_list_tables`

List all tables, optionally filtered by schema.
```
pg_list_tables(schema="public")
```
Returns
```
{
  "result": [
    {"schema": "public", "table": "users"},
    {"schema": "public", "table": "orders"}
  ],
  "success": true
}
```

`pg_describe_table`

Describe a table’s columns.

```
pg_describe_table(
    schema="public",
    table="users"
)
```

Returns
```
{
  "result": [
    {
      "column": "id",
      "type": "bigint",
      "nullable": false,
      "default": null
    },
    {
      "column": "email",
      "type": "text",
      "nullable": false,
      "default": null
    }
  ],
  "success": true
}
```

`pg_explain`

Get the execution plan for a query.

```
pg_explain(sql="SELECT * FROM users WHERE id = 1")
```

Returns
```
{
  "result": [
    "Seq Scan on users  (cost=0.00..1.05 rows=1 width=32)"
  ],
  "success": true
}
```


## Limits & Safeguards

| Guard | Value |
|------|-------------|
| Max rows returned | `1000` |
| Statement timeout | `3000 ms` |
| Allowed operations | `SELECT`, `EXPLAIN`, introspection |
| SQL logging | Hashed only |



## Error Handling

All tools return MCP-friendly error payloads:

```
{
  "error": "Query timed out",
  "success": false
}
```
