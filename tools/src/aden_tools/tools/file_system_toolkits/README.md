# File System Toolkits (post-consolidation)

This package contains only sandbox path helpers used by `csv_tool` and
`excel_tool`. **All file tools live in `aden_tools.file_ops`** (read_file,
write_file, edit_file, hashline_edit, search_files, apply_patch) — they
share one path policy and one home dir.

## Sub-modules

| Module | Description |
|--------|-------------|
| `security.py` | Sandbox path resolver used by csv_tool and excel_tool |

## File tools

For read/write/edit/search/patch, see `aden_tools.file_ops` and call
`register_file_tools(mcp, home=..., write_safe_root=...)` once. The path
model is uniform across all six tools:

- Relative paths anchor to `home`.
- Absolute paths are honored verbatim.
- Writes to system / credential paths are denied; reads of credential
  files are denied; system config files (`/etc/nginx/...`) remain readable.
- `write_safe_root` (str or list) is an optional hard ceiling for writes.

## Usage

```python
from aden_tools.file_ops import register_file_tools

register_file_tools(mcp, home="/path/to/agent/home")
```
