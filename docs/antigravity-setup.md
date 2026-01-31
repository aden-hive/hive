# Antigravity IDE Setup

This guide explains how to use Aden's agent building tools and skills in [Antigravity IDE](https://antigravity.google/) (Google's AI-powered IDE).

## Overview

The repository includes Antigravity IDE support so you can:

- Use the **agent-builder** MCP server to create and manage agents
- Use the **tools** MCP server for file operations, web search, and other agent capabilities
- Load and use **skills** for guided agent development (workflow, building, testing)

Configuration lives in `.antigravity/` and mirrors the Cursor integration for consistency.

## Prerequisites

- [Antigravity IDE](https://antigravity.google/) installed
- Python 3.11+ with the framework and tools installed (run `./scripts/setup-python.sh` from the repo root)
- Repository cloned and set up (see [ENVIRONMENT_SETUP.md](../ENVIRONMENT_SETUP.md))

## MCP Configuration

MCP servers are configured in `.antigravity/mcp_config.json`:

| Server          | Description                          |
|-----------------|--------------------------------------|
| **agent-builder** | Agent building MCP server (goals, nodes, edges, export) |
| **tools**       | Hive tools MCP server (19 tools for agent capabilities)   |

Both servers use stdio transport and run from the repo with the correct `PYTHONPATH`.

## Setup Steps

### 1. Install MCP dependencies (one-time)

From the repo root:

```bash
cd core
./setup_mcp.sh
```

This installs the framework package, MCP dependencies (`mcp`, `fastmcp`), and verifies the server can be imported.

### 2. Register MCP servers with the IDE

**Antigravity (and Claude Code) often do not load project-level `.antigravity/mcp_config.json`.** The IDE typically reads MCP config from a **global** location (e.g. `~/.claude/mcp.json`). To get the servers working:

**Option A – Copy to global config (recommended)**

1. Create the config directory: `mkdir -p ~/.claude`
2. Copy the project config and **use absolute paths** for `cwd` (replace `/path/to/hive` with your repo path, e.g. `/Users/you/hive`):

```json
{
  "mcpServers": {
    "agent-builder": {
      "command": "python",
      "args": ["-m", "framework.mcp.agent_builder_server"],
      "cwd": "/path/to/hive/core",
      "env": {
        "PYTHONPATH": "../tools/src"
      }
    },
    "tools": {
      "command": "python",
      "args": ["mcp_server.py", "--stdio"],
      "cwd": "/path/to/hive/tools",
      "env": {
        "PYTHONPATH": "src"
      }
    }
  }
}
```

Save this as `~/.claude/mcp.json` (merge with existing `mcpServers` if the file already exists).

**Option B – Project-level (if your IDE supports it)**

If your IDE can load MCP config from the project, point it at `.antigravity/mcp_config.json`. Ensure the project root is the repo root so relative `cwd` values (`core`, `tools`) resolve correctly.

### 3. About the `cwd` schema warning

If the IDE shows a warning that `cwd` is not allowed in the MCP config schema, **you can ignore it**. The `cwd` property is valid and supported by MCP clients; the warning is a false positive from the IDE’s JSON schema validator.

### 4. Restart or reload

Restart Antigravity (or your IDE) so it picks up the MCP configuration. The **agent-builder** and **tools** servers should then appear as available tools.

### 5. Use skills

Skills are in `.antigravity/skills/` (symlinks to `.claude/skills/`). If Antigravity has a skill/context loader that reads from the project, it can use these. Otherwise, you can reference the same guides under `.claude/skills/` when working in the IDE.

Available skills:

- **agent-workflow** – End-to-end workflow for building and testing agents
- **building-agents-core** – Core concepts for goal-driven agents
- **building-agents-construction** – Step-by-step agent construction
- **building-agents-patterns** – Patterns and best practices
- **testing-agent** – Goal-based evaluation and testing

## Directory layout

```
.antigravity/
├── mcp_config.json    # MCP server config (agent-builder, tools)
└── skills/            # Symlinks to .claude/skills/
    ├── agent-workflow
    ├── building-agents-core
    ├── building-agents-construction
    ├── building-agents-patterns
    └── testing-agent
```

Skills are symlinked so updates in `.claude/skills/` are reflected in Antigravity without extra copies.

## Troubleshooting

### MCP servers do not connect

- Confirm Python and dependencies are installed: from repo root run `./scripts/setup-python.sh`.
- From repo root, run:
  - `cd core && python -m framework.mcp.agent_builder_server` (Ctrl+C to stop)
  - `cd tools && PYTHONPATH=src python mcp_server.py --stdio` (Ctrl+C to stop)
- If Antigravity uses a user-level `mcp_config.json`, ensure `cwd` and paths point to this repo’s `core` and `tools` directories (use absolute paths if needed).

### "Module not found" or import errors

- Ensure you open the repo **root** as the project so `cwd` and `PYTHONPATH` in `mcp_config.json` resolve correctly.
- If you copied config to a user file, set `cwd` to the absolute path of `core` or `tools` and keep `PYTHONPATH` as in `.antigravity/mcp_config.json` (relative to that `cwd`).

### Skills not visible

- Antigravity may not have a built-in “skills” UI like Cursor. Use the content under `.claude/skills/` (or `.antigravity/skills/`) as reference documentation while using the MCP tools in the IDE.

## How to verify (check by yourself)

You can confirm the integration without Antigravity IDE installed:

### 1. Check files exist

From the repo root:

```bash
# MCP config
test -f .antigravity/mcp_config.json && echo "OK: mcp_config.json" || echo "MISSING"

# Skills symlinks (all should resolve)
for s in agent-workflow building-agents-core building-agents-construction building-agents-patterns testing-agent; do
  test -L .antigravity/skills/$s && test -d .antigravity/skills/$s && echo "OK: $s" || echo "BROKEN: $s"
done
```

### 2. Validate MCP config JSON

```bash
python3 -c "import json; json.load(open('.antigravity/mcp_config.json')); print('OK: valid JSON')"
```

### 3. Verify MCP servers can start (optional)

From repo root, in two terminals:

```bash
# Terminal 1 – agent-builder (Ctrl+C to stop)
cd core && PYTHONPATH=../tools/src python -m framework.mcp.agent_builder_server

# Terminal 2 – tools server (Ctrl+C to stop)
cd tools && PYTHONPATH=src python mcp_server.py --stdio
```

If both start without import/runtime errors, the config is correct.

### 4. Confirm symlinks match Cursor

```bash
# Same 5 skills as .cursor (if present) and .claude/skills
ls -la .antigravity/skills/
# Each should show -> ../../.claude/skills/<name>
```

---

## See also

- [Cursor IDE support](../README.md#cursor-ide-support) – Same MCP servers and skills for Cursor
- [MCP Integration Guide](../core/MCP_INTEGRATION_GUIDE.md) – Framework MCP details
- [Environment setup](../ENVIRONMENT_SETUP.md) – Repo and Python setup
