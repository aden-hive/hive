---
name: hive-concepts
description: Core concepts for goal-driven agents - architecture, node types (event_loop, function), tool discovery, and workflow overview. Use when starting agent development or need to understand agent fundamentals.
license: Apache-2.0
metadata:
  author: hive
  version: "2.0"
  type: foundational
  part_of: hive
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

- `event_loop` — Multi-turn streaming loop with tool execution and judge-based evaluation. Works with or without tools.
- `function` — Deterministic Python operations. No LLM involved.

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

**STEP 1 / STEP 2 Prompt Pattern:** For client-facing nodes, structure the system prompt with two explicit phases:

```python
system_prompt="""\
**STEP 1 — Respond to the user (text only, NO tool calls):**
[Present information, ask questions, etc.]

**STEP 2 — After the user responds, call set_output:**
[Call set_output with the structured outputs]
"""
```

This prevents the LLM from calling `set_output` prematurely before the user has had a chance to respond.

### Node Design: Fewer, Richer Nodes

Prefer fewer nodes that do more work over many thin single-purpose nodes:

- **Bad**: 8 thin nodes (parse query → search → fetch → evaluate → synthesize → write → check → save)
- **Good**: 4 rich nodes (intake → research → review → report)

Why: Each node boundary requires serializing outputs and passing context. Fewer nodes means the LLM retains full context of its work within the node. A research node that searches, fetches, and analyzes keeps all the source material in its conversation history.

### nullable_output_keys for Cross-Edge Inputs

When a node receives inputs that only arrive on certain edges (e.g., `feedback` only comes from a review → research feedback loop, not from intake → research), mark those keys as `nullable_output_keys`:

```python
research_node = NodeSpec(
    id="research",
    input_keys=["research_brief", "feedback"],
    nullable_output_keys=["feedback"],  # Not present on first visit
    max_node_visits=3,
    ...
)
```

## Event Loop Architecture Concepts

### How EventLoopNode Works

An event loop node runs a multi-turn loop:
1. LLM receives system prompt + conversation history
2. LLM responds (text and/or tool calls)
3. Tool calls are executed, results added to conversation
4. Judge evaluates: ACCEPT (exit loop), RETRY (loop again), or ESCALATE
5. Repeat until judge ACCEPTs or max_iterations reached

### EventLoopNode Runtime

EventLoopNodes are **auto-created** by `GraphExecutor` at runtime. You do NOT need to manually register them. Both `GraphExecutor` (direct) and `AgentRuntime` / `create_agent_runtime()` handle event_loop nodes automatically.

```python
# Direct execution — executor auto-creates EventLoopNodes
from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime

runtime = Runtime(storage_path)
executor = GraphExecutor(
    runtime=runtime,
    llm=llm,
    tools=tools,
    tool_executor=tool_executor,
    storage_path=storage_path,
)
result = await executor.execute(graph=graph, goal=goal, input_data=input_data)

# TUI execution — AgentRuntime also works
from framework.runtime.agent_runtime import create_agent_runtime
runtime = create_agent_runtime(
    graph=graph, goal=goal, storage_path=storage_path,
    entry_points=[...], llm=llm, tools=tools, tool_executor=tool_executor,
)
```

### set_output

Nodes produce structured outputs by calling `set_output(key, value)` — a synthetic tool injected by the framework. When the LLM calls `set_output`, the value is stored in the output accumulator and made available to downstream nodes via shared memory.

`set_output` is NOT a real tool — it is excluded from `real_tool_results`. For client-facing nodes, this means a turn where the LLM only calls `set_output` (no other tools) is treated as a conversational boundary and will block for user input.

### JudgeProtocol

**The judge is the SOLE mechanism for acceptance decisions.** Do not add ad-hoc framework gating, output rollback, or premature rejection logic. If the LLM calls `set_output` too early, fix it with better prompts or a custom judge — not framework-level guards.

The judge controls when a node's loop exits:
- **Implicit judge** (default, no judge configured): ACCEPTs when the LLM finishes with no tool calls and all required output keys are set
- **SchemaJudge**: Validates outputs against a Pydantic model
- **Custom judges**: Implement `evaluate(context) -> JudgeVerdict`

### LoopConfig

Controls loop behavior:
- `max_iterations` (default 50) — prevents infinite loops
- `max_tool_calls_per_turn` (default 10) — limits tool calls per LLM response
- `tool_call_overflow_margin` (default 0.5) — wiggle room before discarding extra tool calls (50% means hard cutoff at 150% of limit)
- `stall_detection_threshold` (default 3) — detects repeated identical responses
- `max_history_tokens` (default 32000) — triggers conversation compaction

### Data Tools (Spillover Management)

When tool results exceed the context window, the framework automatically saves them to a spillover directory and truncates with a hint. Nodes that produce or consume large data should include the data tools:

- `save_data(filename, data)` — Write data to a file in the data directory
- `load_data(filename, offset=0, limit=50)` — Read data with line-based pagination
- `list_data_files()` — List available data files
- `serve_file_to_user(filename, label="")` — Get a clickable file:// URI for the user

Note: `data_dir` is a framework-injected context parameter — the LLM never sees or passes it. `GraphExecutor.execute()` sets it per-execution via `contextvars`, so data tools and spillover always share the same session-scoped directory.

These are real MCP tools (not synthetic). Add them to nodes that handle large tool results:

```python
research_node = NodeSpec(
    ...
    tools=["web_search", "web_scrape", "load_data", "save_data", "list_data_files"],
)
```

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

Use hive-concepts when:
- Starting a new agent project and need to understand fundamentals
- Need to understand agent architecture before building
- Want to validate tool availability before proceeding
- Learning about node types, edges, and graph execution

**Next Steps:**
- Ready to build? → Use `hive-create` skill
- Need patterns and examples? → Use `hive-patterns` skill

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

- **hive-create** - Step-by-step building process
- **hive-patterns** - Best practices: judges, feedback edges, fan-out, context management
- **hive** - Complete workflow orchestrator
- **hive-test** - Test and validate completed agents
