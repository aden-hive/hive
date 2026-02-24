# Common Mistakes When Building Hive Agents

## Critical Errors

1. **Using tools that don't exist** — Always verify tools are available in the hive-tools MCP server before assigning them to nodes. Never guess tool names.

2. **Wrong entry_points format** — MUST be `{"start": "first-node-id"}`. NOT a set, NOT `{node_id: [keys]}`.

3. **Wrong mcp_servers.json format** — Flat dict (no `"mcpServers"` wrapper). `cwd` must be `"../../tools"`. `command` must be `"uv"` with args `["run", "python", ...]`.

4. **Missing STEP 1/STEP 2 in client-facing prompts** — Without explicit phases, the LLM calls set_output before the user responds. Always use the pattern.

5. **Forgetting nullable_output_keys** — When a node receives inputs from multiple edges and some inputs only arrive on certain edges (e.g., feedback), mark those as nullable. Without this, the executor blocks waiting for a value that will never arrive.

6. **Creating dead-end nodes in forever-alive graphs** — Every node must have at least one outgoing edge. A node with no outgoing edges ends the execution, breaking the loop.

7. **Setting max_node_visits to a non-zero value in forever-alive agents** — The framework default is `max_node_visits=0` (unbounded). Setting it to any positive value (e.g., 1) means the node stops executing after that many visits, silently breaking the forever-alive loop. Only set `max_node_visits > 0` in one-shot agents with feedback loops that need bounded retries.

7. **Missing module-level exports in `__init__.py`** — The runner loads agents via `importlib.import_module(package_name)`, which imports `__init__.py`. It then reads `goal`, `nodes`, `edges`, `entry_node`, `entry_points`, `pause_nodes`, `terminal_nodes`, `conversation_mode`, `identity_prompt`, `loop_config` via `getattr()`. If ANY of these are missing from `__init__.py`, they default to `None` or `{}` — causing "must define goal, nodes, edges" errors or "node X is unreachable" validation failures. **ALL module-level variables from agent.py must be re-exported in `__init__.py`.**

## Value Errors

8. **Invalid `conversation_mode` value** — Only two valid values: `"continuous"` (recommended for interactive agents) or omit entirely (for isolated per-node conversations). Values like `"client_facing"`, `"interactive"`, `"adaptive"` do NOT exist and will cause runtime errors.

9. **Invalid `loop_config` keys** — Only three valid keys: `max_iterations` (int), `max_tool_calls_per_turn` (int), `max_history_tokens` (int). Keys like `"strategy"`, `"mode"`, `"timeout"` are NOT valid and are silently ignored or cause errors.

10. **Fabricating tools that don't exist** — Never guess tool names. Always verify via `discover_mcp_tools()`. Common hallucinations: `csv_read`, `csv_write`, `csv_append`, `file_upload`, `database_query`. If a required tool doesn't exist, redesign the agent to use tools that DO exist (e.g., `save_data`/`load_data` for data persistence).

## Design Errors

11. **Too many thin nodes** — Hard limit: **2-4 nodes** for most agents. Each node boundary serializes outputs to shared memory and loses all in-context information (tool results, intermediate reasoning, conversation history). A node with 0 tools that just does LLM reasoning is NOT a real node — merge it into its predecessor or successor.

**Merge when:**
- Node has NO tools — pure LLM reasoning belongs in the node that produces or consumes its data
- Node sets only 1 trivial output (e.g., `set_output("done", "true")`) — collapse into predecessor
- Multiple consecutive autonomous nodes with same/similar tools — combine into one
- A "report" or "summary" node that just presents analysis — merge into the client-facing node
- A "schedule" or "confirm" node that doesn't actually schedule anything — remove entirely

**Keep separate when:**
- Client-facing vs autonomous — different interaction models require separate nodes
- Fundamentally different tool sets (e.g., web search vs file I/O)
- Fan-out parallelism — parallel branches MUST be separate nodes

**Bad example** (7 nodes — WAY too many):
```
profile_setup → daily_intake → update_tracker → analyze_progress → generate_plan → schedule_reminders → report
```
`analyze_progress` has no tools. `schedule_reminders` just sets one boolean. `report` just presents analysis. `update_tracker` and `generate_plan` are sequential autonomous work.

**Good example** (3 nodes):
```
intake (client-facing) → process (autonomous: track + analyze + plan) → intake (loop back)
```
One client-facing node handles ALL user interaction (setup, logging, reports). One autonomous node handles ALL backend work (CSV update, analysis, plan generation) with tools and context preserved.

12. **Adding framework gating for LLM behavior** — Don't add output rollback, premature rejection, or interaction protocol injection. Fix with better prompts or custom judges.

13. **Not using continuous conversation mode** — Interactive agents should use `conversation_mode="continuous"`. Without it, each node starts with blank context.

14. **Adding terminal nodes by default** — ALL agents should use `terminal_nodes=[]` (forever-alive) unless the user explicitly requests a one-shot/batch agent. Forever-alive is the standard pattern. Every node must have at least one outgoing edge. Dead-end nodes break the loop.

15. **Calling set_output in same turn as tool calls** — Instruct the LLM to call set_output in a SEPARATE turn from real tool calls.

## File Template Errors

16. **Wrong import paths** — Use `from framework.graph import ...`, NOT `from core.framework.graph import ...`. The PYTHONPATH includes `core/`.

17. **Missing storage path** — Agent class must set `self._storage_path = Path.home() / ".hive" / "agents" / "agent_name"`.

18. **Missing mcp_servers.json** — Without this, the agent has no tools at runtime.

19. **Bare `python` command in mcp_servers.json** — Use `"command": "uv"` with args `["run", "python", ...]`.

## Testing Errors

20. **Using `runner.run()` on forever-alive agents** — `runner.run()` calls `trigger_and_wait()` which blocks until the graph reaches a terminal node. Forever-alive agents have `terminal_nodes=[]`, so **`runner.run()` hangs forever**. This is the #1 cause of stuck test suites.

**For forever-alive agents, write structural tests instead:**
- Validate graph structure (nodes, edges, entry points)
- Verify node specs (tools, prompts, client-facing flag)
- Check goal/constraints/success criteria definitions
- Test that `AgentRunner.load()` + `_setup()` succeeds (skip if no API key)

**What NOT to do:**
```python
# WRONG — hangs forever on forever-alive agents
result = await runner.run({"topic": "quantum computing"})
```

**Correct pattern for structure tests:**
```python
def test_research_has_web_tools(self):
    assert "web_search" in research_node.tools

def test_research_routes_back_to_interact(self):
    edges_to_interact = [e for e in edges if e.source == "research" and e.target == "interact"]
    assert edges_to_interact
```

21. **Stale tests after agent restructuring** — When you change an agent's node count or names (e.g., 4 nodes → 2 nodes), the tests MUST be updated too. Tests referencing old node names (e.g., `"review"`, `"report"`) will fail or hang. Always check that test assertions match the current `nodes/__init__.py`.

22. **Running full integration tests without API keys** — Structural tests (validate, import) work without keys. Full integration tests need `ANTHROPIC_API_KEY`. Use `pytest.skip()` in the runner fixture when `_setup()` fails due to missing credentials.

23. **Forgetting sys.path setup in conftest.py** — Tests need `exports/` and `core/` on sys.path.

24. **Not using auto_responder for client-facing nodes** — Tests with client-facing nodes hang without an auto-responder that injects input. But note: even WITH auto_responder, forever-alive agents still hang because the graph never terminates. Auto-responder only helps for agents with terminal nodes.
