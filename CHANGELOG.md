# Release Notes

## v0.7.1

**Release Date:** March 13, 2026
**Tag:** v0.7.1

### Chrome-Native Browser Control

v0.7.1 replaces Playwright with direct Chrome DevTools Protocol (CDP) integration. The GCU now launches the user's system Chrome via `open -n` on macOS, connects over CDP, and manages browser lifecycle end-to-end -- no extra browser binary required.

---

### Highlights

#### System Chrome via CDP

The entire GCU browser stack has been rewritten:

- **Chrome finder & launcher** -- New `chrome_finder.py` discovers installed Chrome and `chrome_launcher.py` manages process lifecycle with `--remote-debugging-port`
- **Coexist with user's browser** -- `open -n` on macOS launches a separate Chrome instance so the user's tabs stay untouched
- **Dynamic viewport sizing** -- Viewport auto-sizes to the available display area, suppressing Chrome warning bars
- **Orphan cleanup** -- Chrome processes are killed on GCU server shutdown to prevent leaks
- **`--no-startup-window`** -- Chrome launches headlessly by default until a page is needed

#### Per-Subagent Browser Isolation

Each GCU subagent gets its own Chrome user-data directory, preventing cookie/session cross-contamination:

- Unique browser profiles injected per subagent
- Profiles cleaned up after top-level GCU node execution
- Tab origin and age metadata tracked per subagent

#### Dummy Agent Testing Framework

A comprehensive test suite for validating agent graph patterns without LLM calls:

- 8 test modules covering echo, pipeline, branch, parallel merge, retry, feedback loop, worker, and GCU subagent patterns
- Shared fixtures and a `run_all.py` runner for CI integration
- Subagent lifecycle tests

---

### What's New

#### GCU Browser

- **Switch from Playwright to system Chrome via CDP** -- Direct CDP connection replaces Playwright dependency. (@bryanadenhq)
- **Chrome finder and launcher modules** -- `chrome_finder.py` and `chrome_launcher.py` for cross-platform Chrome discovery and process management. (@bryanadenhq)
- **Dynamic viewport sizing** -- Auto-size viewport and suppress Chrome warning bar. (@bryanadenhq)
- **Per-subagent browser profile isolation** -- Unique user-data directories per subagent with cleanup. (@bryanadenhq)
- **Tab origin/age metadata** -- Track which subagent opened each tab and when. (@bryanadenhq)
- **`browser_close_all` tool** -- Bulk tab cleanup for agents managing many pages. (@bryanadenhq)
- **Auto-track popup pages** -- Popups are automatically captured and tracked. (@bryanadenhq)
- **Auto-snapshot from browser interactions** -- Browser interaction tools return screenshots automatically. (@bryanadenhq)
- **Kill orphaned Chrome processes** -- GCU server shutdown cleans up lingering Chrome instances. (@bryanadenhq)
- **`--no-startup-window` Chrome flag** -- Prevent empty window on launch. (@bryanadenhq)
- **Launch Chrome via `open -n` on macOS** -- Coexist with the user's running browser. (@bryanadenhq)

#### Framework & Runtime

- **Session resume fix for new agents** -- Correctly resume sessions when a new agent is loaded. (@bryanadenhq)
- **Queen upsert fix** -- Prevent duplicate queen entries on session restore. (@bryanadenhq)
- **Anchor worker monitoring to queen's session ID on cold-restore** -- Worker monitors reconnect to the correct queen after restart. (@bryanadenhq)
- **Update meta.json when loading workers** -- Worker metadata stays in sync with runtime state. (@RichardTang-Aden)
- **Generate worker MCP file correctly** -- Fix MCP config generation for spawned workers. (@RichardTang-Aden)
- **Share event bus so tool events are visible to parent** -- Tool execution events propagate up to parent graphs. (@bryanadenhq)
- **Subagent activity tracking in queen status** -- Queen instructions include live subagent status. (@bryanadenhq)
- **GCU system prompt updates** -- Auto-snapshots, batching, popup tracking, and close_all guidance. (@bryanadenhq)

#### Frontend

- **Loading spinner in draft panel** -- Shows spinner during planning phase instead of blank panel. (@bryanadenhq)
- **Fix credential modal errors** -- Modal no longer eats errors; banner stays visible. (@bryanadenhq)
- **Fix credentials_required loop** -- Stop clearing the flag on modal close to prevent infinite re-prompting. (@bryanadenhq)
- **Fix "Add tab" dropdown overflow** -- Dropdown no longer hidden when many agents are open. (@prasoonmhwr)

#### Testing

- **Dummy agent test framework** -- 8 test modules (echo, pipeline, branch, parallel merge, retry, feedback loop, worker, GCU subagent) with shared fixtures and CI runner. (@bryanadenhq)
- **Subagent lifecycle tests** -- Validate subagent spawn and completion flows. (@bryanadenhq)

#### Documentation & Infrastructure

- **MCP integration PRD** -- Product requirements for MCP server registry. (@TimothyZhang7)
- **Skills registry PRD** -- Product requirements for skill registry system. (@bryanadenhq)
- **Bounty program updates** -- Standard bounty issue template and updated contributor guide. (@bryanadenhq)
- **Windows quickstart** -- Add default context limit for PowerShell setup. (@bryanadenhq)
- **Remove deprecated files** -- Clean up `setup_mcp.py`, `verify_mcp.py`, `antigravity-setup.md`, and `setup-antigravity-mcp.sh`. (@bryanadenhq)

---

### Bug Fixes

- Fix credential modal eating errors and banner staying open
- Stop clearing `credentials_required` on modal close to prevent infinite loop
- Share event bus so tool events are visible to parent graph
- Use lazy %-formatting in subagent completion log to avoid f-string in logger
- Anchor worker monitoring to queen's session ID on cold-restore
- Update meta.json when loading workers
- Generate worker MCP file correctly
- Fix "Add tab" dropdown partially hidden when creating multiple agents

---

### Community Contributors

- **Prasoon Mahawar** (@prasoonmhwr) -- Fix UI overflow on agent tab dropdown
- **Richard Tang** (@RichardTang-Aden) -- Worker MCP generation and meta.json fixes

---

### Upgrading

```bash
git pull origin main
uv sync
```

The Playwright dependency is no longer required for GCU browser operations. Chrome must be installed on the host system.

---

## v0.7.0

**Release Date:** March 5, 2026
**Tag:** v0.7.0

Session management refactor release.

---

## v0.5.1

**Release Date:** February 18, 2026
**Tag:** v0.5.1

### The Hive Gets a Brain

v0.5.1 is our most ambitious release yet. Hive agents can now **build other agents** -- the new Hive Coder meta-agent writes, tests, and fixes agent packages from natural language. The runtime grows multi-graph support so one session can orchestrate multiple agents simultaneously. The TUI gets a complete overhaul with an in-app agent picker, live streaming, and seamless escalation to the Coder. And we're now provider-agnostic: Claude Code subscriptions, OpenAI-compatible endpoints, and any LiteLLM-supported model work out of the box.

---

### Highlights

#### Hive Coder -- The Agent That Builds Agents

A native meta-agent that lives inside the framework at `core/framework/agents/hive_coder/`. Give it a natural-language specification and it produces a complete agent package -- goal definition, node prompts, edge routing, MCP tool wiring, tests, and all boilerplate files.

```bash
# Launch the Coder directly
hive code

# Or escalate from any running agent (TUI)
Ctrl+E  # or /coder in chat
```

The Coder ships with:

- **Reference documentation** -- anti-patterns, construction guide, and design patterns baked into its system prompt
- **Guardian watchdog** -- an event-driven monitor that catches agent failures and triggers automatic remediation
- **Coder Tools MCP server** -- file I/O, fuzzy-match editing, git snapshots, and sandboxed shell execution (`tools/coder_tools_server.py`)
- **Test generation** -- structural tests for forever-alive agents that don't hang on `runner.run()`

#### Multi-Graph Agent Runtime

`AgentRuntime` now supports loading, managing, and switching between multiple agent graphs within a single session. Six new lifecycle tools give agents (and the TUI) full control:

```python
# Load a second agent into the runtime
await runtime.add_graph("exports/deep_research_agent")

# Tools available to agents:
# load_agent, unload_agent, start_agent, restart_agent, list_agents, get_user_presence
```

The Hive Coder uses multi-graph internally -- when you escalate from a worker agent, the Coder loads as a separate graph while the worker stays alive in the background.

#### TUI Revamp

The Terminal UI gets a ground-up rebuild with five major additions:

- **Agent Picker** (Ctrl+A) -- tabbed modal screen for browsing Your Agents, Framework agents, and Examples with metadata badges (node count, tool count, session count, tags)
- **Runtime-optional startup** -- TUI launches without a pre-loaded agent, showing the picker on first open
- **Live streaming pane** -- dedicated RichLog widget shows LLM tokens as they arrive, replacing the old one-token-per-line display
- **PDF attachments** -- `/attach` and `/detach` commands with native OS file dialog (macOS, Linux, Windows)
- **Multi-graph commands** -- `/graphs`, `/graph <id>`, `/load <path>`, `/unload <id>` for managing agent graphs in-session

#### Provider-Agnostic LLM Support

Hive is no longer Anthropic-only. v0.5.1 adds first-class support for:

- **Claude Code subscriptions** -- `use_claude_code_subscription: true` in `~/.hive/configuration.json` reads OAuth tokens from `~/.claude/.credentials.json` with automatic refresh
- **OpenAI-compatible endpoints** -- `api_base` config routes traffic through any compatible API (Azure OpenAI, vLLM, Ollama, etc.)
- **Any LiteLLM model** -- `RuntimeConfig` now passes `api_key`, `api_base`, and `extra_kwargs` through to LiteLLM

The quickstart script auto-detects Claude Code subscriptions and ZAI Code installations.

---

### What's New

#### Architecture & Runtime

- **Hive Coder meta-agent** -- Natural-language agent builder with reference docs, guardian watchdog, and `hive code` CLI command. (@TimothyZhang7)
- **Multi-graph agent sessions** -- `add_graph`/`remove_graph` on AgentRuntime with 6 lifecycle tools (`load_agent`, `unload_agent`, `start_agent`, `restart_agent`, `list_agents`, `get_user_presence`). (@TimothyZhang7)
- **Claude Code subscription support** -- OAuth token refresh via `use_claude_code_subscription` config, auto-detection in quickstart, LiteLLM header patching. (@TimothyZhang7)
- **OpenAI-compatible endpoint support** -- `api_base` and `extra_kwargs` in `RuntimeConfig` for any OpenAI-compatible API. (@TimothyZhang7)
- **Remove deprecated node types** -- Delete `FlexibleGraphExecutor`, `WorkerNode`, `HybridJudge`, `CodeSandbox`, `Plan`, `FunctionNode`, `LLMNode`, `RouterNode`. Deprecated types (`llm_tool_use`, `llm_generate`, `function`, `router`, `human_input`) now raise `RuntimeError` with migration guidance. (@TimothyZhang7)
- **Interactive credential setup** -- Guided `CredentialSetupSession` with health checks and encrypted storage, accessible via `hive setup-credentials` or automatic prompting on credential errors. (@RichardTang-Aden)
- **Pre-start confirmation prompt** -- Interactive prompt before agent execution allowing credential updates or abort. (@RichardTang-Aden)
- **Event bus multi-graph support** -- `graph_id` on events, `filter_graph` on subscriptions, `ESCALATION_REQUESTED` event type, `exclude_own_graph` filter. (@TimothyZhang7)

#### TUI Improvements

- **In-app agent picker** (Ctrl+A) -- Tabbed modal for browsing agents with metadata badges (nodes, tools, sessions, tags). (@TimothyZhang7)
- **Runtime-optional TUI startup** -- Launches without a pre-loaded agent, shows agent picker on startup. (@TimothyZhang7)
- **Hive Coder escalation** (Ctrl+E) -- Escalate to Hive Coder and return; also available via `/coder` and `/back` chat commands. (@TimothyZhang7)
- **PDF attachment support** -- `/attach` and `/detach` commands with native OS file dialog. (@TimothyZhang7)
- **Streaming output pane** -- Dedicated RichLog widget for live LLM token streaming. (@TimothyZhang7)
- **Multi-graph TUI commands** -- `/graphs`, `/graph <id>`, `/load <path>`, `/unload <id>`. (@TimothyZhang7)
- **Agent Guardian watchdog** -- Event-driven monitor that catches secondary agent failures and triggers automatic remediation, with `--no-guardian` CLI flag. (@TimothyZhang7)

#### New Tool Integrations

| Tool                   | Description                                                                                                                                                            | Contributor        |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| **Discord**            | 4 MCP tools (`discord_list_guilds`, `discord_list_channels`, `discord_send_message`, `discord_get_messages`) with rate-limit retry and channel filtering               | @mishrapravin114   |
| **Exa Search API**     | 4 AI-powered search tools (`exa_search`, `exa_find_similar`, `exa_get_contents`, `exa_answer`) with neural/keyword search, domain filters, and citation-backed answers | @JeetKaria06       |
| **Razorpay**           | 6 payment processing tools for payments, invoices, payment links, and refunds with HTTP Basic Auth                                                                     | @shivamshahi07     |
| **Google Docs**        | Document creation, reading, and editing with OAuth credential support                                                                                                  | @haliaeetusvocifer |
| **Gmail enhancements** | Expanded mail operations for inbox management                                                                                                                          | @bryanadenhq       |

#### Infrastructure

- **Default node type → `event_loop`** -- `NodeSpec.node_type` defaults to `"event_loop"` instead of `"llm_tool_use"`. (@TimothyZhang7)
- **Default `max_node_visits` → 0 (unlimited)** -- Nodes default to unlimited visits, reducing friction for feedback loops and forever-alive agents. (@TimothyZhang7)
- **Remove `function` field from NodeSpec** -- Follows deprecation of `FunctionNode`. (@TimothyZhang7)
- **LiteLLM OAuth patch** -- Correct header construction for OAuth tokens (remove `x-api-key` when Bearer token is present). (@TimothyZhang7)
- **Orchestrator config centralization** -- Reads `api_key`, `api_base`, `extra_kwargs` from centralized `~/.hive/configuration.json`. (@TimothyZhang7)
- **System prompt datetime injection** -- All system prompts now include current date/time for time-aware agent behavior. (@TimothyZhang7)
- **Utils module exports** -- Proper `__init__.py` exports for the utils module. (@Siddharth2624)
- **Increased default max_tokens** -- Opus 4.6 defaults to 32768, Sonnet 4.5 to 16384 (up from 8192). (@TimothyZhang7)

---

### Bug Fixes

- Flush WIP accumulator outputs on cancel/failure so edge conditions see correct values on resume
- Stall detection state preserved across resume (no more resets on checkpoint restore)
- Skip client-facing blocking for event-triggered executions (timer/webhook)
- Executor retry override scoped to actual EventLoopNode instances only
- Add `_awaiting_input` flag to EventLoopNode to prevent input injection race conditions
- Fix TUI streaming display (tokens no longer appear one-per-line)
- Fix `_return_from_escalation` crash when ChatRepl widgets not yet mounted
- Fix tools registration problems for Google Docs credentials (@RichardTang-Aden)
- Fix email agent version conflicts (@RichardTang-Aden)
- Fix coder tool timeouts (120s for tests, 300s cap for commands)

### Documentation

- Clarify installation and prevent root pip install misuse (@paarths-collab)

---

### Agent Updates

- **Email Inbox Management** -- Consolidate `gmail_inbox_guardian` and `inbox_management` into a single unified agent with updated prompts and config. (@RichardTang-Aden, @bryanadenhq)
- **Job Hunter** -- Updated node prompts, config, and agent metadata; added PDF resume selection. (@bryanadenhq)
- **Deep Research Agent** -- Revised node implementations with updated prompts and output handling.
- **Tech News Reporter** -- Revised node prompts for improved output quality.
- **Vulnerability Assessment** -- Expanded prompts with more detailed assessment instructions. (@bryanadenhq)

---

### Breaking Changes

- **Deprecated node types raise `RuntimeError`** -- `llm_tool_use`, `llm_generate`, `function`, `router`, `human_input` now fail instead of warning. Migrate to `event_loop`.
- **`NodeSpec.node_type` defaults to `"event_loop"`** (was `"llm_tool_use"`)
- **`NodeSpec.max_node_visits` defaults to `0` / unlimited** (was `1`)
- **`NodeSpec.function` field removed** -- `FunctionNode` is deleted; use event_loop nodes with tools instead.

---

### Community Contributors

A huge thank you to everyone who contributed to this release:

- **Richard Tang** (@RichardTang-Aden) -- Interactive credential setup, pre-start confirmation, email agent consolidation, tool registration fixes, lint and formatting
- **Pravin Mishra** (@mishrapravin114) -- Discord integration with 4 MCP tools
- **Jeet Karia** (@JeetKaria06) -- Exa Search API integration with 4 AI-powered search tools
- **Shivam Shahi** (@shivamshahi07) -- Razorpay payment processing integration
- **Siddharth Varshney** (@Siddharth2624) -- Utils module exports
- **@haliaeetusvocifer** -- Google Docs integration with OAuth support
- **Bryan** (@bryanadenhq) -- PDF selection, inbox agent fixes, Job Hunter and Vulnerability Assessment updates
- **@paarths-collab** -- Documentation improvements

---

### Upgrading

```bash
git pull origin main
uv sync
```

#### Migration Guide

If your agents use deprecated node types, update them:

```python
# Before (v0.5.0) -- these now raise RuntimeError
NodeSpec(node_type="llm_tool_use", ...)
NodeSpec(node_type="function", function=my_func, ...)

# After (v0.5.1) -- use event_loop for everything
NodeSpec(node_type="event_loop", ...)  # or just omit node_type (it's the default now)
```

If your agents set `max_node_visits=1` explicitly, they'll still work. The only change is the _default_ -- new agents without an explicit value now get unlimited visits.

To try the new Hive Coder:

```bash
# Launch Coder directly
hive code

# Or from TUI -- press Ctrl+E to escalate
hive tui
```
