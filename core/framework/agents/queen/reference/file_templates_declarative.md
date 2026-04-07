# Declarative Agent File Templates

Agents are defined as a single `agent.yaml` file. No Python code needed.
The runner loads this file directly -- no `agent.py`, `config.py`, or
`nodes/__init__.py` required.

## agent.yaml -- Complete Agent Definition

```yaml
name: my-agent
version: 1.0.0
description: What this agent does.

metadata:
  intro_message: Welcome! What would you like me to do?

# Template variables -- substituted into system_prompt and identity_prompt
# via {{variable_name}} syntax.  Use this for config values that appear
# in prompts (spreadsheet IDs, API endpoints, account names, etc.)
variables:
  spreadsheet_id: "1ZVxWDL..."
  sheet_name: "contacts"

goal:
  description: What this agent achieves.
  success_criteria:
    - "First success criterion"
    - "Second success criterion"
  constraints:
    - "Hard constraint the agent must respect"

identity_prompt: |
  You are a helpful agent.

conversation_mode: continuous   # always "continuous" for Hive agents

loop_config:
  max_iterations: 100
  max_tool_calls_per_turn: 30
  max_context_tokens: 32000

# MCP servers to connect (resolved by name from ~/.hive/mcp_registry/)
mcp_servers:
  - name: hive-tools
  - name: gcu-tools

nodes:
  # Node 1: Process (autonomous entry node)
  # The queen handles intake and passes structured input via
  # run_agent_with_input(task). NO client-facing intake node.
  - id: process
    name: Process
    description: Execute the task using available tools
    max_node_visits: 0   # 0 = unlimited (forever-alive agents)
    input_keys: [user_request, feedback]
    output_keys: [results]
    nullable_output_keys: [feedback]
    tools:
      policy: explicit
      allowed: [web_search, web_scrape, save_data, load_data, list_data_files]
    success_criteria: Results are complete and accurate.
    system_prompt: |
      You are a processing agent. Your task is in memory under "user_request".
      If "feedback" is present, this is a revision.

      Work in phases:
      1. Use tools to gather/process data
      2. Analyze results
      3. Call set_output in a SEPARATE turn:
         - set_output("results", "structured results")

  # Node 2: Handoff (autonomous)
  - id: handoff
    name: Handoff
    description: Prepare worker results for queen review
    max_node_visits: 0
    input_keys: [results, user_request]
    output_keys: [next_action, feedback, worker_summary]
    nullable_output_keys: [feedback, worker_summary]
    tools:
      policy: none   # handoff nodes don't need tools
    success_criteria: Results are packaged for queen decision-making.
    system_prompt: |
      Do NOT talk to the user directly. The queen is the only user interface.

      If blocked, call escalate(reason, context) then set:
      - set_output("next_action", "escalated")
      - set_output("feedback", "what help is needed")

      Otherwise summarize and set:
      - set_output("worker_summary", "short summary for queen")
      - set_output("next_action", "done") or "revise"
      - set_output("feedback", "what to revise") only when revising

edges:
  - from_node: process
    to_node: handoff
  # Feedback loop
  - from_node: handoff
    to_node: process
    condition: conditional
    condition_expr: "str(next_action).lower() == 'revise'"
    priority: 2
  # Escalation loop
  - from_node: handoff
    to_node: process
    condition: conditional
    condition_expr: "str(next_action).lower() == 'escalated'"
    priority: 3
  # Loop back for next task
  - from_node: handoff
    to_node: process
    condition: conditional
    condition_expr: "str(next_action).lower() == 'done'"

entry_node: process
terminal_nodes: []   # [] = forever-alive
```

## Key differences from Python templates

| Before (Python)                     | After (YAML)                           |
|-------------------------------------|----------------------------------------|
| `agent.py` (250 lines boilerplate)  | Not needed                             |
| `config.py` (dataclass + metadata)  | `variables:` + `metadata:` in YAML     |
| `nodes/__init__.py` (NodeSpec calls)| `nodes:` list in YAML                  |
| `__init__.py`, `__main__.py`        | Not needed                             |
| f-string config injection           | `{{variable_name}}` templates          |
| `mcp_servers.json` (separate file)  | `mcp_servers:` in YAML (or keep file)  |

## Node types

| Type         | Description                           | Tools                    |
|--------------|---------------------------------------|--------------------------|
| `event_loop` | LLM-driven orchestration (default)    | Explicit list or `none`  |
| `gcu`        | Browser automation via GCU tools      | `policy: all` (auto)     |

## Tool access policies

```yaml
# Explicit list (recommended for most nodes)
tools:
  policy: explicit
  allowed: [web_search, save_data]

# All tools from registry (for GCU browser nodes)
tools:
  policy: all

# No tools (for handoff/summary nodes)
tools:
  policy: none
```

## Edge conditions

| Condition     | When to use                                           |
|---------------|-------------------------------------------------------|
| `on_success`  | Default. Next node after current succeeds.            |
| `on_failure`  | Fallback path when current node fails.                |
| `always`      | Always traverse regardless of outcome.                |
| `conditional` | Evaluate `condition_expr` against shared memory keys. |
| `llm_decide`  | Let the LLM decide at runtime.                        |

## Template variables

Use `{{variable_name}}` in `system_prompt` and `identity_prompt`.
Variables are defined in the top-level `variables:` map.

```yaml
variables:
  spreadsheet_id: "1ZVxWDL..."
  api_endpoint: "https://api.example.com"

nodes:
  - id: start
    system_prompt: |
      Connect to spreadsheet: {{spreadsheet_id}}
      API endpoint: {{api_endpoint}}
```

## Entry points

Default is a single manual entry point. For timer/scheduled triggers:

```yaml
entry_points:
  - id: default
    trigger_type: manual
  - id: daily-check
    trigger_type: timer
    trigger_config:
      interval_minutes: 30
```

## mcp_servers.json -- Still Supported

The `mcp_servers.json` file is still loaded automatically if present alongside
`agent.yaml`.  You can also inline servers in the YAML:

```yaml
mcp_servers:
  - name: hive-tools
  - name: gcu-tools
```

Both approaches work. The JSON file takes precedence for backward compatibility.

## Migration from Python agents

Run the migration tool to convert existing agents:

```bash
uv run python -m framework.tools.migrate_agent exports/my_agent
```

This generates `agent.yaml` from the existing `agent.py` + `nodes/` + `config.py`.
The original files are left untouched. Once verified, you can delete the Python files.

## Files after migration

```
my_agent/
  agent.yaml           # The only required file
  mcp_servers.json     # Optional (can inline in YAML)
  flowchart.json       # Optional (auto-generated)
```
