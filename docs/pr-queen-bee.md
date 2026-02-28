# feat(queen): Hive Queen Bee — native agent-building agent

## Summary

Introduces **Hive Coder** (codename "Queen Bee"), a framework-native coding agent that builds complete Hive agent packages from natural language descriptions. This is a single-node, forever-alive agent inspired by opencode's `while(true)` loop — one continuous conversation handles the full lifecycle: understand, qualify, design, implement, verify, and iterate.

The agent is deeply integrated with the framework: it can discover available MCP tools at runtime, inspect sessions and checkpoints of agents it builds, run their test suites, and self-verify its own output. It ships with a dedicated MCP tools server (`coder_tools_server.py`) providing rich file I/O, fuzzy-match editing, git snapshots, and shell execution — all scoped to a configurable project root.

## What's included

### New: `hive_coder` agent (`core/framework/agents/hive_coder/`)
- **`agent.py`** — Goal with 4 success criteria and 4 constraints, single-node graph, `HiveCoderAgent` class with full runtime lifecycle (start/stop/trigger_and_wait)
- **`nodes/__init__.py`** — Single `coder` EventLoopNode with a comprehensive system prompt covering coding mandates, tool discovery, meta-agent capabilities, node count rules, implementation templates, and a 6-phase workflow
- **`config.py`** — RuntimeConfig with auto-detection of preferred model from `~/.hive/configuration.json`
- **`__main__.py`** — Click CLI with `run`, `tui`, `info`, `validate`, and `shell` subcommands
- **`reference/`** — Framework guide, file templates, and anti-patterns docs embedded as agent reference material

### New: Coder Tools MCP Server (`tools/coder_tools_server.py`)
- 1500-line MCP server providing 15 tools: `read_file`, `write_file`, `edit_file` (with opencode-style 9-strategy fuzzy matching), `list_directory`, `search_files`, `run_command`, `undo_changes`, `discover_mcp_tools`, `list_agents`, `list_agent_sessions`, `get_agent_session_state`, `get_agent_session_memory`, `list_agent_checkpoints`, `get_agent_checkpoint`, `run_agent_tests`
- Path-scoped security: all file operations sandboxed to project root
- Git-based undo: automatic snapshots before writes with `undo_changes` rollback

### Framework changes
- **`hive code` CLI command** — Direct launch shortcut for Hive Coder via `cmd_code` in `runner/cli.py`
- **`hive tui` updated** — Now discovers framework agents alongside exports/ and examples/
- **Cron timer support** — `AgentRuntime` now supports cron expressions (`croniter`) in addition to fixed-interval timers for async entry points
- **Datetime in system prompts** — `prompt_composer._with_datetime()` appends current datetime to all composed system prompts; EventLoopNode also applies it for isolated conversations
- **`max_node_visits` default → 0** — Changed from 1 to 0 (unbounded) across `NodeSpec` and executor, matching the forever-alive pattern as the standard default
- **TUI graph view** — Timer display updated to show cron expressions and hours in countdown
- **CredentialError handling** — `_setup()` calls in TUI launch paths now catch and display credential errors gracefully

### Tests
- New `test_agent_runtime.py` tests for cron-based timer scheduling

## Architecture

```
User ──▶ [coder] (EventLoopNode, client_facing, forever-alive)
              │
              │  Tools: coder_tools_server.py (file I/O, shell, git)
              │         + meta-agent tools (discover, inspect, test)
              │
              └──▶ loops continuously until user exits
```

Single node. No edges. No terminal nodes. The agent stays alive and handles multiple build requests in one session — context accumulates across interactions.

## Test plan

- [ ] `hive code` launches Hive Coder TUI successfully
- [ ] `hive tui` shows "Framework Agents" as a source option
- [ ] Agent can discover tools via `discover_mcp_tools()`
- [ ] Agent generates a valid agent package from a natural language request
- [ ] Generated packages pass `AgentRunner.load()` validation
- [ ] Cron timer tests pass (`test_agent_runtime.py`)
- [ ] Existing tests unaffected by `max_node_visits` default change
