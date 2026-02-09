# Airtable Tool

Read and write Airtable bases and records via the Airtable Web API.

## Setup

```bash
# Required - Personal Access Token
export AIRTABLE_API_TOKEN=your-airtable-personal-access-token
```

**Get your token:**
1. Go to https://airtable.com/create/tokens
2. Click "Create new token"
3. Name your token and add scopes: `schema.bases:read`, `data.records:read`, `data.records:write`
4. Add base access (or all bases)
5. Copy the token and set `AIRTABLE_API_TOKEN` environment variable

Alternatively, configure via the credential store (`CredentialStoreAdapter`).

## Rate Limits

- Automatically retries up to 2 times on 429 using Airtable's `Retry-After` header
- Returns clear error with `retry_after` when exhausted

## Tools (5)

| Tool | Description |
|------|-------------|
| `airtable_list_bases` | List all bases available to the user |
| `airtable_list_tables` | List tables in a base |
| `airtable_list_records` | List records in a table (with filter/sort) |
| `airtable_create_record` | Create a record in a table |
| `airtable_update_record` | Update a record by ID |

## Usage

### List bases

```python
result = airtable_list_bases()
# Returns bases with id, name, permissionLevel
```

### List tables in a base

```python
result = airtable_list_tables(base_id="appXXXXXXXX")
# Returns tables with id, name
```

### List records

```python
result = airtable_list_records(
    base_id="appXXXXXXXX",
    table_id_or_name="Leads",
    filter_by_formula="{Status}='Qualified'",
    sort=[{"field": "Created", "direction": "desc"}],
    max_records=50,
)
# Returns records with id, createdTime, fields
```

### Create record

```python
# Use case: "When a lead is qualified in Slack, create a row in Airtable Leads base"
result = airtable_create_record(
    base_id="appXXXXXXXX",
    table_id_or_name="Leads",
    fields={"Name": "Acme Corp", "Status": "Contacted", "Email": "lead@acme.com"},
)
# Returns created record id and fields
```

### Update record

```python
result = airtable_update_record(
    base_id="appXXXXXXXX",
    table_id_or_name="Leads",
    record_id="recXXXXXXXX",
    fields={"Status": "Contacted"},
)
# Returns updated record id and fields
```

## Scope (MVP)

- List bases
- List tables in a base
- List records (with optional filter/sort)
- Create record
- Update record by ID

## API Reference

- [Airtable Web API](https://airtable.com/developers/web/api/introduction)
