# Hive Queen Bee: Native agent-building agent

## Problem

Building a Hive agent today requires manual assembly of 7+ files (`agent.py`, `config.py`, `nodes/__init__.py`, `__init__.py`, `__main__.py`, `mcp_servers.json`, tests) with precise framework conventions — correct imports, entry_points format, conversation_mode values, STEP 1/STEP 2 prompt patterns, nullable_output_keys, and more. A single missing re-export in `__init__.py` silently breaks `AgentRunner.load()`. This is the #1 friction point for new users and a recurring source of bugs even for experienced ones.

There is no tool that understands the framework deeply enough to produce correct agents. General-purpose coding assistants hallucinate tool names, use wrong import paths (`from core.framework...`), create too many thin nodes, forget module-level exports, and produce agents that fail validation.

## Proposal

Build **Hive Coder** (codename "Queen Bee") — a framework-native coding agent that lives inside the framework itself and builds complete, validated agent packages from natural language.

### Design principles

1. **Single-node, forever-alive** — One continuous EventLoopNode conversation handles the full lifecycle (understand, qualify, design, implement, verify, iterate). No artificial phase boundaries that destroy context.

2. **Meta-agent capabilities** — Not just a file writer. Can discover available MCP tools at runtime, inspect sessions/checkpoints of agents it builds, run their test suites, and debug failures.

3. **Self-verifying** — Runs three validation steps after every build: class validation (graph structure), `AgentRunner.load()` (package export contract), and pytest. Fixes its own errors up to 3 attempts.

4. **Honest qualification** — Assesses framework fit before building. If a use case is a poor fit (needs sub-second latency, pure CRUD, massive data pipelines), says so instead of producing a bad agent.

5. **Reference-grounded** — Ships with embedded reference docs (framework guide, file templates, anti-patterns) that it reads before writing code. No reliance on training data for framework specifics.

### Components

#### `hive_coder` agent (`core/framework/agents/hive_coder/`)

| File | Purpose |
|------|---------|
| `agent.py` | Goal, single-node graph, `HiveCoderAgent` class |
| `nodes/__init__.py` | `coder` EventLoopNode with comprehensive system prompt |
| `config.py` | RuntimeConfig with `~/.hive/configuration.json` auto-detection |
| `__main__.py` | Click CLI (`run`, `tui`, `info`, `validate`, `shell`) |
| `reference/framework_guide.md` | Node types, edges, patterns, async entry points |
| `reference/file_templates.md` | Complete code templates for every agent file |
| `reference/anti_patterns.md` | 22 common mistakes with explanations |

#### Coder Tools MCP Server (`tools/coder_tools_server.py`)

Dedicated tool server providing:

- **File I/O**: `read_file` (with line numbers, offset/limit), `write_file` (auto-mkdir), `edit_file` (9-strategy fuzzy matching ported from opencode), `list_directory`, `search_files` (regex)
- **Shell**: `run_command` (timeout, cwd, output truncation)
- **Git**: `undo_changes` (snapshot-based rollback)
- **Meta-agent**: `discover_mcp_tools`, `list_agents`, `list_agent_sessions`, `get_agent_session_state`, `get_agent_session_memory`, `list_agent_checkpoints`, `get_agent_checkpoint`, `run_agent_tests`

All file operations sandboxed to a configurable project root.

#### Framework changes

- `hive code` CLI command — direct launch shortcut
- `hive tui` — discovers framework agents as a source
- `AgentRuntime` — cron expression support (`croniter`) for async entry points
- `prompt_composer` — appends current datetime to system prompts
- `NodeSpec.max_node_visits` — default changed from 1 to 0 (unbounded), matching forever-alive as the standard pattern
- TUI graph view — cron display and hours in countdown
- CredentialError graceful handling in TUI launch

## Acceptance criteria

- [ ] `hive code` launches Hive Coder in the TUI
- [ ] `hive tui` lists framework agents alongside exports/ and examples/
- [ ] Given "build me a research agent that searches the web and summarizes findings", Hive Coder produces a valid package in `exports/` that passes `AgentRunner.load()`
- [ ] Tool discovery works: agent calls `discover_mcp_tools()` before designing, never fabricates tool names
- [ ] Self-verification: agent runs all 3 validation steps and fixes errors before presenting
- [ ] Cron timers fire on schedule (unit tested)
- [ ] `max_node_visits=0` default does not break existing agents or tests
- [ ] Reference docs are accurate and match current framework behavior

## Non-goals

- Multi-agent orchestration (queen spawning worker agents at runtime) — future work
- GUI/web interface — TUI only for v1
- Auto-publishing to a registry — agents are local packages
