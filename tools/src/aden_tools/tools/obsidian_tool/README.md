# Obsidian Tool

Read, write, search, and manage notes in an Obsidian vault via the Obsidian Local REST API.

## Tools

| Tool | Description |
|------|-------------|
| `obsidian_read_note` | Read the content of a note by path |
| `obsidian_write_note` | Create or overwrite a note |
| `obsidian_append_note` | Append content to an existing note |
| `obsidian_search` | Search notes by text or regex |
| `obsidian_list_files` | List files and folders in a vault path |
| `obsidian_get_active` | Get the currently active note |

## Setup

Requires the [Obsidian Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) plugin.

| Variable | Description |
|----------|-------------|
| `OBSIDIAN_REST_API_KEY` | API key from the Local REST API plugin |
| `OBSIDIAN_REST_BASE_URL` | REST API URL (default: `https://127.0.0.1:27124`) |

## Usage Examples

### Read a note
```python
obsidian_read_note(path="Projects/hive-contributions.md")
```

### Write a note
```python
obsidian_write_note(path="Daily/2026-03-30.md", content="# Today\n\n- Submitted PR")
```

### Search the vault
```python
obsidian_search(query="event bus tests", context_length=100)
```

### List files in a folder
```python
obsidian_list_files(path="Projects/")
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "OBSIDIAN_REST_API_KEY not set", "help": "Set OBSIDIAN_REST_API_KEY environment variable or configure via credential store"}
{"error": "Obsidian API error (HTTP 404): Note not found"}
{"error": "Request timed out"}
```
