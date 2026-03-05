# Common Mistakes When Building Hive Agents

## Critical Errors

1. **Using tools that don't exist** — Always verify tools via `list_agent_tools()` before designing. Common hallucinations: `csv_read`, `csv_write`, `file_upload`, `database_query`, `bulk_fetch_emails`.

2. **Wrong mcp_servers.json format** — Flat dict (no `"mcpServers"` wrapper). `cwd` must be `"../../tools"`. `command` must be `"uv"` with args `["run", "python", ...]`.

3. **Missing STEP 1/STEP 2 in client-facing prompts** — Without explicit phases, the LLM calls set_output before the user responds. Always use the pattern.

4. **Forgetting nullable_output_keys** — When a node receives inputs from multiple edges and some inputs only arrive on certain edges (e.g., feedback), mark those as nullable. Without this, the executor blocks waiting for a value that will never arrive.

5. **Creating dead-end nodes in forever-alive graphs** — Every node must have at least one outgoing edge. Dead-end nodes break the loop.

6. **Setting max_node_visits > 0 in forever-alive agents** — The default is `0` (unbounded). Any positive value silently breaks the forever-alive loop. Only set > 0 in one-shot agents.

7. **Missing module-level exports in `__init__.py`** — The runner reads `goal`, `nodes`, `edges`, `entry_node`, `entry_points`, `terminal_nodes`, `conversation_mode`, `identity_prompt`, `loop_config` via `getattr()`. ALL module-level variables from agent.py must be re-exported in `__init__.py`.

## Value Errors

8. **Invalid `conversation_mode`** — Only `"continuous"` or omit entirely. Values like `"client_facing"`, `"interactive"`, `"adaptive"` do NOT exist.

9. **Invalid `loop_config` keys** — Only `max_iterations`, `max_tool_calls_per_turn`, `max_history_tokens`. Keys like `"strategy"`, `"mode"`, `"timeout"` are invalid.

10. **Fabricating tools** — Always verify via `list_agent_tools()` before designing and `validate_agent_tools()` after building.

## Design Errors

11. **Too many thin nodes** — Hard limit: 2-4 nodes. See "Fewer, Richer Nodes" in Framework Reference for decision framework.

12. **Adding framework gating for LLM behavior** — Don't add output rollback or premature rejection. Fix with better prompts or custom judges.

13. **Not using continuous conversation mode** — Interactive agents should use `conversation_mode="continuous"`. Without it, each node starts with blank context.

14. **Adding terminal nodes by default** — ALL agents should use `terminal_nodes=[]` (forever-alive) unless explicitly requested otherwise.

15. **Calling set_output in same turn as tool calls** — Call set_output in a SEPARATE turn.

## File Template Errors

16. **Wrong import paths** — Use `from framework.graph import ...`, NOT `from core.framework.graph import ...`.

17. **Missing storage path** — Agent class must set `self._storage_path = Path.home() / ".hive" / "agents" / "agent_name"`.

18. **Missing mcp_servers.json** — Without this, the agent has no tools at runtime.

19. **Bare `python` command** — Use `"command": "uv"` with args `["run", "python", ...]`.

## Testing Errors

20. **Using `runner.run()` on forever-alive agents** — `runner.run()` hangs forever because forever-alive agents have no terminal node. Write structural tests instead: validate graph structure, verify node specs, test `AgentRunner.load()` succeeds (no API key needed).

21. **Stale tests after restructuring** — When changing nodes/edges, update tests to match. Tests referencing old node names will fail.

22. **Running integration tests without API keys** — Use `pytest.skip()` when credentials are missing.

23. **Forgetting sys.path setup in conftest.py** — Tests need `exports/` and `core/` on sys.path.

## GCU Errors

24. **Manually wiring browser tools on event_loop nodes** — Use `node_type="gcu"` which auto-includes browser tools. Do NOT manually list browser tool names.

25. **Using GCU nodes as regular graph nodes** — GCU nodes are subagents only. They must ONLY appear in `sub_agents=["gcu-node-id"]` and be invoked via `delegate_to_sub_agent()`. Never connect via edges or use as entry/terminal nodes.

## Worker Agent Errors

26. **Adding client-facing intake node to workers** — The queen owns intake. Workers should start with an autonomous processing node. Client-facing nodes in workers are for mid-execution review/approval only.
