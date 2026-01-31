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

### 1. Enable MCP in Antigravity

1. Open Antigravity IDE and open this repository as the project.
2. Open the MCP / agent panel (e.g. via the "..." dropdown in the agent area).
3. Go to **Manage MCP Servers** (or equivalent).
4. Use **View raw config** (or open the config file) so Antigravity uses the project config.

Antigravity can load MCP config from the project. Point it to `.antigravity/mcp_config.json` or copy its contents into Antigravity’s `mcp_config.json` if the IDE expects a single global/user config file.

### 2. Load project MCP config

- If Antigravity supports **project-level** MCP config, ensure the project root is the repo root so `.antigravity/mcp_config.json` is used.
- If it only supports a **user-level** config, merge the contents of `.antigravity/mcp_config.json` into your user `mcp_config.json`, and adjust `cwd` paths so they are absolute paths to this repo’s `core` and `tools` directories (e.g. `/path/to/hive/core` and `/path/to/hive/tools`).

### 3. Restart or reload

Restart Antigravity or reload MCP servers so the agent-builder and tools servers are connected.

### 4. Use skills

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

## See also

- [Cursor IDE support](../README.md#cursor-ide-support) – Same MCP servers and skills for Cursor
- [MCP Integration Guide](../core/MCP_INTEGRATION_GUIDE.md) – Framework MCP details
- [Environment setup](../ENVIRONMENT_SETUP.md) – Repo and Python setup
