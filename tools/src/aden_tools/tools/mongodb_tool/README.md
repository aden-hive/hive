# MongoDB Tool

Perform document CRUD and aggregation on MongoDB collections via the Atlas Data API (or compatible replacements like Delbridge and RESTHeart).

## Tools

| Tool | Description |
|------|-------------|
| `mongodb_find` | Find multiple documents matching a filter |
| `mongodb_find_one` | Find a single document matching a filter |
| `mongodb_insert_one` | Insert a single document into a collection |
| `mongodb_update_one` | Update a single document matching a filter |
| `mongodb_delete_one` | Delete a single document matching a filter |
| `mongodb_aggregate` | Run an aggregation pipeline on a collection |

## Setup

Requires MongoDB Atlas Data API credentials:

```bash
export MONGODB_DATA_API_URL="https://data.mongodb-api.com/app/<app-id>/endpoint/data/v1"
export MONGODB_API_KEY="your_api_key"
```

> Enable the Data API and get credentials from https://cloud.mongodb.com under **App Services → Data API**

> **Note:** The Atlas Data API reached EOL in September 2025. Compatible replacements like [Delbridge](https://github.com/stdatlas/delbridge) and [RESTHeart](https://restheart.org/) use the same interface.

## Usage Examples

### Find documents
```python
mongodb_find(
    database="mydb",
    collection="users",
    filter='{"status": "active"}',
    sort='{"created": -1}',
    limit=10
)
```

### Find a single document
```python
mongodb_find_one(
    database="mydb",
    collection="users",
    filter='{"email": "alice@example.com"}',
    projection='{"name": 1, "email": 1, "_id": 0}'
)
```

### Insert a document
```python
mongodb_insert_one(
    database="mydb",
    collection="users",
    document='{"name": "Alice", "email": "alice@example.com", "status": "active"}'
)
```

### Update a document
```python
mongodb_update_one(
    database="mydb",
    collection="users",
    filter='{"email": "alice@example.com"}',
    update='{"$set": {"status": "inactive"}}',
    upsert=False
)
```

### Delete a document
```python
mongodb_delete_one(
    database="mydb",
    collection="users",
    filter='{"email": "alice@example.com"}'
)
```

### Run an aggregation pipeline
```python
mongodb_aggregate(
    database="mydb",
    collection="orders",
    pipeline='[{"$match": {"status": "completed"}}, {"$group": {"_id": "$userId", "total": {"$sum": "$amount"}}}]'
)
```

## Error Handling

All tools return error dicts on failure:

```python
{"error": "MONGODB_DATA_API_URL and MONGODB_API_KEY are required", "help": "Set MONGODB_DATA_API_URL and MONGODB_API_KEY environment variables"}
{"error": "HTTP 401: ..."}
{"error": "filter must be valid JSON"}
{"error": "no document found matching filter"}
```