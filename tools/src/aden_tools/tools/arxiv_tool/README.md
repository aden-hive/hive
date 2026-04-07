# arXiv Tool

Search and download scientific papers from arXiv.

## Description

Provides two tools for interacting with the arXiv preprint repository:

- **`search_papers`** — Search for papers by keyword, author, title, or category with flexible sorting
- **`download_paper`** — Download a paper as a PDF to a temporary local file by arXiv ID

## Arguments

### `search_papers`

| Argument      | Type      | Required | Default        | Description                                                            |
| ------------- | --------- | -------- | -------------- | ---------------------------------------------------------------------- |
| `query`       | str       | Yes*     | `""`           | Search query. Supports field prefixes and boolean operators (see below) |
| `id_list`     | list[str] | Yes*     | `None`         | Specific arXiv IDs to retrieve (e.g. `["1706.03762"]`)                 |
| `max_results` | int       | No       | `10`           | Maximum number of results to return (capped at 100)                    |
| `sort_by`     | str       | No       | `"relevance"`  | Sort criterion: `"relevance"`, `"lastUpdatedDate"`, `"submittedDate"`  |
| `sort_order`  | str       | No       | `"descending"` | Sort direction: `"descending"` or `"ascending"`                        |

\* At least one of `query` or `id_list` must be provided.

**Query syntax:**

- Field prefixes: `ti:` (title), `au:` (author), `abs:` (abstract), `cat:` (category)
- Boolean operators: `AND`, `OR`, `ANDNOT` (must be uppercase)
- Examples: `"ti:transformer AND au:vaswani"`, `"abs:multi-agent systems"`

### `download_paper`

| Argument   | Type | Required | Default | Description                                                              |
| ---------- | ---- | -------- | ------- | ------------------------------------------------------------------------ |
| `paper_id` | str  | Yes      | -       | arXiv paper ID, with or without version (e.g. `"2207.13219"`, `"2207.13219v4"`) |

## Environment Variables

No API credentials required. arXiv is a publicly accessible repository.

## Example Usage

```python
# Keyword search
result = search_papers(query="multi-agent reinforcement learning")

# Search by title and author
result = search_papers(query="ti:attention AND au:vaswani", max_results=5)

# Search by category, sorted by submission date
result = search_papers(
    query="cat:cs.LG",
    sort_by="submittedDate",
    sort_order="descending",
    max_results=20,
)

# Retrieve specific papers by ID
result = search_papers(id_list=["1706.03762", "2005.14165"])

# Download a paper as a PDF
result = download_paper(paper_id="1706.03762")
# result["file_path"] → "/tmp/arxiv_papers_<random>/Attention_Is_All_You_Need_1706_03762_.pdf"
# Files are stored in a shared managed directory for the lifetime of the server process.
# No cleanup needed — the directory is automatically deleted on process exit.
```

## Return Values

### `search_papers` — success

Results are truncated to one entry for brevity; `"total"` reflects the actual count returned.

```json
{
  "success": true,
  "query": "multi-agent reinforcement learning",
  "id_list": [],
  "results": [
    {
      "id": "2203.08975v2",
      "title": "A Survey of Multi-Agent Deep Reinforcement Learning with Communication",
      "summary": "Communication is an effective mechanism for coordinating the behaviors of multiple agents...",
      "published": "2022-03-16",
      "authors": [
        "Changxi Zhu",
        "Mehdi Dastani",
        "Shihan Wang"
      ],
      "pdf_url": "https://arxiv.org/pdf/2203.08975v2",
      "categories": [
        "cs.MA",
        "cs.LG"
      ]
    }
  ],
  "total": 10
}
```

When using `id_list`, `"query"` is returned as an empty string and `"id_list"` echoes the requested IDs:

```json
{
  "success": true,
  "query": "",
  "id_list": [
    "1706.03762",
    "2005.14165"
  ],
  "results": ["..."],
  "total": 2
}
```

### `download_paper` — success

```json
{
  "success": true,
  "file_path": "/tmp/arxiv_papers_<random>/Attention_Is_All_You_Need_1706_03762_.pdf",
  "paper_id": "1706.03762"
}
```

## Error Handling

All errors return `{"success": false, "error": "..."}`.

### `search_papers`

| Error message | Cause |
|---|---|
| `Invalid Request: You must provide either a 'query' or an 'id_list'.` | Both `query` and `id_list` are empty |
| `arXiv specific error: <reason>` | `arxiv.ArxivError` raised by the library |
| `Network unreachable.` | `ConnectionError` — no internet connectivity |
| `arXiv search failed: <reason>` | Any other unexpected exception |

```json
{
  "success": false,
  "error": "Invalid Request: You must provide either a 'query' or an 'id_list'."
}
```

### `download_paper`

| Error message | Cause |
|---|---|
| `No paper found with ID: <id>` | The arXiv ID does not exist |
| `PDF URL not available for this paper.` | Paper metadata has no PDF link |
| `Failed during download or write: <reason>` | `requests` network error, OS write failure, or arXiv returned an unexpected content type (e.g. HTML error page instead of PDF) |
| `arXiv library error: <reason>` | `arxiv.ArxivError` raised during metadata lookup |
| `Network error: <reason>` | `ConnectionError` during metadata lookup |
| `Unexpected error: <reason>` | Any other unexpected exception (partial file is cleaned up before returning) |

```json
{
  "success": false,
  "error": "No paper found with ID: 0000.00000"
}
```
## Implementation Notes

**PDF download** uses `requests.get` against `export.arxiv.org` (the designated programmatic subdomain) instead of the deprecated `Result.download_pdf()` helper. The 3-second rate limit only applies to the metadata API — the PDF download itself is a plain HTTPS file transfer and has no such restriction.

**Temporary storage** — PDFs are written to a module-level `TemporaryDirectory`, cleaned up automatically on process exit via `atexit`. This is intentional: the PDF is a transient bridge between `download_paper` and `pdf_read_tool` — not a deliverable. Using `data_dir` (the framework's session workspace) would pollute `list_data_files` with unreadable binary blobs and accumulate files with no cleanup. `_TEMP_DIR` scopes the file to exactly as long as it's needed.

**Known limitation:**
- **Resumable sessions** — if the process restarts mid-session, `_TEMP_DIR` is wiped and any checkpointed file path becomes invalid. This is unlikely to matter in practice since `pdf_read_tool` should be called immediately after `download_paper` in the same node.
