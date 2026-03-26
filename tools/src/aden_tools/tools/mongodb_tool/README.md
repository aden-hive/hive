# MongoDB Tool

Document CRUD and aggregation via the MongoDB Atlas Data API (or compatible replacements like Delbridge and RESTHeart).

## Supported Actions

- **mongodb_find** – Query documents with filter, projection, sort, and limit
- **mongodb_find_one** – Find a single document by filter
- **mongodb_insert_one** – Insert a document into a collection
- **mongodb_update_one** – Update a document with filter and update operators
- **mongodb_delete_one** – Delete a single document by filter
- **mongodb_aggregate** – Run an aggregation pipeline

## Setup

1. Enable the [Atlas Data API](https://www.mongodb.com/docs/atlas/app-services/data-api/) or deploy a compatible REST interface.

2. Set the required environment variables:
   ```bash
   export MONGODB_DATA_API_URL=https://data.mongodb-api.com/app/<app-id>/endpoint/data/v1
   export MONGODB_API_KEY=your-api-key
   export MONGODB_DATA_SOURCE=your-cluster-name
   ```

> **Note:** The Atlas Data API reached EOL in September 2025. Compatible replacements (Delbridge, RESTHeart) use the same interface.

## Use Case

Example: "Query the `transactions` collection for all records over $10,000 in the last 24 hours and aggregate them by merchant category."
