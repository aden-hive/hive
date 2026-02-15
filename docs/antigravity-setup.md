# Antigravity IDE Setup

Use the Hive agent framework (MCP servers and skills) inside [Antigravity IDE](https://antigravity.google/) (Google’s AI IDE).

---

## Quick start (3 steps)

**Repo root** = the folder that contains `core/`, `tools/`, and `.agent/` (where you cloned the project).

1. **Open a terminal** and go to the hive repo root (e.g. `cd ~/hive`).
2. **Run the setup script** (use `./` so the script runs from this repo; don't use `/scripts/...`):
   ```bash
   ./scripts/setup-antigravity-mcp.sh
   ```
3. **Restart Antigravity IDE.** You should see **agent-builder** and **tools** as available MCP servers.

> **Important:** Always restart/refresh Antigravity IDE after running the setup script or making any changes to MCP configuration. The IDE only loads MCP servers on startup.

Done. For details, prerequisites, and troubleshooting, read on.

---

## What you get after setup

- **agent-builder** – Create and manage agents (goals, nodes, edges).
- **tools** – File operations, web search, and other agent tools.
- **Skills** – Guided docs for building and testing agents (in `.agent/skills/` or `.claude/skills/`).

---

## Prerequisites

- [Antigravity IDE](https://antigravity.google/) installed.
- **Python 3.11+** and project dependencies. If you haven’t set up the repo yet, from repo root run:
  ```bash
  ./quickstart.sh
  ```
- **MCP server dependencies** (one-time). From repo root:
  ```bash
  cd core && ./setup_mcp.sh
  ```

---

## Full setup (step by step)

### Step 1: Install MCP dependencies (one-time)

From the **repo root**:

```bash
cd core
./setup_mcp.sh
```

This installs the framework and MCP packages and checks that the server can start.

### Step 2: Register MCP servers with Antigravity

Antigravity reads MCP config from your **user config file** (`~/.gemini/antigravity/mcp_config.json`), not from the project. The easiest way is to run the setup script from the **hive repo folder**:

```bash
./scripts/setup-antigravity-mcp.sh
```

The script finds the repo root, writes `~/.gemini/antigravity/mcp_config.json` with the right paths, and you don't edit any paths by hand.

> **Important:** Always restart/refresh Antigravity IDE after running the setup script. MCP servers are only loaded on IDE startup.

The **agent-builder** and **tools** servers should show up after restart.

**Using Claude Code instead?** Run:

```bash
./scripts/setup-antigravity-mcp.sh --claude
```

That writes `~/.claude/mcp.json` as well.

**Prefer to do it manually?** See [Manual MCP config](#manual-mcp-config-template) below. You’ll create `~/.gemini/mcp.json` (or `~/.claude/mcp.json`) with absolute paths to your repo’s `core` and `tools` folders.

### Step 3: Use skills

Skills are guides (workflow, building, testing) in `.agent/skills/` (they point to `.claude/skills/`). If Antigravity doesn’t show a “skills” UI, open those folders in the project and use the files as reference while you use the MCP tools.

| Skill | What it's for |
|-------|----------------|
| **hive** | End-to-end workflow for building and testing agents |
| **hive-concepts** | Core ideas for goal-driven agents |
| **hive-create** | Step-by-step agent construction |
| **hive-patterns** | Patterns and best practices |
| **hive-test** | Goal-based evaluation and testing |
| **hive-credentials** | Set up and manage agent credentials |

---

## What’s in the repo (`.agent/`)

```
.agent/
├── mcp_config.json   # Template for MCP servers (agent-builder, tools)
└── skills/           # Symlinks to .claude/skills/
```

The **setup script** writes your **user** config (`~/.gemini/antigravity/mcp_config.json`) using paths from **this repo**. The file in `.agent/` is the template; Antigravity itself uses the file in your home directory.

---

## Troubleshooting

**MCP servers don’t connect**

- Run the setup script again from the hive repo root: `./scripts/setup-antigravity-mcp.sh`, then restart Antigravity.
- Make sure Python and deps are installed: from repo root run `./quickstart.sh`.
- Check that the servers can start: from repo root run
  `cd core && uv run -m framework.mcp.agent_builder_server` (Ctrl+C to stop), and in another terminal
  `cd tools && uv run mcp_server.py --stdio` (Ctrl+C to stop).
  If those fail, fix the errors first (e.g. install deps with `uv sync`).

**"Module not found" or import errors**

- Open the **repo root** as the project in the IDE (the folder that has `core/` and `tools/`).
- If you edited `~/.gemini/antigravity/mcp_config.json` by hand, make sure `--directory` paths are **absolute** (e.g. `/Users/you/hive/core` and `/Users/you/hive/tools`).

**Skills don’t show up in the UI**

- Antigravity may not have a dedicated “skills” panel. Use the files in `.claude/skills/` or `.agent/skills/` as docs; the MCP tools (agent-builder, tools) still work.

---

## Verification prompt (optional)

Paste this into Antigravity to check that MCP and skills are set up. It doesn’t use your machine’s paths; anyone can use it.

```
Check the Hive + Antigravity integration:

1. MCP: List available MCP servers/tools. Confirm that "agent-builder" and "tools" (or equivalent) are connected. If not, tell the user to run ./scripts/setup-antigravity-mcp.sh from the hive repo root, then restart Antigravity (see docs/antigravity-setup.md).

2. Skills: Confirm that the project has .agent/skills/ (or .claude/skills/) with: hive, hive-concepts, hive-create, hive-patterns, hive-test, hive-credentials.

3. Result: Reply with PASS (MCP + skills OK), PARTIAL (only skills or only MCP), or FAIL (neither), and one line on what to fix if not PASS.
```

If you get **PARTIAL** (e.g. MCP not connected), run `./scripts/setup-antigravity-mcp.sh` from the repo root and restart Antigravity.

---

## Manual MCP config template

Use this only if you don’t want to run the setup script. Replace `/path/to/hive` with your actual repo root (e.g. the output of `pwd` when you’re in the hive folder).

Save as `~/.gemini/antigravity/mcp_config.json` (Antigravity) or `~/.claude/mcp.json` (Claude Code), then **restart the IDE** to load the new configuration.

```json
{
  "mcpServers": {
    "agent-builder": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/hive/core", "-m", "framework.mcp.agent_builder_server"],
      "disabled": false
    },
    "tools": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/hive/tools", "mcp_server.py", "--stdio"],
      "disabled": false
    }
  }
}
```

Make sure `uv` is installed and available in your PATH. Note: Use `--directory` in args instead of `cwd` for Antigravity compatibility.

---

## Verify from the command line (optional)

From the **repo root**:

**Check that config and skills exist**

```bash
test -f .agent/mcp_config.json && echo "OK: mcp_config.json" || echo "MISSING"
for s in hive hive-concepts hive-create hive-patterns hive-test hive-credentials; do
  test -L .agent/skills/$s && test -d .agent/skills/$s && echo "OK: $s" || echo "BROKEN: $s"
done
```

**Check that the config is valid JSON**

```bash
python3 -c "import json; json.load(open('.agent/mcp_config.json')); print('OK: valid JSON')"
```

**Test that MCP servers start** (two terminals)

```bash
# Terminal 1
cd core && uv run -m framework.mcp.agent_builder_server

# Terminal 2
cd tools && uv run mcp_server.py --stdio
```

If both start without errors, the config is fine.

---

## See also

- [Cursor IDE support](../README.md#cursor-ide-support) – Same MCP servers and skills for Cursor
- [MCP Integration Guide](../core/MCP_INTEGRATION_GUIDE.md) – How the framework MCP works
- [Environment setup](../ENVIRONMENT_SETUP.md) – Repo and Python setup
