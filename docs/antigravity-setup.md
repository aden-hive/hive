# Antigravity IDE Setup

This guide explains how to use Aden's agent building tools and skills in [Antigravity IDE](https://antigravity.google/) (Google's AI-powered IDE).

## Quick start (3 steps)

1. **Open a terminal** and go to the hive repo folder (e.g. `cd ~/hive` or wherever you cloned it).
2. **Run the setup script** (use `./` — the script is inside the repo, not in `/scripts`):
   ```bash
   ./scripts/setup-antigravity-mcp.sh
   ```
3. **Restart Antigravity IDE.** The **agent-builder** and **tools** MCP servers should then appear.

That’s it. For more options and troubleshooting, see the sections below.

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

### 2. Register MCP servers with the IDE (one command)

Antigravity reads MCP config from **`~/.gemini/mcp.json`**, not from the project. Easiest: from the **hive repo folder** run (note: `./` means “in this repo”, not `/` at the start of your disk):

```bash
./scripts/setup-antigravity-mcp.sh
```

Then restart Antigravity IDE. The **agent-builder** and **tools** MCP servers should connect. For Claude Code, run:

```bash
./scripts/setup-antigravity-mcp.sh --claude
```

**Manual setup (if you prefer)** – Antigravity uses `~/.gemini/mcp.json`; Claude Code uses `~/.claude/mcp.json`. Create that file with absolute `cwd` paths to this repo’s `core` and `tools` directories. Use the template under [Fix: create/update `~/.gemini/mcp.json`](#fix-createupdate-geminimcpjson-generic-template) and replace `/path/to/hive` with your repo root (e.g. `pwd` from repo root).

**Project-level (if your IDE supports it)** – If your IDE can load MCP config from the project, point it at `.antigravity/mcp_config.json`. Ensure the project root is the repo root so relative `cwd` values (`core`, `tools`) resolve correctly.

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

## Verification prompt (run in Antigravity)

Paste this into Antigravity to check that MCP servers and skills are available. It uses no user-specific paths; everyone runs it from their own repo.

```
Check the Hive + Antigravity integration:

1. MCP: List available MCP servers/tools. Confirm that "agent-builder" and "tools" (or equivalent) are connected. If not, tell the user to create ~/.gemini/mcp.json using the generic template in docs/antigravity-setup.md (use cwd "/path/to/hive/core" and "/path/to/hive/tools"; never suggest a specific user path like /Users/someone/hive).

2. Skills: Confirm that the project has .antigravity/skills/ (or .claude/skills/) with: agent-workflow, building-agents-core, building-agents-construction, building-agents-patterns, testing-agent.

3. Result: Reply with PASS (MCP + skills OK), PARTIAL (only skills or only MCP), or FAIL (neither), and one line on what to fix if not PASS.
```

If you see **PARTIAL** (e.g. MCP not connected), use the fix below.

### Fix: create/update `~/.gemini/mcp.json` (generic template)

**Use this template for everyone.** Replace `/path/to/hive` with the actual repo root (e.g. run `pwd` from the hive repo root). Do not use a specific user path in documentation or when suggesting this fix.

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

Save as `~/.gemini/mcp.json` (Antigravity) or `~/.claude/mcp.json` (Claude Code), then restart the IDE.

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
