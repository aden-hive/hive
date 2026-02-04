---
name: building-agents-core
description: Core concepts for goal-driven agents - architecture, node types (event_loop, function), tool discovery, and workflow overview. Use when starting agent development or need to understand agent fundamentals.
license: Apache-2.0
metadata:
  author: hive
  version: "2.0"
  type: foundational
  part_of: building-agents
---

# Building Agents - Core Concepts

Foundational knowledge for building goal-driven agents as Python packages.

## Architecture: Python Services (Not JSON Configs)

Agents are built as Python packages:

```
exports/my_agent/
├── __init__.py          # Package exports
├── __main__.py          # CLI (run, info, validate, shell)
├── agent.py             # Graph construction (goal, edges, agent class)
├── nodes/__init__.py    # Node definitions (NodeSpec)
├── config.py            # Runtime config
└── README.md            # Documentation
```

**Key Principle: Agent is visible and editable during build**

- Files created immediately as components are approved
- User can watch files grow in their editor
- No session state - just direct file writes
- No "export" step - agent is ready when build completes

## Core Concepts

### Goal

Success criteria and constraints (written to agent.py)

```python
goal = Goal(
    id="research-goal",
    name="Technical Research Agent",
    description="Research technical topics thoroughly",
    success_criteria=[
        SuccessCriterion(
            id="completeness",
            description="Cover all aspects of topic",
            metric="coverage_score",
            target=">=0.9",
            weight=0.4,
        ),
        # 3-5 success criteria total
    ],
    constraints=[
        Constraint(
            id="accuracy",
            description="All information must be verified",
            constraint_type="hard",
            category="quality",
        ),
        # 1-5 constraints total
    ],
)
```

### Node

Unit of work (written to nodes/__init__.py)

**Node Types:**

- `event_loop` — **Recommended for all LLM-powered work.** Multi-turn streaming loop with tool execution and judge-based evaluation. Works with or without tools.
- `function` — Deterministic Python operations. No LLM involved.

> **Legacy Note:** `llm_generate` and `llm_tool_use` still function but are deprecated. Use `event_loop` instead, which handles both cases in a single multi-turn streaming loop.

```python
search_node = NodeSpec(
    id="search-web",
    name="Search Web",
    description="Search for information and extract results",
    node_type="event_loop",
    input_keys=["query"],
    output_keys=["search_results"],
    system_prompt="Search the web for: {query}. Use the web_search tool to find results, then call set_output to store them.",
    tools=["web_search"],
)
```

**NodeSpec Fields for Event Loop Nodes:**

| Field | Default | Description |
|-------|---------|-------------|
| `client_facing` | `False` | If True, streams output to user and blocks for input between turns |
| `nullable_output_keys` | `[]` | Output keys that may remain unset (for mutually exclusive outputs) |
| `max_node_visits` | `1` | Max times this node executes per run. Set >1 for feedback loop targets |

### Edge

Connection between nodes (written to agent.py)

**Edge Conditions:**

- `on_success` — Proceed if node succeeds (most common)
- `on_failure` — Handle errors
- `always` — Always proceed
- `conditional` — Based on expression evaluating node output

**Edge Priority:**

Priority controls evaluation order when multiple edges leave the same node. Higher priority edges are evaluated first. Use negative priority for feedback edges (edges that loop back to earlier nodes).

```python
# Forward edge (evaluated first)
EdgeSpec(
    id="review-to-campaign",
    source="review",
    target="campaign-builder",
    condition=EdgeCondition.CONDITIONAL,
    condition_expr="output.get('approved_contacts') is not None",
    priority=1,
)

# Feedback edge (evaluated after forward edges)
EdgeSpec(
    id="review-feedback",
    source="review",
    target="extractor",
    condition=EdgeCondition.CONDITIONAL,
    condition_expr="output.get('redo_extraction') is not None",
    priority=-1,
)
```

### Client-Facing Nodes

For multi-turn conversations with the user, set `client_facing=True` on a node. The node will:
- Stream its LLM output directly to the end user
- Block for user input between conversational turns
- Resume when new input is injected via `inject_event()`

```python
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Gather requirements from the user",
    node_type="event_loop",
    client_facing=True,
    input_keys=[],
    output_keys=["repo_url", "project_url"],
    system_prompt="You are the intake agent. Ask the user for the repo URL and project URL.",
)
```

> **Legacy Note:** The old `pause_nodes` / `entry_points` pattern still works but `client_facing=True` is preferred for new agents.

## Event Loop Architecture Concepts

### How EventLoopNode Works

An event loop node runs a multi-turn loop:
1. LLM receives system prompt + conversation history
2. LLM responds (text and/or tool calls)
3. Tool calls are executed, results added to conversation
4. Judge evaluates: ACCEPT (exit loop), RETRY (loop again), or ESCALATE
5. Repeat until judge ACCEPTs or max_iterations reached

### CRITICAL: EventLoopNode Runtime Requirements

EventLoopNodes are **not auto-created** by the graph executor. They must be explicitly instantiated and registered in a `node_registry` dict before execution.

**Required components:**
1. **`EventLoopNode` instances** — One per event_loop NodeSpec, registered in `node_registry`
2. **`Runtime` instance** — `GraphExecutor` calls `runtime.start_run()` internally. Passing `None` crashes the executor
3. **`GraphExecutor` (not `AgentRuntime`)** — `AgentRuntime`/`create_agent_runtime()` does NOT pass `node_registry` to the internal `GraphExecutor`, so all event_loop nodes fail with "not found in registry"

```python
from framework.graph.executor import GraphExecutor
from framework.graph.event_loop_node import EventLoopNode, LoopConfig
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime

# Build node_registry
event_bus = EventBus()
node_registry = {}
for node_spec in nodes:
    if node_spec.node_type == "event_loop":
        node_registry[node_spec.id] = EventLoopNode(
            event_bus=event_bus,
            config=LoopConfig(max_iterations=50, max_tool_calls_per_turn=15),
            tool_executor=tool_executor,
        )

# Create executor with Runtime and node_registry
runtime = Runtime(storage_path)
executor = GraphExecutor(
    runtime=runtime,
    llm=llm,
    tools=tools,
    tool_executor=tool_executor,
    node_registry=node_registry,
)
```

### set_output

Nodes produce structured outputs by calling `set_output(key, value)` — a synthetic tool injected by the framework. When the LLM calls `set_output`, the value is stored in the output accumulator and made available to downstream nodes via shared memory.

### JudgeProtocol

The judge controls when a node's loop exits:
- **Implicit judge** (default, no judge configured): ACCEPTs when the LLM finishes with no tool calls and all required output keys are set
- **SchemaJudge**: Validates outputs against a Pydantic model
- **Custom judges**: Implement `evaluate(context) -> JudgeVerdict`

### LoopConfig

Controls loop behavior:
- `max_iterations` (default 50) — prevents infinite loops
- `max_tool_calls_per_turn` (default 10) — limits tool calls per LLM response
- `stall_detection_threshold` (default 3) — detects repeated identical responses
- `max_history_tokens` (default 32000) — triggers conversation compaction

### Fan-Out / Fan-In

Multiple ON_SUCCESS edges from the same source create parallel execution. All branches run concurrently via `asyncio.gather()`. Parallel event_loop nodes must have disjoint `output_keys`.

### max_node_visits

Controls how many times a node can execute in one graph run. Default is 1. Set higher for nodes that are targets of feedback edges (review-reject loops). Set 0 for unlimited (guarded by max_steps).

## Tool Discovery & Validation

**CRITICAL:** Before adding a node with tools, you MUST verify the tools exist.

Tools are provided by MCP servers. Never assume a tool exists - always discover dynamically.

### Step 1: Register MCP Server (if not already done)

```python
mcp__agent-builder__add_mcp_server(
    name="tools",
    transport="stdio",
    command="python",
    args='["mcp_server.py", "--stdio"]',
    cwd="../tools"
)
```

### Step 2: Discover Available Tools

```python
# List all tools from all registered servers
mcp__agent-builder__list_mcp_tools()

# Or list tools from a specific server
mcp__agent-builder__list_mcp_tools(server_name="tools")
```

### Step 3: Validate Before Adding Nodes

Before writing a node with `tools=[...]`:

1. Call `list_mcp_tools()` to get available tools
2. Check each tool in your node exists in the response
3. If a tool doesn't exist:
   - **DO NOT proceed** with the node
   - Inform the user: "The tool 'X' is not available. Available tools are: ..."
   - Ask if they want to use an alternative or proceed without the tool

### Tool Validation Anti-Patterns

- **Never assume a tool exists** - always call `list_mcp_tools()` first
- **Never write a node with unverified tools** - validate before writing
- **Never silently drop tools** - if a tool doesn't exist, inform the user
- **Never guess tool names** - use exact names from discovery response

## Workflow Overview: Incremental File Construction

```
1. CREATE PACKAGE → mkdir + write skeletons
2. DEFINE GOAL → Write to agent.py + config.py
3. FOR EACH NODE:
   - Propose design (event_loop for LLM work, function for deterministic)
   - User approves
   - Write to nodes/__init__.py IMMEDIATELY
   - (Optional) Validate with test_node
4. CONNECT EDGES → Update agent.py
   - Use priority for feedback edges (negative priority)
   - (Optional) Validate with validate_graph
5. FINALIZE → Write agent class to agent.py
6. DONE - Agent ready at exports/my_agent/
```

**Files written immediately. MCP tools optional for validation/testing bookkeeping.**

## When to Use This Skill

Use building-agents-core when:
- Starting a new agent project and need to understand fundamentals
- Need to understand agent architecture before building
- Want to validate tool availability before proceeding
- Learning about node types, edges, and graph execution

**Next Steps:**
- Ready to build? → Use `building-agents-construction` skill
- Need patterns and examples? → Use `building-agents-patterns` skill

## MCP Tools for Validation

After writing files, optionally use MCP tools for validation:

**test_node** - Validate node configuration with mock inputs
```python
mcp__agent-builder__test_node(
    node_id="search-web",
    test_input='{"query": "test query"}',
    mock_llm_response='{"results": "mock output"}'
)
```

**validate_graph** - Check graph structure
```python
mcp__agent-builder__validate_graph()
# Returns: unreachable nodes, missing connections, event_loop validation, etc.
```

**configure_loop** - Set event loop parameters
```python
mcp__agent-builder__configure_loop(
    max_iterations=50,
    max_tool_calls_per_turn=10,
    stall_detection_threshold=3,
    max_history_tokens=32000
)
```

**Key Point:** Files are written FIRST. MCP tools are for validation only.

## Related Skills

- **building-agents-construction** - Step-by-step building process
- **building-agents-patterns** - Best practices: judges, feedback edges, fan-out, context management
- **agent-workflow** - Complete workflow orchestrator
- **testing-agent** - Test and validate completed agents
