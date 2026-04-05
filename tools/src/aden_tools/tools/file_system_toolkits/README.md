# File System Toolkits

A collection of file system tools for reading, writing, searching, and executing commands within the agent workspace.

## Tools

| Tool | Description |
|------|-------------|
| `apply_diff` | Apply a unified diff to a file |
| `apply_patch` | Apply a patch file to modify source files |
| `hashline_edit` | Edit a file using hashline-addressed replacements |
| `replace_file_content` | Find and replace content in a file |
| `grep_search` | Search file contents using regex patterns |
| `list_dir` | List directory contents with metadata |
| `execute_command_tool` | Execute a shell command in the workspace |
| `save_data` | Save data to a file in the agent's data directory |
| `load_data` | Load data from a file in the data directory |
| `serve_file_to_user` | Serve a file to the user for download |
| `list_data_files` | List files in the agent's data directory |
| `append_data` | Append data to an existing file |

## Sub-modules

| Module | Description |
|--------|-------------|
| `apply_diff/` | Unified diff application |
| `apply_patch/` | Patch file application |
| `data_tools/` | Data persistence (save, load, append, list, serve) |
| `execute_command_tool/` | Shell command execution with sanitization |
| `grep_search/` | File content search (uses ripgrep if available) |
| `hashline_edit/` | Hashline-based file editing |
| `list_dir/` | Directory listing |
| `replace_file_content/` | Find-and-replace in files |

## Setup

No external credentials required. File operations are scoped to the agent's workspace directory.

## Security

- `command_sanitizer.py` validates and sanitizes shell commands before execution
- `security.py` provides path traversal protection
- All file operations are workspace-scoped

## Usage Examples

### Search for a pattern in files
```python
grep_search(pattern="def register_tools", path="tools/src/", include="*.py")
```

### List directory contents
```python
list_dir(path="core/framework/", workspace_id="ws1", agent_id="agent1", session_id="s1")
```

### Save data to a file
```python
save_data(filename="results.json", data='{"status": "complete"}', data_dir="/path/to/data")
```

### Execute a command
```python
execute_command_tool(command="python -m pytest tests/ -v")
```
