# Changelog

## v0.5.1 (2026-02-18)

A major release introducing the Hive Coder meta-agent, multi-graph runtime, TUI overhaul, subscription model support, and 5 new tool integrations.

### Highlights

- **Hive Coder** — A native meta-agent that builds and modifies Hive agent packages from natural-language specifications, complete with reference docs, guardian watchdog, and `hive code` CLI command.
- **Multi-Graph Runtime** — AgentRuntime now supports loading, managing, and switching between multiple agent graphs within a single session.
- **TUI Revamp** — In-app agent picker, PDF attachments, streaming output pane, Hive Coder escalation, and runtime-optional startup.
- **Subscription & Endpoint Support** — First-class Claude Code OAuth subscription support and OpenAI-compatible endpoint routing.

### Features

- **Multi-graph agent sessions**: `add_graph`/`remove_graph` on AgentRuntime plus 6 lifecycle tools (`load_agent`, `unload_agent`, `start_agent`, `restart_agent`, `list_agents`, `get_user_presence`)
- **Claude Code subscription support**: Automatic OAuth token refresh via `use_claude_code_subscription` config, with auto-detection in quickstart
- **OpenAI-compatible endpoints**: `api_base` and `extra_kwargs` in `RuntimeConfig` for routing LLM traffic through any compatible API
- **Interactive credential setup**: Guided `CredentialSetupSession` with health checks and encrypted storage, accessible via `hive setup-credentials` or automatic prompting
- **Agent escalation to Hive Coder**: Client-facing nodes can call `escalate_to_coder` to hand off to Hive Coder with automatic state preservation and restoration
- **Coder Tools MCP server**: File I/O, fuzzy-match editing, git snapshots, and sandboxed shell execution for the Hive Coder agent
- **Pre-start confirmation prompt**: Interactive prompt before agent execution allowing credential updates or abort

### TUI

- **In-app agent picker** (Ctrl+A): Tabbed modal for browsing Your Agents, Framework, and Example agents with metadata badges
- **Runtime-optional startup**: TUI launches without a pre-loaded agent, showing the agent picker on startup
- **Hive Coder escalation** (Ctrl+E): Escalate to Hive Coder and return with `/coder` and `/back` commands
- **PDF attachment support**: `/attach` and `/detach` commands with native OS file dialog
- **Streaming output pane**: Dedicated RichLog widget for live LLM token streaming
- **Multi-graph commands**: `/graphs`, `/graph <id>`, `/load <path>`, `/unload <id>` for managing multiple graphs
- **Agent Guardian watchdog**: Event-driven monitor that catches secondary agent failures with automatic remediation

### Tool Integrations

- **Discord**: 4 MCP tools (`discord_list_guilds`, `discord_list_channels`, `discord_send_message`, `discord_get_messages`) with rate-limit retry
- **Exa Search API**: 4 AI-powered search tools (`exa_search`, `exa_find_similar`, `exa_get_contents`, `exa_answer`) with neural/keyword search
- **Razorpay**: 6 payment tools for payments, invoices, payment links, and refunds
- **Google Docs**: Document creation, reading, and editing with OAuth credential support
- **Gmail enhancements**: Expanded mail operations

### Infrastructure

- **Remove deprecated node types**: Delete `FlexibleGraphExecutor`, `WorkerNode`, `HybridJudge`, `CodeSandbox`, `Plan`, `FunctionNode`, `LLMNode`, `RouterNode`; deprecated types now raise `RuntimeError` with migration guidance
- **Default node type → `event_loop`**: `NodeSpec.node_type` defaults to `"event_loop"` instead of `"llm_tool_use"`
- **Default `max_node_visits` → 0 (unlimited)**: Nodes default to unlimited visits, reducing friction for feedback loops and forever-alive agents
- **Remove `function` field from NodeSpec**: Follows deprecation of `FunctionNode`
- **LiteLLM OAuth patch**: Correct header construction for OAuth tokens (remove `x-api-key` when Bearer token is present)
- **Event bus multi-graph support**: `graph_id` on events, `filter_graph` on subscriptions, `ESCALATION_REQUESTED` event type
- **ExecutionStream graph_id tagging**: Streams carry `graph_id` propagated to all emitted events
- **Orchestrator config centralization**: Reads `api_key`, `api_base`, `extra_kwargs` from centralized config
- **System prompt datetime injection**: All system prompts now include current date/time for time-aware behavior
- **Utils module exports**: Proper `__init__.py` exports for the utils module

### Bug Fixes

- Flush WIP accumulator outputs on cancel/failure so edge conditions see correct values on resume
- Stall detection state preserved across resume (no more resets on checkpoint restore)
- Skip client-facing blocking for event-triggered executions (timer/webhook)
- Executor retry override scoped to actual EventLoopNode instances only
- Add `_awaiting_input` flag to EventLoopNode to prevent input injection race conditions
- Fix TUI streaming display (tokens no longer appear one-per-line)
- Fix `_return_from_escalation` crash when ChatRepl widgets not yet mounted

### Agent Updates

- Consolidate email agents into single `email_inbox_management` agent
- Update prompts for Deep Research, Job Hunter, Tech News Reporter, and Vulnerability Assessment agents

### Breaking Changes

- Deprecated node types (`llm_tool_use`, `llm_generate`, `function`, `router`, `human_input`) now raise `RuntimeError` instead of warnings — migrate to `event_loop`
- `NodeSpec.node_type` defaults to `"event_loop"` (was `"llm_tool_use"`)
- `NodeSpec.max_node_visits` defaults to `0` / unlimited (was `1`)
- `NodeSpec.function` field removed

---

## v0.5.0

Initial public release.
