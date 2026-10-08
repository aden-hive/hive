# Supabase Tool

Database queries, auth, and edge function invocation via the Supabase REST API.

## Tools

| Tool | Description |
|------|-------------|
| `supabase_select` | Query rows from a table using PostgREST filters |
| `supabase_insert` | Insert one or more rows into a table |
| `supabase_update` | Update rows matching PostgREST filters |
| `supabase_delete` | Delete rows matching PostgREST filters |
| `supabase_auth_signup` | Register a new user via Supabase Auth (GoTrue) |
| `supabase_auth_signin` | Sign in a user and retrieve an access token |
| `supabase_edge_invoke` | Invoke a Supabase Edge Function |

## Setup

Requires a Supabase project URL and anon/service key:

1. Go to [supabase.com/dashboard](https://supabase.com/dashboard) → your project → **Project Settings → API**
2. Copy your **Project URL** and **anon public** key (or service role key for elevated access)

Set the following environment variables:

```bash
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your-anon-or-service-key
```

## Usage Examples

### Query rows with filters

```python
supabase_select(
    table="users",
    columns="id,name,email",
    filters="status=eq.active&role=eq.admin",
    order="created_at.desc",
    limit=50,
)
```

### Insert a single row

```python
supabase_insert(
    table="orders",
    rows='{"customer_id": 42, "total": 99.99, "status": "pending"}',
)
```

### Insert multiple rows

```python
supabase_insert(
    table="products",
    rows='[{"name": "Widget A", "price": 10}, {"name": "Widget B", "price": 20}]',
)
```

### Update rows matching a filter

```python
supabase_update(
    table="orders",
    filters="id=eq.123",
    data='{"status": "shipped"}',
)
```

### Delete rows matching a filter

```python
supabase_delete(
    table="sessions",
    filters="expires_at=lt.2024-01-01",
)
```

### Sign up a new user

```python
supabase_auth_signup(
    email="alice@example.com",
    password="securepassword",
)
```

### Sign in and get an access token

```python
supabase_auth_signin(
    email="alice@example.com",
    password="securepassword",
)
```

### Invoke an Edge Function

```python
supabase_edge_invoke(
    function_name="send-welcome-email",
    body='{"user_id": "abc123"}',
    method="POST",
)
```

## PostgREST Filter Syntax

| Operator | Meaning | Example |
|----------|---------|---------|
| `eq` | equals | `status=eq.active` |
| `neq` | not equals | `role=neq.admin` |
| `gt` | greater than | `age=gt.18` |
| `lt` | less than | `price=lt.100` |
| `like` | pattern match | `name=like.*Alice*` |
| `is` | is null/true/false | `deleted_at=is.null` |

Combine multiple filters with `&`: `"status=eq.active&role=eq.admin"`

## Error Handling

All tools return error dicts on failure:

```python
{"error": "SUPABASE_ANON_KEY or SUPABASE_URL not set", "help": "Get your keys at https://supabase.com/dashboard → Project Settings → API"}
{"error": "Supabase error 403: ..."}
{"error": "Request to Supabase timed out"}
```
