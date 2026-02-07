# Vector Database Tool

Semantic search and vector storage for document management.

## Features

- **Vector Storage**: Store and retrieve documents using semantic similarity
- **Multiple Backends**: Support for ChromaDB, Pinecone, Qdrant, and PGVector (ChromaDB implemented)
- **Text Chunking**: Intelligent text splitting for efficient storage and retrieval
- **Metadata Filtering**: Filter search results by metadata

## Usage

### Upsert Documents

```python
vector_db_upsert(
    ids=["doc1", "doc2"],
    documents=["First document text", "Second document text"],
    metadatas=[{"source": "file1.txt"}, {"source": "file2.txt"}],
    collection_name="my_collection"
)
```

### Search Similar Documents

```python
vector_db_search(
    query_texts=["search query"],
    n_results=5,
    where={"source": "file1.txt"},
    collection_name="my_collection"
)
```

### Chunk Large Text

```python
vector_db_chunk_text(
    text="Large document content...",
    chunk_size=1000,
    chunk_overlap=200
)
```

## Configuration

Environment variables:
- `CHROMA_PERSIST_DIR`: Directory to persist ChromaDB data (default: `./chroma_db`)
- `CHROMA_COLLECTION_NAME`: Default collection name (default: `default_collection`)

## Architecture

- `vector_db_tool.py`: MCP tool interface
- `stores/chromadb.py`: ChromaDB adapter (uses default embeddings)
- `chunking.py`: Recursive text splitter
- `embeddings/`: Embedding providers (future expansion)
- `stores/`: Vector store adapters (future expansion)
