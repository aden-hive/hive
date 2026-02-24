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
| `terminal_nodes` | no | `[]` | OK for forever-alive |
| `pause_nodes` | no | `[]` | OK |
| `conversation_mode` | no | not passed | Isolated mode (no context carryover) |
| `identity_prompt` | no | not passed | No agent-level identity |
| `loop_config` | no | `{}` | No iteration limits |
| `async_entry_points` | no | `[]` | No async triggers (timers, webhooks, events) |
| `runtime_config` | no | `None` | No webhook server |

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
| node_type | str | required | Always `"event_loop"` |
| input_keys | list[str] | required | Memory keys this node reads |
| output_keys | list[str] | required | Memory keys this node writes via set_output |
| system_prompt | str | "" | LLM instructions |
| tools | list[str] | [] | Tool names from MCP servers |
| client_facing | bool | False | If True, streams to user and blocks for input |
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

**Hard limit: 2-4 nodes for most agents.** Never exceed 5 unless the user
explicitly requests a complex multi-phase pipeline.

Each node boundary serializes outputs to shared memory and **destroys** all
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

**Typical agent structure (3 nodes):**
```
intake (client-facing) ←→ process (autonomous) ←→ review (client-facing)
```
Or for simpler agents, just 2 nodes:
```
interact (client-facing) → process (autonomous) → interact (loop)
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

### Forever-Alive Pattern
`terminal_nodes=[]` — every node has outgoing edges, graph loops until user exits.
Use `conversation_mode="continuous"` to preserve context across transitions.

### set_output
- Synthetic tool injected by framework
- Call separately from real tool calls (separate turn)
- `set_output("key", "value")` stores to shared memory

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
| **Forever-alive** | `[]` | **DEFAULT for all agents** |
| Linear | `["last-node"]` | Only if user explicitly requests one-shot/batch |

**Forever-alive is the default.** Always use `terminal_nodes=[]`.
The framework default for `max_node_visits` is 0 (unbounded), so
nodes work correctly in forever-alive loops without explicit override.
Only set `max_node_visits > 0` in one-shot agents with feedback loops.
Every node must have at least one outgoing edge — no dead ends. The
user exits by closing the TUI. Only use terminal nodes if the user
explicitly asks for a batch/one-shot agent that runs once and exits.

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
    "max_history_tokens": 32000,    # Triggers conversation compaction
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
- Fan-in node gets all outputs in shared memory

## Judge System

- **Implicit** (default): ACCEPTs when LLM finishes with no tool calls and all required outputs set
- **SchemaJudge**: Validates against Pydantic model
- **Custom**: Implement `evaluate(context) -> JudgeVerdict`

Judge is the SOLE acceptance mechanism — no ad-hoc framework gating.

## Async Entry Points (Webhooks, Timers, Events)

For agents that need to react to external events (incoming emails, scheduled
tasks, API calls), use `AsyncEntryPointSpec` and optionally `AgentRuntimeConfig`.

### Imports
```python
from framework.graph.edge import GraphSpec, AsyncEntryPointSpec
from framework.runtime.agent_runtime import AgentRuntime, AgentRuntimeConfig, create_agent_runtime
```
Note: `AsyncEntryPointSpec` is in `framework.graph.edge` (the graph/declarative layer).
`AgentRuntimeConfig` is in `framework.runtime.agent_runtime` (the runtime layer).

### AsyncEntryPointSpec Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | required | Unique identifier |
| name | str | required | Human-readable name |
| entry_node | str | required | Node ID to start execution from |
| trigger_type | str | `"manual"` | `webhook`, `api`, `timer`, `event`, `manual` |
| trigger_config | dict | `{}` | Trigger-specific config (see below) |
| isolation_level | str | `"shared"` | `isolated`, `shared`, `synchronized` |
| priority | int | `0` | Execution priority (higher = more priority) |
| max_concurrent | int | `10` | Max concurrent executions |

### Trigger Types

**timer** — Fires on a schedule. Two modes: cron expressions or fixed interval.

Cron (preferred for precise scheduling):
```python
AsyncEntryPointSpec(
    id="daily-digest",
    name="Daily Digest",
    entry_node="check-node",
    trigger_type="timer",
    trigger_config={"cron": "0 9 * * *"},  # daily at 9am
    isolation_level="shared",
    max_concurrent=1,
)
```
- `cron` (str) — standard cron expression (5 fields: min hour dom month dow)
- Examples: `"0 9 * * *"` (daily 9am), `"0 9 * * MON-FRI"` (weekdays 9am), `"*/30 * * * *"` (every 30 min)

Fixed interval (simpler, for polling-style tasks):
```python
AsyncEntryPointSpec(
    id="scheduled-check",
    name="Scheduled Check",
    entry_node="check-node",
    trigger_type="timer",
    trigger_config={"interval_minutes": 20, "run_immediately": False},
    isolation_level="shared",
    max_concurrent=1,
)
```
- `interval_minutes` (float) — how often to fire
- `run_immediately` (bool, default False) — fire once on startup

**event** — Subscribes to EventBus (e.g., webhook events):
```python
AsyncEntryPointSpec(
    id="email-event",
    name="Email Event Handler",
    entry_node="process-emails",
    trigger_type="event",
    trigger_config={"event_types": ["webhook_received"]},
    isolation_level="shared",
    max_concurrent=10,
)
```
- `event_types` (list[str]) — EventType values to subscribe to
- `filter_stream` (str, optional) — only receive from this stream
- `filter_node` (str, optional) — only receive from this node

**webhook** — HTTP endpoint (requires AgentRuntimeConfig):
The webhook server publishes `WEBHOOK_RECEIVED` events on the EventBus.
An `event` trigger type with `event_types: ["webhook_received"]` subscribes
to those events. The flow is:
```
HTTP POST /webhooks/gmail → WebhookServer → EventBus (WEBHOOK_RECEIVED)
  → event entry point → triggers graph execution from entry_node
```

**manual** — Triggered programmatically via `runtime.trigger()`.

### Isolation Levels

| Level | Meaning |
|-------|---------|
| `isolated` | Private state per execution |
| `shared` | Eventual consistency — async executions can read primary session memory |
| `synchronized` | Shared with write locks (use when ordering matters) |

For most async patterns, use `shared` — the async execution reads the primary
session's memory (e.g., user-configured rules) and runs its own workflow.

### AgentRuntimeConfig (for webhook servers)

```python
from framework.runtime.agent_runtime import AgentRuntimeConfig

runtime_config = AgentRuntimeConfig(
    webhook_host="127.0.0.1",
    webhook_port=8080,
    webhook_routes=[
        {
            "source_id": "gmail",
            "path": "/webhooks/gmail",
            "methods": ["POST"],
            "secret": None,  # Optional HMAC-SHA256 secret
        },
    ],
)
```
`runtime_config` is a module-level variable read by `AgentRunner.load()`.
The runner passes it to `create_agent_runtime()`. On `runtime.start()`,
if webhook_routes is non-empty, an embedded HTTP server starts.

### Session Sharing

Timer and event triggers automatically call `_get_primary_session_state()`
before execution. This finds the active user-facing session and provides
its memory to the async execution, filtered to only the async entry node's
`input_keys`. This means the async flow can read user-configured values
(like rules, preferences) without needing separate configuration.

### Module-Level Variables

Agents with async entry points must export two additional variables:
```python
# In agent.py:
async_entry_points = [AsyncEntryPointSpec(...), ...]
runtime_config = AgentRuntimeConfig(...)  # Only if using webhooks
```

Both must be re-exported from `__init__.py`:
```python
from .agent import (
    ..., async_entry_points, runtime_config,
)
```

### Reference Agent

See `exports/gmail_inbox_guardian/agent.py` for a complete example with:
- Primary client-facing intake node (user configures rules)
- Timer-based scheduled inbox checks (every 20 min)
- Webhook-triggered email event handling
- Shared isolation for memory access across streams

## Framework Capabilities

**Works well:** Multi-turn conversations, HITL review, tool orchestration, structured outputs, parallel execution, context management, error recovery, session persistence.

**Limitations:** LLM latency (2-10s/turn), context window limits (~128K), cost per run, rate limits, node boundaries lose context.

**Not designed for:** Sub-second responses, millions of items, real-time streaming, guaranteed determinism, offline/air-gapped.

## Tool Discovery

Do NOT rely on a static tool list — it will be outdated. Always use
`discover_mcp_tools()` to get the current tool catalog from the
hive-tools MCP server. This returns full schemas including parameter
names, types, and descriptions.

```
discover_mcp_tools()                          # default: hive-tools
discover_mcp_tools("exports/my_agent/mcp_servers.json")  # specific agent
```

Common tool categories (verify via discover_mcp_tools):
- **Web**: search, scrape, PDF
- **Data**: save/load/append/list data files, serve to user
- **File**: view, write, replace, diff, list, grep
- **Communication**: email, gmail, slack, telegram
- **CRM**: hubspot, apollo, calcom
- **GitHub**: stargazers, user profiles, repos
- **Vision**: image analysis
- **Time**: current time
