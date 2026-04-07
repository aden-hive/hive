# Hive Agent Framework — Condensed Reference

## Architecture

Agents are Python packages in `exports/`:
```
exports/my_agent/
├── __init__.py          # MUST re-export ALL module-level vars from agent.py
├── __main__.py          # CLI (run, tui, info, validate, shell)
├── agent.py             # Graph construction (goal, edges, agent class)
├── config.py            # Runtime config
├── nodes/__init__.py    # Node definitions (NodeSpec)
├── mcp_servers.json     # MCP tool server config
└── tests/               # pytest tests
```

## Agent Loading Contract

`AgentRunner.load()` imports the package (`__init__.py`) and reads these
module-level variables via `getattr()`:

| Variable | Required | Default if missing | Consequence |
|----------|----------|--------------------|-------------|
| `goal` | YES | `None` | **FATAL** — "must define goal, nodes, edges" |
| `nodes` | YES | `None` | **FATAL** — same error |
| `edges` | YES | `None` | **FATAL** — same error |
| `entry_node` | no | `nodes[0].id` | Probably wrong node |
| `entry_points` | no | `{}` | **Nodes unreachable** — validation fails |
| `terminal_nodes` | **YES** | `[]` | **FATAL** — graph must have at least one terminal node |
| `pause_nodes` | no | `[]` | OK |
| `conversation_mode` | no | not passed | Isolated mode (no context carryover) |
| `identity_prompt` | no | not passed | No agent-level identity |
| `loop_config` | no | `{}` | No iteration limits |
| `triggers.json` (file) | no | not present | No triggers (timers, webhooks) |

**CRITICAL:** `__init__.py` MUST import and re-export ALL of these from
`agent.py`. Missing exports silently fall back to defaults, causing
hard-to-debug failures.

**Why `default_agent.validate()` is NOT sufficient:**
`validate()` checks the agent CLASS's internal graph (self.nodes, self.edges).
These are always correct because the constructor references agent.py's module
vars directly. But `AgentRunner.load()` reads from the PACKAGE (`__init__.py`),
not the class. So `validate()` passes while `AgentRunner.load()` fails.
Always test with `AgentRunner.load("exports/{name}")` — this is the same
code path the TUI and `hive run` use.

## Goal

Defines success criteria and constraints:
```python
goal = Goal(
    id="kebab-case-id",
    name="Display Name",
    description="What the agent does",
    success_criteria=[
        SuccessCriterion(id="sc-id", description="...", metric="...", target="...", weight=0.25),
    ],
    constraints=[
        Constraint(id="c-id", description="...", constraint_type="hard", category="quality"),
    ],
)
```
- 3-5 success criteria, weights sum to 1.0
- 1-5 constraints (hard/soft, categories: quality, accuracy, interaction, functional)

## NodeSpec Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | required | kebab-case identifier |
| name | str | required | Display name |
| description | str | required | What the node does |
| node_type | str | required | `"event_loop"` or `"gcu"` (browser automation — see GCU Guide appendix) |
| input_keys | list[str] | required | Memory keys this node reads |
| output_keys | list[str] | required | Memory keys this node writes via set_output |
| system_prompt | str | "" | LLM instructions |
| tools | list[str] | [] | Tool names from MCP servers |
| client_facing | bool | False | Deprecated compatibility field. Queen interactivity is implicit; workers should escalate instead |
| nullable_output_keys | list[str] | [] | Keys that may remain unset |
| max_node_visits | int | 0 | 0=unlimited (default); >1 for one-shot feedback loops |
| max_retries | int | 3 | Retries on failure |
| success_criteria | str | "" | Natural language for judge evaluation |

## EdgeSpec Fields

| Field | Type | Description |
|-------|------|-------------|
| id | str | kebab-case identifier |
| source | str | Source node ID |
| target | str | Target node ID |
| condition | EdgeCondition | ON_SUCCESS, ON_FAILURE, ALWAYS, CONDITIONAL |
| condition_expr | str | Python expression evaluated against memory (for CONDITIONAL) |
| priority | int | Positive=forward (evaluated first), negative=feedback (loop-back) |

## Key Patterns

### STEP 1/STEP 2 (Client-Facing Nodes)
```
**STEP 1 — Respond to the user (text only, NO tool calls):**
[Present information, ask questions]

**STEP 2 — After the user responds, call set_output:**
- set_output("key", "value based on user response")
```
This prevents premature set_output before user interaction.

### Fewer, Richer Nodes (CRITICAL)

**Hard limit: 3-6 nodes for most agents.** Never exceed 6 unless the user
explicitly requests a complex multi-phase pipeline.

Each node boundary serializes outputs to the shared buffer and **destroys** all
in-context information: tool call results, intermediate reasoning, conversation
history. A research node that searches, fetches, and analyzes in ONE node keeps
all source material in its conversation context. Split across 3 nodes, each
downstream node only sees the serialized summary string.

**Decision framework — merge unless ANY of these apply:**
1. **Client-facing boundary** — Autonomous and client-facing work MUST be
   separate nodes (different interaction models)
2. **Disjoint tool sets** — If tools are fundamentally different (e.g., web
   search vs database), separate nodes make sense
3. **Parallel execution** — Fan-out branches must be separate nodes

**Red flags that you have too many nodes:**
- A node with 0 tools (pure LLM reasoning) → merge into predecessor/successor
- A node that sets only 1 trivial output → collapse into predecessor
- Multiple consecutive autonomous nodes → combine into one rich node
- A "report" node that presents analysis → merge into the client-facing node
- A "confirm" or "schedule" node that doesn't call any external service → remove

**Typical agent structure (2 nodes):**
```
process (autonomous) ←→ review (queen-mediated)
```
The queen owns intake — she gathers requirements from the user, then
passes structured input via `run_agent_with_input(task)`. When building
the agent, design the entry node's `input_keys` to match what the queen
will provide at run time. Worker agents should NOT have a client-facing
intake node. Mid-execution review/approval should happen through queen
escalation rather than direct worker HITL.

For simpler agents, just 1 autonomous node:
```
process (autonomous) — loops back to itself
```

### nullable_output_keys
For inputs that only arrive on certain edges:
```python
research_node = NodeSpec(
    input_keys=["brief", "feedback"],
    nullable_output_keys=["feedback"],  # Only present on feedback edge
    max_node_visits=3,
)
```

### Mutually Exclusive Outputs
For routing decisions:
```python
review_node = NodeSpec(
    output_keys=["approved", "feedback"],
    nullable_output_keys=["approved", "feedback"],  # Node sets one or the other
)
```

### Continuous Loop Pattern
Mark the primary event_loop node as terminal: `terminal_nodes=["process"]`.
The node has `output_keys` and can complete when the agent finishes its work.
Use `conversation_mode="continuous"` to preserve context across transitions.

### set_output
- Synthetic tool injected by framework
- Call separately from real tool calls (separate turn)
- `set_output("key", "value")` stores to the shared buffer

## Edge Conditions

| Condition | When |
|-----------|------|
| ON_SUCCESS | Node completed successfully |
| ON_FAILURE | Node failed |
| ALWAYS | Unconditional |
| CONDITIONAL | condition_expr evaluates to True against memory |

condition_expr examples:
- `"needs_more_research == True"`
- `"str(next_action).lower() == 'new_agent'"`
- `"feedback is not None"`

## Graph Lifecycle

| Pattern | terminal_nodes | When |
|---------|---------------|------|
| **Continuous loop** | `["node-with-output-keys"]` | **DEFAULT for all agents** |
| Linear | `["last-node"]` | One-shot/batch agents |

**Every graph must have at least one terminal node.** Terminal nodes
define where execution ends. For interactive agents that loop continuously,
mark the primary event_loop node as terminal (it has `output_keys` and can
complete at any point). The framework default for `max_node_visits` is 0
(unbounded), so nodes work correctly in continuous loops without explicit
override. Only set `max_node_visits > 0` in one-shot agents with feedback loops.
Every node must have at least one outgoing edge — no dead ends.

## Continuous Conversation Mode

`conversation_mode` has ONLY two valid states:
- `"continuous"` — recommended for interactive agents
- Omit entirely — isolated per-node conversations (each node starts fresh)

**INVALID values** (do NOT use): `"client_facing"`, `"interactive"`,
`"adaptive"`, `"shared"`. These do not exist in the framework.

When `conversation_mode="continuous"`:
- Same conversation thread carries across node transitions
- Layered system prompts: identity (agent-level) + narrative + focus (per-node)
- Transition markers inserted at boundaries
- Compaction happens opportunistically at phase transitions

## loop_config

Only three valid keys:
```python
loop_config = {
    "max_iterations": 100,          # Max LLM turns per node visit
    "max_tool_calls_per_turn": 20,  # Max tool calls per LLM response
    "max_context_tokens": 32000,    # Triggers conversation compaction
}
```
**INVALID keys** (do NOT use): `"strategy"`, `"mode"`, `"timeout"`,
`"temperature"`. These are silently ignored or cause errors.

## Data Tools (Spillover)

For large data that exceeds context:
- `save_data(filename, data)` — Write to session data dir
- `load_data(filename, offset, limit)` — Read with pagination
- `list_data_files()` — List files
- `serve_file_to_user(filename, label)` — Clickable file:// URI

`data_dir` is auto-injected by framework — LLM never sees it.

## Fan-Out / Fan-In

Multiple ON_SUCCESS edges from same source → parallel execution via asyncio.gather().
- Parallel nodes must have disjoint output_keys
- Only one branch may have client_facing nodes
- Fan-in node gets all outputs in the shared buffer

## Judge System

- **Implicit** (default): ACCEPTs when LLM finishes with no tool calls and all required outputs set
- **SchemaJudge**: Validates against Pydantic model
- **Custom**: Implement `evaluate(context) -> JudgeVerdict`

Judge is the SOLE acceptance mechanism — no ad-hoc framework gating.

## Triggers (Timers, Webhooks)

For agents that react to external events, create a `triggers.json` file
in the agent's export directory:

```json
[
  {
    "id": "daily-check",
    "name": "Daily Check",
    "trigger_type": "timer",
    "trigger_config": {"cron": "0 9 * * *"},
    "task": "Run the daily check process"
  }
]
```

### Key Fields
- `trigger_type`: `"timer"` or `"webhook"`
- `trigger_config`: `{"cron": "0 9 * * *"}` or `{"interval_minutes": 20}`
- `task`: describes what the worker should do when the trigger fires
- Triggers can also be created/removed at runtime via `set_trigger` / `remove_trigger` queen tools

## Tool Discovery

Do NOT rely on a static tool list — it will be outdated. Always call
`list_agent_tools()` with NO arguments first to see ALL available tools.
Only use `group=` or `output_schema=` as follow-up calls after seeing the
full list.

```
list_agent_tools()                            # ALWAYS call this first
list_agent_tools(group="gmail", output_schema="full")  # then drill into a category
list_agent_tools("exports/my_agent/mcp_servers.json")  # specific agent's tools
```

After building, run `validate_agent_package("{name}")` to check everything at once.

Common tool categories (verify via list_agent_tools):
- **Web**: search, scrape, PDF
- **Data**: save/load/append/list data files, serve to user
- **File**: view, write, replace, diff, list, grep
- **Communication**: email, gmail, slack, telegram
- **CRM**: hubspot, apollo, calcom
- **GitHub**: stargazers, user profiles, repos
- **Vision**: image analysis
- **Time**: current time
