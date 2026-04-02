# Viral Tech Copywriter

## What it does

- **Job:** Turns a **marketing brief** (collected in chat) into **structured brief JSON**,
  then **hooks plus per-channel copy**, then **exports** the bundle as **HTML** and/or **Markdown**
  (`save_data` / `append_data` / `serve_file_to_user` only—no extra tools package features).
- **Flow:** `intake` (HITL) → `normalize-brief` → `write-package` → `deliver-exports` (terminal).
  Delivery uses **hive-tools** MCP: `save_data`, `append_data`, `serve_file_to_user`,
  `load_data`, `list_data_files`, `edit_data`.
- **Honesty:** Prompts forbid inventing metrics, customers, or quotes. Uncertain claims belong
  in `verify_flags` / notes.

## Run

`mcp_servers.json` must be present (it ships with the template) so the MCP server can start
from the repo `tools/` directory (`uv run python mcp_server.py --stdio`).

```bash
PYTHONPATH=core:examples/templates uv run python -m viral_tech_copywriter validate
PYTHONPATH=core:examples/templates uv run python -m viral_tech_copywriter tui
```

Configure the LLM via `~/.hive/configuration.json` like other Hive agents.

## Outputs

- **`raw_brief`:** Plain text from intake.
- **`structured_brief`:** JSON string (product, ICP, value props, platforms, etc.).
- **`copy_package`:** JSON string (`hooks[]`, `channels{}`, optional `notes`).
- **`delivered_artifacts`:** JSON string listing chosen formats and served files (URIs/paths).

**HTML** is served with `open_in_browser=true` when possible. **Markdown** (e.g.
`viral_copywriter_report.md`) is served as a **clickable file link** (`open_in_browser=false`)
so the user can open it in an editor or preview.

## Tests

```bash
PYTHONPATH=core:examples/templates uv run python -m pytest \
  examples/templates/viral_tech_copywriter/tests/ -v
```
