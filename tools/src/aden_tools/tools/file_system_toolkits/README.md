# File System Toolkits

A comprehensive set of tools for interacting with files and directories within the sandboxed environment of the Aden Agent Framework.

## Overview

The `file_system_toolkits` package provides 8 essential tools for file operations, allowing agents to manage project files, view content, search through source code, and apply patches securely.

## Available Tools

### 1. [view_file](./view_file/README.md)
Reads and returns the complete content of a file within the sandbox.
- **Use Case**: Reading source code, config files, or logs.
- **Return**: Full content, size, and line count.

### 2. [write_to_file](./write_to_file/README.md)
Creates or overwrites a file with new content.
- **Use Case**: Saving generated code, configuration, or data.
- **Support**: Automatically creates parent directories if they don't exist.

### 3. [list_dir](./list_dir/README.md)
Lists files and directories in a given path.
- **Use Case**: Exploring project structure and identifying files.
- **Support**: Recursive listing and filtering options.

### 4. [grep_search](./grep_search/README.md)
Performs a regex search across multiple files in a directory.
- **Use Case**: Finding specific patterns, function definitions, or bugs.
- **Support**: Recursive search with context.

### 5. [replace_file_content](./replace_file_content/README.md)
Performs surgical replacements within a file using `old_string` and `new_string`.
- **Use Case**: Precise editing of large files without overwriting the entire content.
- **Safety**: Verifies that exactly one occurrence exists by default.

### 6. [apply_patch](./apply_patch/README.md)
Applies a standard unified diff patch to the file system.
- **Use Case**: Applying complex multi-file changes or PR-style patches.

### 7. [apply_diff](./apply_diff/README.md)
A specialized tool for applying string-based diffs to a target file.
- **Use Case**: Lightweight surgical edits when full patches aren't necessary.

### 8. [execute_command_tool](./execute_command_tool/README.md)
Executes safe shell commands within the sandbox.
- **Use Case**: Running build scripts, tests, or system utilities.
- **Restriction**: Limited to a predefined set of allowed commands and restricted by security policies.

## Security

All tools in this toolkit strictly adhere to the following security principles:
- **Sandbox Isolation**: Operations are restricted to the session-specific workspace directory.
- **Path Traversal Protection**: Prevents access to files outside the authorized project root.
- **Audit Logging**: All file modifications are logged for accountability and review.

## Usage Example

Most tools in this toolkit require `workspace_id`, `agent_id`, and `session_id` for context-aware operations:

```python
from aden_tools.tools.file_system_toolkits.view_file.view_file import view_file

result = view_file(
    path="src/main.py",
    workspace_id="ws-123",
    agent_id="agent-456",
    session_id="session-789"
)
```

For more details on each tool, refer to their respective README files.
