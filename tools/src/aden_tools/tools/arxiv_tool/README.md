# arXiv Tool

Search and download scholarly articles from the arXiv public archive.

## Features

- **search_papers**: Find papers by keyword or arXiv ID
- **download_paper**: Download PDFs for use with pdf_read
- **Automatic rate limiting**: 3-second delays between API calls
- **No authentication**: Public API, no credentials needed

## Usage Examples

### Search by Keyword

```python
# Search for papers about transformers
result = search_papers(
    query="transformer attention mechanism",
    max_results=10,
    sort_by="relevance"
)

# Access results
for paper in result["papers"]:
    print(f"{paper['title']}")
    print(f"  Authors: {', '.join(paper['authors'])}")
    print(f"  ID: {paper['paper_id']}")
    print()
```

### Search by arXiv ID

```python
# Get a specific paper
result = search_papers(query="1706.03762", max_results=1)
paper = result["papers"][0]
print(paper["title"])  # "Attention Is All You Need"
```

### Download and Read Paper

```python
# Download PDF
download_result = download_paper(paper_id="1706.03762")

# Read with pdf_read_tool
content = pdf_read(
    file_path=download_result["file_path"],
    pages="1-3",
    include_metadata=True
)

print(content["content"])
```

## Tool Reference

### search_papers

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `query` | str | (required) | Search query or arXiv ID (1-500 chars) |
| `max_results` | int | 10 | Number of results to return (1-100) |
| `sort_by` | str | "relevance" | Sort order: "relevance", "recent", "submitted" |

**Returns**:
```python
{
    "query": str,
    "num_results": int,
    "sort_by": str,
    "papers": [
        {
            "paper_id": str,        # e.g., "1706.03762v5"
            "title": str,
            "authors": [str],
            "abstract": str,
            "published": str,       # ISO format
            "updated": str | None,  # ISO format
            "pdf_url": str,
            "categories": [str]     # e.g., ["cs.CL", "cs.LG"]
        }
    ]
}
```

### download_paper

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `paper_id` | str | (required) | arXiv ID (e.g., "1706.03762") |

**Returns**:
```python
{
    "paper_id": str,
    "title": str,
    "file_path": str,           # Absolute path to PDF
    "file_size_bytes": int
}
```

## Error Handling

All errors return: `{"error": "descriptive message"}`

Common errors:
- Invalid query length
- Paper not found
- Network errors
- Rate limiting

## Rate Limiting

The arXiv API requires ~3 seconds between requests. This is automatically enforced with a thread-safe rate limiter.

## File Storage

Downloaded PDFs are stored in:
- **Windows**: `%TEMP%\arxiv_papers\`
- **Linux/Mac**: `/tmp/arxiv_papers/`

Files persist until manually deleted or system cleanup.
