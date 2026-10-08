# Pinecone Tool

Manage Pinecone vector indexes and perform vector operations for semantic search and RAG workflows.

## Tools

| Tool | Description |
|------|-------------|
| `pinecone_list_indexes` | List all indexes in your Pinecone project |
| `pinecone_create_index` | Create a new serverless index |
| `pinecone_describe_index` | Get configuration and status of a specific index |
| `pinecone_delete_index` | Delete an index (irreversible) |
| `pinecone_upsert_vectors` | Insert or update vectors in an index |
| `pinecone_query_vectors` | Query an index for similar vectors |
| `pinecone_fetch_vectors` | Fetch specific vectors by ID |
| `pinecone_delete_vectors` | Delete vectors by ID, filter, or entire namespace |
| `pinecone_index_stats` | Get vector counts and namespace statistics for an index |

## Setup

Requires a Pinecone API key:

```bash
export PINECONE_API_KEY="your_api_key_here"
```

> Get your API key at https://app.pinecone.io/ under **API Keys**

## Usage Examples

### List all indexes
```python
pinecone_list_indexes()
```

### Create a new index
```python
pinecone_create_index(
    name="my-index",
    dimension=1536,
    metric="cosine",
    cloud="aws",
    region="us-east-1"
)
```

### Describe an index
```python
pinecone_describe_index(index_name="my-index")
```

### Upsert vectors
```python
pinecone_upsert_vectors(
    index_host="https://my-index-abc123.svc.pinecone.io",
    vectors=[
        {"id": "vec1", "values": [0.1, 0.2, 0.3], "metadata": {"source": "doc1"}},
        {"id": "vec2", "values": [0.4, 0.5, 0.6], "metadata": {"source": "doc2"}},
    ],
    namespace="my-namespace"
)
```

### Query for similar vectors
```python
pinecone_query_vectors(
    index_host="https://my-index-abc123.svc.pinecone.io",
    vector=[0.1, 0.2, 0.3],
    top_k=5,
    filter={"source": {"$eq": "doc1"}},
    include_metadata=True
)
```

### Fetch vectors by ID
```python
pinecone_fetch_vectors(
    index_host="https://my-index-abc123.svc.pinecone.io",
    ids=["vec1", "vec2"],
    namespace="my-namespace"
)
```

### Delete vectors
```python
# By ID
pinecone_delete_vectors(
    index_host="https://my-index-abc123.svc.pinecone.io",
    ids=["vec1", "vec2"]
)

# All vectors in a namespace
pinecone_delete_vectors(
    index_host="https://my-index-abc123.svc.pinecone.io",
    namespace="my-namespace",
    delete_all=True
)
```

### Get index stats
```python
pinecone_index_stats(index_host="https://my-index-abc123.svc.pinecone.io")
```

### Delete an index
```python
pinecone_delete_index(index_name="my-index")
```

## Distance Metrics

| Metric | Description |
|--------|-------------|
| `cosine` | Cosine similarity (default, recommended for text embeddings) |
| `euclidean` | Euclidean distance |
| `dotproduct` | Dot product (for normalized vectors) |

## Error Handling

All tools return error dicts on failure:

```python
{"error": "PINECONE_API_KEY not set", "help": "Get an API key at https://app.pinecone.io/ under API Keys"}
{"error": "Unauthorized. Check your PINECONE_API_KEY."}
{"error": "Pinecone API error 400: ..."}
{"error": "Request to Pinecone timed out"}
```