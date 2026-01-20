---
name: building-agents
description: Build goal-driven agents with nodes, edges, and validation. Use when asked to create an agent, design a workflow, or build automation that requires multiple steps with LLM reasoning.
---

# Building Agents

Build goal-driven agents that use LLM reasoning to accomplish tasks.

## Quick Start

1. Define the goal (what success looks like)
2. Add nodes (units of work)
3. Connect with edges (flow between nodes)
4. Validate and test

## Core Concepts

**Goal**: The source of truth. Defines success criteria and constraints.

**Node**: A unit of work. Types:
- `llm_generate` - Text generation, parsing
- `llm_tool_use` - Actions requiring tools
- `router` - Conditional branching
- `function` - Deterministic operations

**Edge**: Connection between nodes with conditions:
- `on_success` - Proceed if node succeeds
- `on_failure` - Handle errors
- `always` - Always proceed
- `conditional` - Based on expression

**Session Architecture**: Agents are stateful services that:
- Maintain execution state across invocations
- Pause at HITL nodes and resume with new input
- Accept inputs through multiple entry points
- Persist state until explicitly cleared

## Workflow (HITL Required)

**CRITICAL**: Each step requires human approval before proceeding.
**CRITICAL**: Run tests during approval so humans can see actual behavior.
**CRITICAL**: Use structured questions (AskUserQuestion) with fallback to text mode.

### Approval Strategy

**Always try structured questions first**, with graceful fallback:

1. **Attempt**: Call AskUserQuestion with clickable options
2. **Catch**: If tool fails/rejected, fall back to text prompt
3. **Parse**: Accept text input like "approve", "reject", "pause"

This ensures the workflow works in all environments (VSCode extension, CLI, web).

**Practical Example**:
```python
# 1. Call MCP tool to create goal
result = set_goal(
    goal_id="text-parser",
    name="Text Parser",
    description="Parse text into JSON",
    success_criteria='[...]',
    constraints='[...]'
)

# 2. Parse result
import json
data = json.loads(result)

# 3. MCP tool returns approval_required=True with approval_question
# Claude sees this and calls AskUserQuestion

# 4. Present component
print(f"**GOAL: {data['goal']['name']}**")
print(f"Validation: ✅ PASS")

# 5. Call AskUserQuestion with the approval_question data
answer = AskUserQuestion(
    questions=[{
        "question": data["approval_question"]["question"],
        "header": data["approval_question"]["header"],
        "options": data["approval_question"]["options"],
        "multiSelect": False
    }]
)

# If widget supported → User sees clickable buttons:
┌─────────────────────────────────┐
│ Do you approve this goal?       │
│ ○ ✓ Approve (Recommended)       │
│ ○ ✗ Reject & Modify             │
│ ○ ⏸ Pause & Review              │
└─────────────────────────────────┘

# If widget NOT supported → Falls back to text:
→ Do you approve this goal definition?
Options: approve | reject | pause
> approve  ← User types this
```

### Build Loop

```
For each component (goal, node, edge):
1. PROPOSE → Show the component to the human
2. VALIDATE → Run validation, show errors/warnings
3. TEST → Run the component with sample inputs to show behavior
4. ASK APPROVAL → Use AskUserQuestion with clickable options (NOT free text)
5. Only proceed after approval
```

**CRITICAL**: Step 4 MUST use AskUserQuestion tool with structured options. Never ask "Do you approve?" as free text.

### Checklist (ask approval at each ✓)

**NOTE**: Every "ASK APPROVAL" means use AskUserQuestion with clickable options.

```
Agent Build Progress:
- [ ] Define goal with success criteria → ASK APPROVAL (clickable: Approve/Reject/Pause) ✓
- [ ] Define goal constraints → ASK APPROVAL (clickable: Approve/Reject/Pause) ✓
- [ ] Add entry node → TEST NODE → ASK APPROVAL (clickable: Approve/Reject/Pause) ✓
- [ ] Add each processing node → TEST NODE → ASK APPROVAL (clickable: Approve/Reject/Pause) ✓
- [ ] Add pause nodes (if HITL needed) → TEST NODE → ASK APPROVAL (clickable: Approve/Reject/Pause) ✓
- [ ] Add resume entry points (for pause nodes) → ASK APPROVAL (clickable: Approve/Reject/Pause) ✓
- [ ] Add terminal node(s) → TEST NODE → ASK APPROVAL (clickable: Approve/Reject/Pause) ✓
- [ ] Connect nodes with edges → ASK APPROVAL (clickable: Approve/Reject/Pause) ✓
- [ ] Configure entry_points and pause_nodes → ASK APPROVAL (clickable: Approve/Reject/Pause) ✓
- [ ] Validate full graph → TEST GRAPH → SHOW RESULTS
- [ ] Final approval → ASK APPROVAL (clickable: Approve & Export/Reject/Pause) ✓
- [ ] Export to exports/{agent-name}/
```

### Testing During Approval

**For each node**, use `test_node` with sample inputs:
```
test_node(
    node_id="my-node",
    test_input='{"key": "sample value"}',
)
```

Show the human:
- What inputs the node will read
- What the LLM prompt looks like
- What tools are available
- What outputs will be written

**Before final approval**, use `test_graph` to simulate full execution:
```
test_graph(
    test_input='{"initial": "data"}',
    dry_run=true,
)
```

Show the human:
- The complete execution path
- Each node that will execute
- The data flow between nodes

### Approval Format

After each component, **TRY to use AskUserQuestion with structured options** (fallback to text if unavailable):

**CRITICAL**: Attempt structured questions first, fall back to text mode gracefully if the environment doesn't support it.

```python
# Try structured approval first
try:
    response = AskUserQuestion(
        questions=[{
            "question": "Do you approve this [goal/node/edge]?",
            "header": "Approve",
            "options": [
                {
                    "label": "✓ Approve (Recommended)",
                    "description": "Component looks good, proceed to next step"
                },
                {
                    "label": "✗ Reject & Modify",
                    "description": "Need to make changes before proceeding"
                },
                {
                    "label": "⏸ Pause & Review",
                    "description": "I need more time to review this"
                }
            ],
            "multiSelect": false
        }]
    )
except:
    # Fallback to text mode if widget not supported
    # Ask: "Do you approve? Type: approve | reject | pause"
    pass
```

**Before asking for approval**, present the component details:
```
**[COMPONENT TYPE]: [NAME]**

[Show details of what was created]

Validation: [PASS/FAIL]
- Errors: [list]
- Warnings: [list]

Test Results:
[Show test_node or test_graph output]
```

**Then ask for approval** using structured questions (or text fallback).

**DO NOT proceed without explicit human approval.**

### Approval Helper Pattern

**IMPORTANT**: MCP tools now return `approval_required: true` flag with approval questions.

After calling any MCP tool (`set_goal`, `add_node`, `add_edge`), check the response:

```python
# Call MCP tool
result = set_goal(...)
result_data = json.loads(result)

# Check if approval is required
if result_data.get("approval_required"):
    approval_q = result_data["approval_question"]

    # Present component details first
    print(f"**{approval_q['component_type'].upper()}: {approval_q['component_name']}**")
    print(f"\nValidation: {'✅ PASS' if result_data['valid'] else '❌ FAIL'}")
    if result_data.get('errors'):
        print(f"Errors: {result_data['errors']}")
    if result_data.get('warnings'):
        print(f"Warnings: {result_data['warnings']}")

    # Try structured question first
    try:
        answer = AskUserQuestion(
            questions=[{
                "question": approval_q["question"],
                "header": approval_q["header"],
                "options": approval_q["options"],
                "multiSelect": False
            }]
        )
        # Parse answer - look for "Approve" in the response
        response_text = str(answer.values())
        if "Approve" in response_text and "Reject" not in response_text:
            # Approved - continue
            pass
        elif "Reject" in response_text:
            # Rejected - ask what to modify
            print("What would you like to modify?")
            # Handle modifications...
        else:
            # Paused - stop here
            print("Build paused. Resume when ready.")
            return

    except:
        # Fallback: text mode
        print(f"\n→ {approval_q['question']}")
        print("Options: approve | reject | pause")
        user_input = input().strip().lower()

        if user_input != "approve":
            if user_input == "reject":
                print("What would you like to modify?")
            else:
                print("Build paused.")
            return
```

Use this pattern after EVERY MCP tool call that creates/modifies components.

### Clarification Questions (Use Structured Options)

When you need to clarify requirements during the build, **TRY AskUserQuestion with options (fallback to text)**:

**For Node Type Selection**:
```python
try:
    answer = AskUserQuestion(
        questions=[{
            "question": "What type of node should this be?",
            "header": "Node Type",
            "options": [
                {
                    "label": "llm_generate",
                    "description": "Text generation, parsing, analysis"
                },
                {
                    "label": "llm_tool_use",
                    "description": "Actions requiring tools (API calls, data fetching)"
                },
                {
                    "label": "router",
                    "description": "Conditional branching based on output"
                },
                {
                    "label": "function",
                    "description": "Deterministic operations without LLM"
                }
            ],
            "multiSelect": false
        }]
    )
    node_type = answer["Node Type"]
except:
    # Fallback to text
    print("→ Node type? Options: llm_generate | llm_tool_use | router | function")
    node_type = input().strip()
```

**For Edge Conditions**:
```python
AskUserQuestion(
    questions=[{
        "question": "When should this edge be traversed?",
        "header": "Edge Condition",
        "options": [
            {
                "label": "on_success (Recommended)",
                "description": "Proceed only if node succeeds"
            },
            {
                "label": "on_failure",
                "description": "Proceed only if node fails (error handling)"
            },
            {
                "label": "always",
                "description": "Always proceed regardless of result"
            },
            {
                "label": "conditional",
                "description": "Custom expression-based condition"
            }
        ],
        "multiSelect": false
    }]
)
```

**For Multi-Field Input** (e.g., collecting input/output keys):
```python
AskUserQuestion(
    questions=[{
        "question": "What keys should this node read from memory?",
        "header": "Input Keys",
        "options": [
            {
                "label": "objective",
                "description": "User's main objective/request"
            },
            {
                "label": "context",
                "description": "Additional context data"
            },
            {
                "label": "previous_result",
                "description": "Output from previous node"
            },
            {
                "label": "Custom keys",
                "description": "I'll specify custom keys in the text field"
            }
        ],
        "multiSelect": true  # Allow selecting multiple
    }]
)
```

**For Yes/No Decisions**:
```python
AskUserQuestion(
    questions=[{
        "question": "Should this agent support pause/resume for HITL conversations?",
        "header": "HITL Support",
        "options": [
            {
                "label": "Yes",
                "description": "Agent will pause for user input and resume later"
            },
            {
                "label": "No",
                "description": "Agent runs end-to-end without pausing"
            }
        ],
        "multiSelect": false
    }]
)
```

**General Rules**:
- If there are 2-4 common options → Use structured questions with fallback
- For truly open-ended input (system prompts, descriptions) → Text input only
- **Always wrap AskUserQuestion in try/except** to handle environments without widget support
- Fallback format: Simple text prompt listing the options

## Defining Goals

Goals must be measurable. Include:

```python
Goal(
    id="my-agent",
    name="My Agent",
    description="One sentence describing what it does",
    success_criteria=[
        SuccessCriterion(
            id="primary",
            description="What must be true for success",
            metric="how to measure",
            target="threshold",
            weight=1.0,
        ),
    ],
    constraints=[
        Constraint(
            id="safety",
            description="What the agent must NOT do",
            constraint_type="hard",  # hard = must not violate
            category="safety",
        ),
    ],
)
```

**Good goals**: Specific, measurable, constrained
**Bad goals**: Vague, unmeasurable, no boundaries

## Integrating External Tools (MCP Servers)

Before adding nodes, you can register MCP servers to make their tools available to your agent.

### Using aden-tools in the Hive Monorepo

The hive monorepo includes `aden-tools` which provides web search, web scraping, and file operations.

**Step 1: Register the MCP Server**

After creating your session, register aden-tools:

```python
# Using MCP tools
add_mcp_server(
    name="aden-tools",
    transport="stdio",
    command="python",
    args='["mcp_server.py", "--stdio"]',
    cwd="../aden-tools"  # Relative to core/ directory
)
```

**Expected response:**
```json
{
  "success": true,
  "server": {
    "name": "aden-tools",
    "transport": "stdio",
    "command": "python",
    "args": ["-m", "aden_tools.server"],
    "cwd": "../aden-tools"
  },
  "tools_discovered": 6,
  "tools": [
    "web_search",
    "web_scrape",
    "file_read",
    "file_write",
    "pdf_read",
    "example_tool"
  ],
  "note": "MCP server 'aden-tools' registered with 6 tools..."
}
```

**Step 2: List Available Tools** (optional verification)

```python
list_mcp_tools(server_name="aden-tools")
```

This shows detailed information about each tool including parameters.

**Step 3: Use Tools in Your Nodes**

Now you can reference these tools in `llm_tool_use` nodes:

```python
add_node(
    node_id="web_searcher",
    name="Web Searcher",
    description="Search the web for information",
    node_type="llm_tool_use",
    input_keys='["query"]',
    output_keys='["search_results"]',
    tools='["web_search"]',  # ← Tool from aden-tools
    system_prompt="Search for {query} using web_search tool"
)
```

**Step 4: Export Creates mcp_servers.json**

When you export your agent with `export_graph()`, the MCP server configuration is automatically saved:

```
exports/my-agent/
├── agent.json           # Agent specification
├── README.md            # Documentation
└── mcp_servers.json     # ← MCP configuration (auto-generated)
```

The `mcp_servers.json` file ensures the agent can access aden-tools when run later.

### Available aden-tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `web_search` | Search the web using Brave Search API | `query`, `num_results`, `country` |
| `web_scrape` | Extract text content from a webpage | `url`, `selector`, `include_links` |
| `file_read` | Read file contents | `path` |
| `file_write` | Write content to files | `path`, `content` |
| `pdf_read` | Extract text from PDF files | `path` |

### MCP Server Management

List registered servers:
```python
list_mcp_servers()
```

Remove a server:
```python
remove_mcp_server(name="aden-tools")
```

### Best Practices

1. **Register early**: Call `add_mcp_server` right after `create_session` and before defining nodes
2. **Verify tools**: Use `list_mcp_tools` to see available tools and their parameters
3. **Minimal tools**: Only include tools a node actually needs in its `tools` list
4. **Test nodes**: Use `test_node` to verify tool access works before building the full graph

### Example: Research Agent with aden-tools

```python
# 1. Create session
create_session(name="research-agent")

# 2. Register aden-tools
add_mcp_server(
    name="aden-tools",
    transport="stdio",
    command="python",
    args='["mcp_server.py", "--stdio"]',
    cwd="../aden-tools"
)

# 3. Verify tools
list_mcp_tools(server_name="aden-tools")

# 4. Define goal
set_goal(
    goal_id="research",
    name="Research Agent",
    description="Gather and synthesize information",
    success_criteria='[...]',
    constraints='[...]'
)

# 5. Add node that uses web_search
add_node(
    node_id="searcher",
    name="Information Searcher",
    node_type="llm_tool_use",
    input_keys='["topic"]',
    output_keys='["search_results"]',
    tools='["web_search"]',  # From aden-tools
    system_prompt="Search for information about {topic}"
)

# 6. Continue building...
```

## Adding Nodes

Each node does one thing:

```python
NodeSpec(
    id="processor",
    name="Processor",
    description="What this node does",
    node_type="llm_tool_use",
    input_keys=["input_data"],      # What it reads
    output_keys=["result"],          # What it writes
    tools=["tool_a", "tool_b"],      # Available tools
    system_prompt="Instructions for the LLM",
)
```

**Node design rules**:
- Single responsibility
- Explicit input/output keys
- Minimal tools (only what's needed)
- Specific system prompts

## Connecting Edges

Edges define flow:

```python
EdgeSpec(
    id="process-to-format",
    source="processor",
    target="formatter",
    condition=EdgeCondition.ON_SUCCESS,
)
```

**Edge rules**:
- Every node (except terminal) needs outgoing edges
- Handle failure paths explicitly
- Use priority when multiple edges could match

## Pause/Resume Architecture (HITL Conversations)

For agents that need multi-turn conversations with users:

### Graph Configuration

```python
GraphSpec(
    entry_node="start-node",
    entry_points={
        "start": "analyze-input",                    # Initial entry
        "request-clarification_resume": "process-clarification",  # Resume after pause
    },
    pause_nodes=["request-clarification"],  # Nodes that pause execution
    terminal_nodes=["output-result"],
)
```

### Pause Node Pattern

**Pause nodes** generate output (e.g., questions) then pause execution:

```python
# Node 1: Detect if clarification needed (entry node)
NodeSpec(
    id="analyze-input",
    node_type="llm_generate",
    input_keys=["objective"],
    output_keys=["objective", "needs_clarification", "questions"],
)

# Node 2: Ask questions (PAUSE NODE)
NodeSpec(
    id="request-clarification",
    node_type="llm_generate",
    input_keys=["objective", "questions"],
    output_keys=["questions_to_ask"],  # Returns questions to user
)

# Node 3: Process user's answers (RESUME ENTRY POINT)
NodeSpec(
    id="process-clarification",
    node_type="llm_generate",
    input_keys=["objective", "questions_to_ask", "input"],  # input = user's answers
    output_keys=["enriched_objective", "ready"],
)
```

### Execution Flow

**First invocation** (fresh start):
```
User: "Travel to LA"
→ Entry: analyze-input
→ Executes: analyze-input (needs_clarification=true)
→ Executes: request-clarification (pause node)
⏸ PAUSES - saves state
```

**Second invocation** (resume):
```
User: "from SF, March 15-20"
→ Entry: process-clarification (resume point)
→ Executes: process-clarification (merges answers)
→ Continues: identify-stakeholders → ...
```

### Key Rules

1. **Pause nodes are NOT terminal** - They execute fully, save state, then pause
2. **Entry points** - Each pause node needs a `{pause_node}_resume` entry point
3. **Resume node** - Takes user's follow-up input in the `input` key
4. **State restoration** - All memory from pause is restored automatically

## Validation Checks

Before running, validate:
- [ ] Entry node exists (no incoming edges)
- [ ] Terminal nodes exist (no outgoing edges)
- [ ] All nodes reachable from entry
- [ ] No orphan nodes
- [ ] All edge sources/targets exist

## Example: Calculator Agent

See [examples/calculator.md](examples/calculator.md) for a complete example.

## Example: Sales Agent

See [examples/sales-agent.md](examples/sales-agent.md) for a multi-node agent with tools.

## Common Patterns

**Linear pipeline**: A → B → C → D (each node feeds the next)

**Router pattern**: A → Router → [B or C or D] based on condition

**Error handling**: Add `on_failure` edges to error handler nodes

**Parallel paths**: Multiple edges from same source (use priority)

**HITL Conversation** (multi-turn with user):
```
analyze → needs_clarification? → YES → request-clarification (PAUSE)
                              ↓ NO                          ↓
                              process                [User provides answers]
                                                             ↓
                                              process-clarification (RESUME) → continue
```
- Pause node generates questions and pauses
- User provides answers in next invocation
- Resume node merges answers and continues
- State persists across pauses automatically

## Anti-Patterns

**Too many nodes**: If a node does one tiny thing, combine with others

**Vague prompts**: "Process the data" → "Extract the customer name and email from the JSON"

**Missing error paths**: Always handle what happens when nodes fail

**Circular dependencies**: Nodes shouldn't loop back without exit conditions

**Terminal pause nodes**: ❌ Don't make pause nodes terminal - they need edges to resume nodes

**Missing resume entry points**: ❌ Each pause node needs a `{pause_node}_resume` entry point

**Restarting instead of resuming**: ❌ Don't route back to entry node - use resume entry points

## Tools Reference

### Building Tools
| Tool | Purpose |
|------|---------|
| `create_session` | Start a new agent building session |
| `set_goal` | Define the goal with success criteria and constraints |
| `add_node` | Add a node to the graph |
| `add_edge` | Connect two nodes with an edge |
| `validate_graph` | Check the graph for errors |
| `export_graph` | Export the completed agent |
| `get_session_status` | View current build progress |

### Testing Tools (for HITL approval)
| Tool | Purpose |
|------|---------|
| `test_node` | Run a single node with sample inputs to show behavior |
| `test_graph` | Simulate full graph execution to show the complete flow |

## Using the Exported Agent

After `export_graph`, you get JSON containing both the **plan** and the **goal**.

### 1. Save the Export to Proper Location

**CRITICAL**: Each agent MUST be saved to its own folder under `exports/`:

```
exports/
├── outbound-sales-agent/
│   ├── agent.json          # The export_graph() output
│   └── tools.py            # Tool implementations (optional)
├── lead-qualifier/
│   ├── agent.json
│   └── tools.py
└── customer-support/
    ├── agent.json
    └── tools.py
```

Save the complete output from `export_graph()`:
```python
import os

# Create agent folder
agent_name = "outbound-sales-agent"  # Use the session name
os.makedirs(f"exports/{agent_name}", exist_ok=True)

# Save the export
with open(f"exports/{agent_name}/agent.json", "w") as f:
    f.write(export_graph_output)
```

### 2. Running the Agent (CLI)

Use the built-in agent runner CLI:

```bash
# Show agent info
python -m core info exports/outbound-sales-agent

# Validate the agent
python -m core validate exports/outbound-sales-agent

# Run with JSON input
python -m core run exports/outbound-sales-agent --input '{"lead_id": "123"}'

# Interactive shell (best for conversational agents)
python -m core shell exports/outbound-sales-agent

# Run in mock mode (no real LLM calls)
python -m core run exports/outbound-sales-agent --input '{"lead_id": "123"}' --mock

# List all agents
python -m core list exports/
```

**Interactive Shell** (for agents with pause/resume):
```bash
$ python -m core shell exports/task-planner

>>> Travel to LA this month
⏸ Agent paused at: request-clarification
   Questions: ["What's your departure city?", "What dates?"]

>>> from San Francisco, March 15-20
🔄 Resuming from paused state
✓ Execution complete!

# Use /reset to clear conversation state
>>> /reset
✓ Conversation state and agent session cleared
```

### 3. Running the Agent (Python API)

Use `AgentRunner` for programmatic access:

```python
import asyncio
from framework.runner import AgentRunner

async def main():
    # Load and run
    runner = AgentRunner.load("exports/outbound-sales-agent")
    result = await runner.run({"lead_id": "123"})

    if result.status.value == "completed":
        print("Success!", result.results)
    else:
        print("Needs attention:", result.feedback)

asyncio.run(main())
```

With context manager:
```python
async with AgentRunner.load("exports/outbound-sales-agent") as runner:
    result = await runner.run({"lead_id": "123"})
```

### 4. Providing Tools

Create `tools.py` in the agent folder:

```python
"""Tools for my-agent."""
import json
from framework.llm.provider import Tool, ToolUse, ToolResult

# Define tools
TOOLS = {
    "my_tool": Tool(
        name="my_tool",
        description="What it does",
        parameters={"type": "object", "properties": {"param": {"type": "string"}}},
    ),
}

# Implement executor
def tool_executor(tool_use: ToolUse) -> ToolResult:
    if tool_use.name == "my_tool":
        result = do_something(tool_use.input["param"])
        return ToolResult(
            tool_use_id=tool_use.id,
            content=json.dumps(result),
            is_error=False,
        )
```

Or register tools programmatically:
```python
runner = AgentRunner.load("exports/my-agent")
runner.register_tool("my_tool", my_tool_function)
result = await runner.run(context)
```

For complete API details, see [reference/api.md](reference/api.md).
