---
name: building-agents-core
description: Core concepts for goal-driven agents - architecture, node types, tool discovery, and workflow overview. Use when starting agent development or need to understand agent fundamentals.
license: Apache-2.0
metadata:
  author: hive
  version: "1.0"
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

- ✅ Files created immediately as components are approved
- ✅ User can watch files grow in their editor
- ✅ No session state - just direct file writes
- ✅ No "export" step - agent is ready when build completes

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

- `llm_generate` - Text generation, parsing
- `llm_tool_use` - Actions requiring tools
- `router` - Conditional branching
- `function` - Deterministic operations

```python
search_node = NodeSpec(
    id="search-web",
    name="Search Web",
    description="Search for information online",
    node_type="llm_tool_use",
    input_keys=["query"],
    output_keys=["search_results"],
    system_prompt="Search the web for: {query}",
    tools=["web_search"],
    max_retries=3,
)
```

### Edge

Connection between nodes (written to agent.py)

**Edge Conditions:**

- `on_success` - Proceed if node succeeds
- `on_failure` - Handle errors
- `always` - Always proceed
- `conditional` - Based on expression

```python
EdgeSpec(
    id="search-to-analyze",
    source="search-web",
    target="analyze-results",
    condition=EdgeCondition.ON_SUCCESS,
    priority=1,
)
```

### Pause/Resume

Multi-turn conversations

- **Pause nodes** - Stop execution, wait for user input
- **Resume entry points** - Continue from pause with user's response

```python
# Example pause/resume configuration
pause_nodes = ["request-clarification"]
entry_points = {
    "start": "analyze-request",
    "request-clarification_resume": "process-clarification"
}
```

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

This returns available tools with their descriptions and parameters:

```json
{
  "success": true,
  "tools_by_server": {
    "tools": [
      {
        "name": "web_search",
        "description": "Search the web...",
        "parameters": ["query"]
      },
      {
        "name": "web_scrape",
        "description": "Scrape a URL...",
        "parameters": ["url"]
      }
    ]
  },
  "total_tools": 14
}
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

❌ **Never assume a tool exists** - always call `list_mcp_tools()` first
❌ **Never write a node with unverified tools** - validate before writing
❌ **Never silently drop tools** - if a tool doesn't exist, inform the user
❌ **Never guess tool names** - use exact names from discovery response

### Example Validation Flow

```python
# 1. User requests: "Add a node that searches the web"
# 2. Discover available tools
tools_response = mcp__agent-builder__list_mcp_tools()

# 3. Check if web_search exists
available = [t["name"] for tools in tools_response["tools_by_server"].values() for t in tools]
if "web_search" not in available:
    # Inform user and ask how to proceed
    print("❌ 'web_search' not available. Available tools:", available)
else:
    # Proceed with node creation
    # ...
```

## Workflow Overview: Incremental File Construction

```
1. CREATE PACKAGE → mkdir + write skeletons
2. DEFINE GOAL → Write to agent.py + config.py
3. FOR EACH NODE:
   - Propose design
   - User approves
   - Write to nodes/__init__.py IMMEDIATELY ← FILE WRITTEN
   - (Optional) Validate with test_node ← MCP VALIDATION
   - User can open file and see it
4. CONNECT EDGES → Update agent.py ← FILE WRITTEN
   - (Optional) Validate with validate_graph ← MCP VALIDATION
5. FINALIZE → Write agent class to agent.py ← FILE WRITTEN
6. DONE - Agent ready at exports/my_agent/
```

**Files written immediately. MCP tools optional for validation/testing bookkeeping.**

### The Key Difference

**OLD (Bad):**

```
MCP add_node → Session State → MCP add_node → Session State → ...
                                                                ↓
                                                     MCP export_graph
                                                                ↓
                                                       Files appear
```

**NEW (Good):**

```
Write node to file → (Optional: MCP test_node) → Write node to file → ...
       ↓                                               ↓
  File visible                                    File visible
  immediately                                     immediately
```

**Bottom line:** Use Write/Edit for construction, MCP for validation if needed.

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
# Returns: unreachable nodes, missing connections, etc.
```

**create_session** - Track session state for bookkeeping
```python
mcp__agent-builder__create_session(session_name="my-build")
```

**Key Point:** Files are written FIRST. MCP tools are for validation only.

## Related Skills

- **building-agents-construction** - Step-by-step building process
- **building-agents-patterns** - Best practices and examples
- **agent-workflow** - Complete workflow orchestrator
- **testing-agent** - Test and validate completed agents
