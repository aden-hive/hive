# Data Tools

Load, save, and manage data files for agent pipelines within the secure session sandbox.

## Description

The `data_tools` toolkit provides file-based data management for AI agent pipelines. Its core purpose is keeping the LLM conversation context small — when a tool produces a large result (search results, profiles, analysis output), instead of passing it inline, agents save it to a file and retrieve it later with efficient byte-based pagination.

These tools also integrate with the **spillover system**: when a tool result is too large for the context window, the framework automatically writes it to a file, and the agent can load it back using `load_data()`.

## Setup

No external API keys or credentials required. The `data_tools` toolkit operates entirely within the local session sandbox.

The only requirement is providing a valid absolute path for `data_dir` when calling any tool.

```bash
# Example data directory
data_dir = "/workspace/data"
```

## Tools

- **save_data** — Write string data to a named file in the data directory
- **load_data** — Read a file back with byte-based pagination (handles files of any size)
- **append_data** — Append content to an existing file, or create it if it doesn't exist
- **edit_data** — Find and replace a unique text segment in an existing file
- **list_data_files** — List all files and their sizes in the data directory
- **serve_file_to_user** — Resolve a sandboxed file to a clickable `file://` URI for the user

## Security Model

All tools enforce strict filename validation to ensure operations stay within the sandbox:

- Filenames must be **simple names only** (e.g., `results.json`, `report.html`)
- No `..` — prevents directory traversal attacks
- No `/` or `\` — prevents path manipulation
- `data_dir` must always be an absolute path provided by the caller

Any filename violating these rules is rejected immediately with an error — no file operation is attempted.

## Typical Workflow

```
save_data → load_data (paginated) → edit_data / append_data → serve_file_to_user
```

## Usage Examples

### Save data to a file

```python
save_data(
    filename="search_results.json",
    data='[{"name": "Alice"}, {"name": "Bob"}]',
    data_dir="/workspace/data"
)
```

### Load data with pagination

```python
# Load first 10KB
load_data(
    filename="search_results.json",
    data_dir="/workspace/data"
)

# Load next 10KB using next_offset_bytes from previous result
load_data(
    filename="search_results.json",
    data_dir="/workspace/data",
    offset_bytes=10000
)

# Load a larger chunk
load_data(
    filename="large_file.txt",
    data_dir="/workspace/data",
    limit_bytes=50000
)
```

### Append content incrementally

```python
# Write the HTML skeleton first
append_data(
    filename="report.html",
    data="<html><body>",
    data_dir="/workspace/data"
)

# Append each section separately
append_data(
    filename="report.html",
    data="<h1>Results</h1><p>Section content here</p>",
    data_dir="/workspace/data"
)
```

### Edit a specific section of a file

```python
edit_data(
    filename="report.html",
    old_text="<p>Section content here</p>",
    new_text="<p>Updated content with real data</p>",
    data_dir="/workspace/data"
)
```

### List available files

```python
list_data_files(
    data_dir="/workspace/data"
)
```

### Serve a file to the user

```python
# Return a clickable file:// URI
serve_file_to_user(
    filename="report.html",
    data_dir="/workspace/data",
    label="Final Report"
)

# Auto-open in the user's default browser
serve_file_to_user(
    filename="report.html",
    data_dir="/workspace/data",
    label="Final Report",
    open_in_browser=True
)
```

## API Reference

### save_data

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `filename` | str | Yes | - | Simple filename (e.g. `results.json`). No paths or `..`. |
| `data` | str | Yes | - | The string data to write (typically JSON). |
| `data_dir` | str | Yes | - | Absolute path to the data directory. |

**Returns:**
```python
# Success
{
    "success": True,
    "filename": "results.json",
    "size_bytes": 1024,
    "lines": 42,
    "preview": "first 200 characters of data..."
}

# Error
{"error": "Invalid filename. Use simple names like 'users.json'"}
```

---

### load_data

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `filename` | str | Yes | - | The filename to load. |
| `data_dir` | str | Yes | - | Absolute path to the data directory. |
| `offset_bytes` | int | No | `0` | Byte offset to start reading from. |
| `limit_bytes` | int | No | `10000` | Max bytes to return (default 10KB). |

**Returns:**
```python
# Success
{
    "success": True,
    "filename": "results.json",
    "content": "...file content...",
    "offset_bytes": 0,
    "bytes_read": 10000,
    "next_offset_bytes": 10000,
    "file_size_bytes": 45000,
    "has_more": True
}

# Error
{"error": "File not found: results.json"}
```

> **Note:** Uses O(1) byte seeking — works efficiently on files of any size. Automatically trims to valid UTF-8 character boundaries to prevent character splitting.

---

### append_data

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `filename` | str | Yes | - | Simple filename to append to. No paths or `..`. |
| `data` | str | Yes | - | The string data to append. |
| `data_dir` | str | Yes | - | Absolute path to the data directory. |

**Returns:**
```python
# Success
{
    "success": True,
    "filename": "report.html",
    "size_bytes": 2048,
    "appended_bytes": 512
}

# Error
{"error": "Invalid filename. Use simple names like 'report.html'"}
```

---

### edit_data

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `filename` | str | Yes | - | The file to edit. Must exist in `data_dir`. |
| `old_text` | str | Yes | - | The exact text to find (must appear exactly once). |
| `new_text` | str | Yes | - | The replacement text. |
| `data_dir` | str | Yes | - | Absolute path to the data directory. |

**Returns:**
```python
# Success
{
    "success": True,
    "filename": "report.html",
    "size_bytes": 2100,
    "replacements": 1
}

# Error — text not found
{"error": "old_text not found in the file. Make sure you're matching the exact text, including whitespace and newlines."}

# Error — text not unique
{"error": "old_text found 3 times — it must be unique. Include more surrounding context to match exactly once."}
```

> **Important:** `old_text` must appear **exactly once** in the file. If it matches zero or more than one time, the edit is rejected — include more surrounding context to make it unique.

---

### list_data_files

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `data_dir` | str | Yes | - | Absolute path to the data directory. |

**Returns:**
```python
# Success
{
    "files": [
        {"filename": "report.html", "size_bytes": 2100},
        {"filename": "results.json", "size_bytes": 45000}
    ]
}

# Empty directory
{"files": []}

# Error
{"error": "Failed to list data files: ..."}
```

---

### serve_file_to_user

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `filename` | str | Yes | - | The filename to serve. Must exist in `data_dir`. |
| `data_dir` | str | Yes | - | Absolute path to the data directory. |
| `label` | str | No | `""` | Display label (defaults to filename). |
| `open_in_browser` | bool | No | `False` | If True, auto-opens the file in the default browser. |

**Returns:**
```python
# Success
{
    "success": True,
    "file_uri": "file:///workspace/data/report.html",
    "file_path": "/workspace/data/report.html",
    "label": "Final Report"
}

# Success with browser opened
{
    "success": True,
    "file_uri": "file:///workspace/data/report.html",
    "file_path": "/workspace/data/report.html",
    "label": "Final Report",
    "browser_opened": True,
    "browser_message": "Opened in default browser"
}

# Error
{"error": "File not found: report.html"}
```

## Error Handling

All tools follow a consistent error pattern — they return a dictionary with an `"error"` key on failure:

```python
{"error": "Invalid filename. Use simple names like 'users.json'"}
{"error": "data_dir is required"}
{"error": "File not found: results.json"}
{"error": "Could not decode file as UTF-8"}
{"error": "old_text not found in the file. Make sure you're matching the exact text, including whitespace and newlines."}
```

Always check for the presence of `"error"` in the returned dict before using the result.
