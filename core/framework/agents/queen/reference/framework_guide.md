# Hive Agent Framework -- Condensed Reference

## Architecture

Agents are declarative JSON configs in `exports/`:
```
exports/my_agent/
  agent.json          # The entire agent definition
  mcp_servers.json    # MCP tool server config (optional, prefer registry refs)
```

No Python files. No `__init__.py`, `__main__.py`, `config.py`, or `nodes/`.

## Agent Loading

`AgentLoader.load()` reads `agent.json` and builds the execution graph.
If `agent.py` exists (legacy), it's loaded as a Python module instead.

## agent.json Schema

```json
{
  "name": "my-agent",
  "version": "1.0.0",
  "description": "What this agent does",
  "goal": {
    "description": "What to achieve",
    "success_criteria": ["criterion 1", "criterion 2"],
    "constraints": ["constraint 1"]
  },
  "identity_prompt": "You are a helpful agent.",
  "conversation_mode": "continuous",
  "loop_config": {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 30,
    "max_context_tokens": 32000
  },
  "mcp_servers": [
    {"name": "hive-tools"},
    {"name": "gcu-tools"}
  ],
  "variables": {
    "spreadsheet_id": "1ZVx..."
  },
  "nodes": [...],
  "edges": [...],
  "entry_node": "process",
  "terminal_nodes": []
}
```

## Template Variables

Use `{{variable_name}}` in `system_prompt` and `identity_prompt`. Variables
are defined in the top-level `variables` object:

```json
{
  "variables": {"sheet_id": "1ZVx..."},
  "nodes": [{
    "id": "start",
    "system_prompt": "Use sheet: {{sheet_id}}"
  }]
}
```

## Node Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | required | kebab-case identifier |
| name | str | id | Display name |
| description | str | required | What the node does |
| node_type | str | "event_loop" | `"event_loop"` |
| input_keys | list | [] | Memory keys this node reads |
| output_keys | list | [] | Memory keys this node writes via set_output |
| system_prompt | str | "" | LLM instructions |
| tools | object | {} | Tool access policy (see below) |
| nullable_output_keys | list | [] | Keys that may remain unset |
| max_node_visits | int | 1 | 0=unlimited (for forever-alive agents) |
| success_criteria | str | "" | Natural language for judge evaluation |
| client_facing | bool | false | Whether output is shown to user |

## Tool Access Policies

Each node declares its tools via a policy object:

```json
{"tools": {"policy": "explicit", "allowed": ["web_search", "save_data"]}}
{"tools": {"policy": "all"}}
{"tools": {"policy": "none"}}
```

- `explicit` (default): only named tools. Empty `allowed` = zero tools.
- `all`: all tools from registry (e.g. for browser automation nodes).
- `none`: no tools (for handoff/summary nodes).

## Edge Fields

| Field | Type | Description |
|-------|------|-------------|
| from_node | str | Source node ID |
| to_node | str | Target node ID |
| condition | str | `on_success`, `on_failure`, `always`, `conditional` |
| condition_expr | str | Python expression for conditional routing |
| priority | int | Higher = evaluated first |

condition_expr examples:
- `"needs_more_research == True"`
- `"str(next_action).lower() == 'revise'"`

## Key Patterns

### Fewer, Richer Nodes (CRITICAL)

**Hard limit: 3-6 nodes for most agents.** Each node boundary serializes
outputs and destroys in-context information. Merge unless:
1. Client-facing boundary (different interaction models)
2. Disjoint tool sets
3. Parallel execution (fan-out branches)

**Typical structure (2 nodes):**
```
process (autonomous) <-> review (queen-mediated)
```

The queen owns intake. Worker agents should NOT have a client-facing intake
node. Mid-execution review should happen through queen escalation.

### set_output
- Synthetic tool injected by framework
- Call separately from real tool calls (separate turn)
- `set_output("key", "value")` stores to the shared buffer

### Graph Lifecycle

| Pattern | terminal_nodes | When |
|---------|---------------|------|
| Continuous loop | `["node-with-output-keys"]` | DEFAULT for all agents |
| Linear | `["last-node"]` | One-shot/batch agents |

Every graph must have at least one terminal node.

### Continuous Conversation Mode

`conversation_mode` has ONLY two valid states:
- `"continuous"` -- recommended (context carries across node transitions)
- Omit entirely -- isolated per-node conversations

**INVALID values:** `"client_facing"`, `"interactive"`, `"shared"`.

## loop_config

Only three valid keys:
```json
{
  "max_iterations": 100,
  "max_tool_calls_per_turn": 20,
  "max_context_tokens": 32000
}
```

## Data Tools (Spillover)

For large data that exceeds context:
- `save_data(filename, data)` -- write to session data dir
- `load_data(filename, offset, limit)` -- read with pagination
- `list_data_files()` -- list files
- `serve_file_to_user(filename, label)` -- clickable file URI

`data_dir` is auto-injected by framework.

## Fan-Out / Fan-In

Multiple `on_success` edges from same source = parallel execution.
Parallel nodes must have disjoint output_keys.

## Judge System

- **Implicit** (default): ACCEPTs when LLM finishes with no tool calls and all required outputs set
- **SchemaJudge**: Validates against Pydantic model

## Tool Discovery

Always call `list_agent_tools()` first to see available tools.
Do NOT rely on a static tool list.

```
list_agent_tools()                                      # full summary
list_agent_tools(group="gmail", output_schema="full")   # drill into category
```

After building, run `validate_agent_package("{name}")` to check everything.
