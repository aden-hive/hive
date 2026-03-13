# Codebase Navigator

Navigate unfamiliar codebases using only file tools. No third-party credentials.

## What it does

1. **Intake** — Asks what you want to understand (entry points, config, a module, dependencies).
2. **Explore** — Maps repo structure with `list_dir`.
3. **Search** — Finds relevant files with `grep_search`.
4. **Synthesize** — Reads files with `view_file` and produces a summary with file:line citations.
5. **Deliver** — Generates an HTML report with optional Mermaid diagram and serves a clickable file link.

## Requirements

- Sync a local directory into the workspace before running
- hive-tools MCP server (list_dir, view_file, grep_search)

## Usage

```bash
# 1. Sync your repo into the workspace (required)
PYTHONPATH=core:examples/templates uv run python -m codebase_navigator sync --source .

# 2. Run with a question
PYTHONPATH=core:examples/templates uv run python -m codebase_navigator run --question "Where are the entry points?"

# 3. Or use the TUI for interactive navigation
PYTHONPATH=core:examples/templates uv run python -m codebase_navigator tui
```

## Design

- **Zero credentials** — Only file tools; runs offline, no API keys
- **5-node linear pipeline** — intake → explore → search → synthesize → deliver
- **MCP-native** — Uses hive-tools; no custom tools
- **HTML report** — Full report in a browser (not limited by TUI). Includes optional Mermaid diagram of codebase structure
