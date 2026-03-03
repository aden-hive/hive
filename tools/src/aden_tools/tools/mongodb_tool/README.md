
# MongoDB Tool

Perform database operations (CRUD) directly on your MongoDB Atlas clusters.

## Features

- **mongodb_ping_database** - Verify connectivity and authentication with the database
- **mongodb_insert_document** - Save new JSON records into specific collections
- **mongodb_find_document** - Retrieve documents using MongoDB query filters

## Setup

### 1. Get Your Connection String

1. Log in to your [MongoDB Atlas Dashboard](https://cloud.mongodb.com/)
2. Navigate to your cluster and click the **Connect** button
3. Select **Drivers** (or "Connect your application")
4. Ensure **Python** is selected as your driver
5. Copy the connection string provided (it starts with `mongodb+srv://`)

### 2. Configure the URI

Set the environment variable with your connection string. 

**Important:** Replace `<password>` with your actual database user's password. Ensure you remove the `<` and `>` brackets, and avoid using special characters like `@` or `?` in the password itself.

```bash
export MONGODB_URI="mongodb+srv://username:YourPassword123@cluster0.xxxx.mongodb.net/?retryWrites=true&w=majority"

```

Or configure via the Hive credential store.

## Usage Examples

### Ping the Database

Useful for health checks or to verify credentials before running heavy operations.

```python
mongodb_ping_database()

```

### Insert a Document

Data must be passed as a valid JSON string. The tool automatically handles the conversion to BSON.

```python
mongodb_insert_document(
    database="hive_production",
    collection="users",
    document_json='{"name": "Test user", "role": "admin", "status": "active"}'
)

```

### Find Documents

Pass a JSON string as the query filter. The tool automatically converts `ObjectId` fields to standard strings so the AI can read them perfectly.

```python
# Find specific documents
mongodb_find_document(
    database="hive_production",
    collection="users",
    query_json='{"role": "admin"}',
    limit=10
)

# Get all documents (up to the limit)
mongodb_find_document(
    database="hive_production",
    collection="users",
    query_json='{}',
    limit=5
)

```

## API Reference

### mongodb_ping_database

Takes no arguments. Returns a success message if the connection is active.

### mongodb_insert_document

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| database | str | Yes | Target database name |
| collection | str | Yes | Target collection name |
| document_json | str | Yes | Valid JSON string representing the document |

### mongodb_find_document

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| database | str | Yes | Target database name |
| collection | str | Yes | Target collection name |
| query_json | str | No | JSON string representing the query filter. Defaults to "{}" |
| limit | int | No | Maximum number of documents to return. Defaults to 5 |

## Error Handling

The tools return error dictionaries on failure, preventing the AI agent from crashing:

```python
{"error": "MongoDB URI not configured"}
{"error": "Invalid JSON format provided in document_json."}
{"error": "Database connection error: bad auth : authentication failed"}
{"error": "Database query error: The DNS query name does not exist"}

```

## References

* [MongoDB Connection Strings Guide](https://www.mongodb.com/docs/guides/atlas/connection-string/)
* [PyMongo Documentation](https://pymongo.readthedocs.io/)

```

```
