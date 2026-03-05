# Hashline Edit Tool

Edit files using anchor-based line references for precise, hash-validated edits.

## Description

The `hashline_edit` tool enables file editing using short content-hash anchors (`N:hhhh`) instead of requiring exact text reproduction. Each line's anchor includes a 4-character hash of its content. If the file has changed since the model last read it, the hash won't match and the edit is cleanly rejected.

Use this tool together with `view_file(hashline=True)` and `grep_search(hashline=True)`, which return anchors for each line.

## Use Cases

- Making targeted edits after reading a file with `view_file(hashline=True)`
- Replacing single lines, line ranges, or inserting new lines by anchor
- Batch editing multiple locations in a single atomic call
- Falling back to string replacement when anchors are not available

## Usage

```python
import json

# First, read the file with hashline mode to get anchors
content = view_file(path="app.py", hashline=True, workspace_id="ws-1", agent_id="a-1", session_id="s-1")
# Returns lines like: 1:a3b1|def main():  2:f1c2|    print("hello")  ...

# Then edit using the anchors
hashline_edit(
    path="app.py",
    edits=json.dumps([
        {"op": "set_line", "anchor": "2:f1c2", "content": '    print("goodbye")'}
    ]),
    workspace_id="ws-1",
    agent_id="a-1",
    session_id="s-1"
)
```

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `path` | str | Yes | - | The path to the file (relative to session root) |
| `edits` | str | Yes | - | JSON string containing a list of edit operations (see Operations below) |
| `workspace_id` | str | Yes | - | The ID of the workspace |
| `agent_id` | str | Yes | - | The ID of the agent |
| `session_id` | str | Yes | - | The ID of the current session |
| `auto_cleanup` | bool | No | `True` | Strip hashline prefixes and echoed context from content. Set to `False` to write content exactly as provided. |
| `encoding` | str | No | `"utf-8"` | File encoding. Must match the file's actual encoding. |

## Operations

The `edits` parameter is a JSON array of operation objects. Each object must have an `"op"` field:

| Op | Fields | Behavior |
|---|---|---|
| `set_line` | `anchor`, `content` | Replace one line identified by anchor (use `content: ""` to delete the line) |
| `replace_lines` | `start_anchor`, `end_anchor`, `content` | Replace a range of lines (can expand or shrink) |
| `insert_after` | `anchor`, `content` | Insert new lines after the anchor line |
| `insert_before` | `anchor`, `content` | Insert new lines before the anchor line |
| `replace` | `old_content`, `new_content`, `allow_multiple` (optional) | Fallback string replacement; errors if 0 or 2+ matches (unless `allow_multiple: true`) |
| `append` | `content` | Append new lines to end of file (works for empty files too) |

## Returns

**Success:**
```python
{
    "success": True,
    "path": "app.py",
    "edits_applied": 2,
    "content": "1:b2c4|def main():\n2:c4a1|    print(\"goodbye\")\n..."
}
```

**Success (noop, content unchanged after applying edits):**
```python
{
    "success": True,
    "path": "app.py",
    "edits_applied": 0,
    "note": "Content unchanged after applying edits",
    "content": "1:b2c4|def main():\n..."
}
```

**Success (with auto-cleanup applied):**
```python
{
    "success": True,
    "path": "app.py",
    "edits_applied": 1,
    "content": "...",
    "cleanup_applied": ["prefix_strip"]
}
```

The `cleanup_applied` field is only present when cleanup actually modified content. Possible values: `prefix_strip`, `boundary_echo_strip`, `insert_echo_strip`.

**Success (replace with allow_multiple):**
```python
{
    "success": True,
    "path": "app.py",
    "edits_applied": 1,
    "content": "...",
    "replacements": {"edit_1": 3}
}
```

The `replacements` field is only present when `allow_multiple: true` was used, showing the count per replace op.

**Error:**
```python
{
    "error": "Edit #1 (set_line): Hash mismatch at line 2: expected 'f1c2', got 'a3b1'. Re-read the file to get current anchors."
}
```

## Error Handling

- Returns an error if the file doesn't exist
- Returns an error if any anchor hash doesn't match (stale read)
- Returns an error if a line number is out of range
- Returns an error if splice ranges overlap within a batch
- Returns an error if a `replace` op matches 0 or 2+ times (unless `allow_multiple: true`)
- Returns an error for unknown op types or invalid JSON
- All edits are validated before any writes occur (atomic): on any error the file is unchanged

## Examples

### Replacing a single line
```python
edits = json.dumps([
    {"op": "set_line", "anchor": "5:a3b1", "content": "    return result"}
])
result = hashline_edit(path="app.py", edits=edits, workspace_id="ws-1", agent_id="a-1", session_id="s-1")
# Returns: {"success": True, "path": "app.py", "edits_applied": 1, "content": "..."}
```

### Replacing a range of lines
```python
edits = json.dumps([{
    "op": "replace_lines",
    "start_anchor": "10:b1c2",
    "end_anchor": "15:c2d3",
    "content": "    # simplified\n    return x + y"
}])
result = hashline_edit(path="math.py", edits=edits, workspace_id="ws-1", agent_id="a-1", session_id="s-1")
```

### Inserting new lines after
```python
edits = json.dumps([
    {"op": "insert_after", "anchor": "3:d4e5", "content": "import os\nimport sys"}
])
result = hashline_edit(path="app.py", edits=edits, workspace_id="ws-1", agent_id="a-1", session_id="s-1")
```

### Inserting new lines before
```python
edits = json.dumps([
    {"op": "insert_before", "anchor": "1:a1b2", "content": "#!/usr/bin/env python3"}
])
result = hashline_edit(path="app.py", edits=edits, workspace_id="ws-1", agent_id="a-1", session_id="s-1")
```

### Batch editing
```python
edits = json.dumps([
    {"op": "set_line", "anchor": "1:a1b2", "content": "#!/usr/bin/env python3"},
    {"op": "insert_after", "anchor": "2:b2c3", "content": "import logging"},
    {"op": "set_line", "anchor": "10:c3d4", "content": "    logging.info('done')"},
])
result = hashline_edit(path="app.py", edits=edits, workspace_id="ws-1", agent_id="a-1", session_id="s-1")
```

### Replace all occurrences
```python
edits = json.dumps([
    {"op": "replace", "old_content": "old_name", "new_content": "new_name", "allow_multiple": True}
])
result = hashline_edit(path="app.py", edits=edits, workspace_id="ws-1", agent_id="a-1", session_id="s-1")
# Returns: {..., "replacements": {"edit_1": 5}}
```

## Notes

- Anchors are generated by `view_file(hashline=True)` and `grep_search(hashline=True)`
- The hash is a CRC32-based 4-char hex digest of the line content (with trailing spaces and tabs stripped; leading whitespace is included so indentation changes invalidate anchors). Collision probability is ~0.0015% per changed line.
- All anchor-based ops are validated before any writes occur; if any op fails validation, the file is left unchanged
- String `replace` ops are applied after all anchor-based splices, so they match against post-splice content
- Original line endings (LF or CRLF) are preserved
- The response includes the updated file content in hashline format, so subsequent edits can use the new anchors without re-reading

## Auto-Cleanup Details

When `auto_cleanup=True` (the default), the tool strips hashline prefixes and echoed context that LLMs frequently include in edit content. Prefix stripping uses a **2+ non-empty line threshold** to avoid false positives. The prefix regex matches the `N:hhhh|` pattern (4-char hex hash).

**Why the threshold matters:** Single-line content matching the `N:hhhh|` pattern is ambiguous. It could be literal content (CSV data, config values, log format strings) that happens to match the pattern. With 2+ lines all matching, the probability of a false positive drops dramatically.

**Single-line example (NOT stripped):**
```python
# set_line with content "5:a3b1|hello" writes literally "5:a3b1|hello"
{"op": "set_line", "anchor": "2:f1c2", "content": "5:a3b1|hello"}
```

**Multi-line example (stripped):**
```python
# replace_lines where all lines match N:hhhh| pattern gets stripped
{"op": "replace_lines", "start_anchor": "2:f1c2", "end_anchor": "3:b2d3",
 "content": "2:a3b1|BBB\n3:c4d2|CCC"}
# Writes "BBB\nCCC" (prefixes removed)
```

**Escape hatch:** Set `auto_cleanup=False` to write content exactly as provided, bypassing all cleanup heuristics.
