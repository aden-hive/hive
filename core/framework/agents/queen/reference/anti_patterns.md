# Common Mistakes When Building Hive Agents

## Critical Errors
1. **Using tools that don't exist** — Always verify tools via `list_agent_tools()` before designing. Common hallucinations: `csv_read`, `csv_write`, `file_upload`, `database_query`, `bulk_fetch_emails`.
2. **Wrong mcp_servers.json format** — Flat dict (no `"mcpServers"` wrapper). `cwd` must be `"../../tools"`. `command` must be `"uv"` with args `["run", "python", ...]`.
3. **Missing module-level exports in `__init__.py`** — The runner reads `goal`, `nodes`, `edges`, `entry_node`, `entry_points`, `terminal_nodes`, `conversation_mode`, `identity_prompt`, `loop_config` via `getattr()`. ALL module-level variables from agent.py must be re-exported in `__init__.py`.

## Value Errors
4. **Fabricating tools** — Always verify via `list_agent_tools()` before designing and `validate_agent_package()` after building.

## Design Errors
5. **Adding framework gating for LLM behavior** — Don't add output rollback or premature rejection. Fix with better prompts or custom judges.
6. **Calling set_output in same turn as tool calls** — Call set_output in a SEPARATE turn.

## File Template Errors
7. **Wrong import paths** — Use `from framework.graph import ...`, NOT `from core.framework.graph import ...`.
8. **Missing storage path** — Agent class must set `self._storage_path = Path.home() / ".hive" / "agents" / "agent_name"`.
9. **Missing mcp_servers.json** — Without this, the agent has no tools at runtime.
10. **Bare `python` command** — Use `"command": "uv"` with args `["run", "python", ...]`.

## Testing Errors
11. **Using `runner.run()` on forever-alive agents** — `runner.run()` hangs forever because forever-alive agents have no terminal node. Write structural tests instead: validate graph structure, verify node specs, test `AgentRunner.load()` succeeds (no API key needed).
12. **Stale tests after restructuring** — When changing nodes/edges, update tests to match. Tests referencing old node names will fail.
13. **Running integration tests without API keys** — Use `pytest.skip()` when credentials are missing.
14. **Forgetting sys.path setup in conftest.py** — Tests need `exports/` and `core/` on sys.path.

## GCU Errors
15. **Manually wiring browser tools on event_loop nodes** — Use `node_type="gcu"` which auto-includes browser tools. Do NOT manually list browser tool names.
16. **Using GCU nodes as regular graph nodes** — GCU nodes are subagents only. They must ONLY appear in `sub_agents=["gcu-node-id"]` and be invoked via `delegate_to_sub_agent()`. Never connect via edges or use as entry/terminal nodes.
17. **Reusing the same GCU node ID for parallel tasks** — Each concurrent browser task needs a distinct GCU node ID (e.g. `gcu-site-a`, `gcu-site-b`). Two `delegate_to_sub_agent` calls with the same `agent_id` share a browser profile and will interfere with each other's pages.
18. **Passing `profile=` in GCU tool calls** — Profile isolation for parallel subagents is automatic. The framework injects a unique profile per subagent via an asyncio `ContextVar`. Hardcoding `profile="default"` in a GCU system prompt breaks this isolation.

## Worker Agent Errors
19. **Adding client-facing intake node to workers** — The queen owns intake. Workers should start with an autonomous processing node. Route worker review/approval through queen escalation instead of direct worker HITL.
20. **Putting `escalate` or `set_output` in NodeSpec `tools=[]`** — These are synthetic framework tools, auto-injected at runtime. Only list MCP tools from `list_agent_tools()`.
