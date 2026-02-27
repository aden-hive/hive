# Hive Coder: Meta-Agent Integration Plan

## Problem

The hive_coder agent currently has 7 file I/O tools (`read_file`, `write_file`, `edit_file`, `list_directory`, `search_files`, `run_command`, `undo_changes`) in `tools/coder_tools_server.py`. It can write agent packages but is **not integrated into the Hive ecosystem**:

1. **No dynamic tool discovery** — It references a static list of hive-tools in `reference/framework_guide.md`. It can't discover what MCP tools are actually available or what parameters they accept.
2. **No runtime observability** — It can't inspect sessions, checkpoints, or logs from agents it builds. When something goes wrong, the user has to manually dig through files.
3. **No test execution** — It can't run an agent's test suite structurally (it could use `run_command` with raw pytest, but has no structured test parsing).

## Solution

Add 8 new tools to `coder_tools_server.py` that give hive_coder deep integration with the Hive framework. Update the system prompt to teach the LLM when and how to use these meta-agent capabilities.

---

## New Tools

### 1. Tool Discovery

**`discover_mcp_tools(server_config_path?)`**

Connect to any MCP server and list all available tools with full schemas. Uses `framework.runner.mcp_client.MCPClient` — the same client the runtime uses. Reads a `mcp_servers.json` file (defaults to hive-tools), connects to each server, calls `list_tools()`, returns tool names + descriptions + input schemas, then disconnects.

This replaces the static tools reference. The LLM now discovers tools dynamically before designing an agent.

### 2. Agent Inventory

**`list_agents()`**

Scan `exports/` for agent packages and `~/.hive/agents/` for runtime data. Returns agent names, descriptions (from `__init__.py`), and session counts. Gives the LLM awareness of what already exists.

### 3-7. Session & Checkpoint Inspection

Ported from `agent_builder_server.py` lines 3484-3856. Pure filesystem reads — JSON + pathlib, zero framework imports.

| Tool | Purpose |
|------|---------|
| `list_agent_sessions(agent_name, status?, limit?)` | List sessions, filterable by status |
| `get_agent_session_state(agent_name, session_id)` | Full session state (memory excluded to prevent context bloat) |
| `get_agent_session_memory(agent_name, session_id, key?)` | Read memory contents from a session |
| `list_agent_checkpoints(agent_name, session_id)` | List checkpoints for debugging |
| `get_agent_checkpoint(agent_name, session_id, checkpoint_id?)` | Load a checkpoint's full state |

**Key difference from agent-builder:** These tools accept `agent_name` (e.g. `"deep_research_agent"`) instead of raw `agent_work_dir` paths. They resolve to `~/.hive/agents/{agent_name}/` internally. Friendlier for the LLM.

### 8. Test Execution

**`run_agent_tests(agent_name, test_types?, fail_fast?)`**

Ported from `agent_builder_server.py` lines 2756-2920. Runs pytest on an agent's test suite, sets PYTHONPATH automatically, parses output into structured results (passed/failed/skipped counts, per-test status, failure details).

---

## Files to Modify

### `tools/coder_tools_server.py` (~400 new lines)

Add all 8 tools after the existing `undo_changes` tool:

```
# ── Meta-agent: Tool discovery ────────────────────────────────
# discover_mcp_tools()

# ── Meta-agent: Agent inventory ───────────────────────────────
# list_agents()

# ── Meta-agent: Session & checkpoint inspection ───────────────
# _resolve_hive_agent_path(), _read_session_json(), _scan_agent_sessions(), _truncate_value()
# list_agent_sessions(), get_agent_session_state(), get_agent_session_memory()
# list_agent_checkpoints(), get_agent_checkpoint()

# ── Meta-agent: Test execution ────────────────────────────────
# run_agent_tests()
```

### `exports/hive_coder/nodes/__init__.py`

- Add 8 new tool names to the `tools` list
- Rewrite system prompt "Tools Available" section with meta-agent tools
- Add "Meta-Agent Capabilities" section teaching:
  - Tool discovery before designing agents
  - Post-build test execution
  - Debugging via session/checkpoint inspection
  - Agent awareness via `list_agents()`

### `exports/hive_coder/agent.py`

- Update `identity_prompt` to mention dynamic tool discovery and runtime observability
- Add `dynamic-tool-discovery` constraint to the goal

### `exports/hive_coder/reference/framework_guide.md`

Replace static tools list with a note to use `discover_mcp_tools()` instead.

---

## What's NOT in Scope (deferred to v2)

- **Agent notifications / webhook listener** — Requires always-on listener architecture
- **`compare_agent_checkpoints`** — LLM can compare by reading two checkpoints sequentially
- **Runtime log query tools** — Available in hive-tools MCP; `run_command` can access them now

---

## Verification

1. MCP server starts with all 15 tools (7 existing + 8 new)
2. `discover_mcp_tools()` connects to hive-tools and returns real tool schemas
3. Agent validation passes (`default_agent.validate()`)
4. Session tools work against existing data in `~/.hive/agents/`
5. Smoke test: launch in TUI, ask it to discover tools
