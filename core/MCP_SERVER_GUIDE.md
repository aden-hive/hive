# MCP Server Guide - Agent Builder

This guide covers the MCP (Model Context Protocol) server for building goal-driven agents.

## Setup

### Quick Setup

```bash
# Using the setup script (recommended)
python setup_mcp.py

# Or using bash
./setup_mcp.sh
```

### Manual Configuration

Add to your MCP client configuration (e.g., Claude Desktop):

```json
{
  "mcpServers": {
    "agent-builder": {
      "command": "python",
      "args": ["-m", "framework.mcp.agent_builder_server"],
      "cwd": "/path/to/goal-agent"
    }
  }
}
```

## Available MCP Tools

### Session Management

#### `create_session`
Create a new agent building session.

**Parameters:**
- `name` (string, required): Name of the agent

**Example:**
```json
{
  "name": "research-summary-agent"
}
```

#### `get_session_status`
Get the current status of the build session.

**Returns:**
- Session name
- Goal status
- Number of nodes
- Number of edges
- Validation status

---

### Goal Definition

#### `set_goal`
Define the goal for the agent with success criteria and constraints.

**Parameters:**
- `goal_id` (string, required): Unique identifier for the goal
- `name` (string, required): Human-readable name
- `description` (string, required): What the agent should accomplish
- `success_criteria` (string, required): JSON array of success criteria
- `constraints` (string, optional): JSON array of constraints

**Success Criterion Structure:**
```json
{
  "id": "criterion_id",
  "description": "What should be achieved",
  "metric": "How to measure it",
  "target": "Target value",
  "weight": 1.0
}
```

**Constraint Structure:**
```json
{
  "id": "constraint_id",
  "description": "What must not happen",
  "constraint_type": "hard|soft",
  "category": "safety|quality|performance"
}
```

---

### Node Management

#### `add_node`
Add a processing node to the agent graph.

**Parameters:**
- `node_id` (string, required): Unique node identifier
- `name` (string, required): Human-readable name
- `description` (string, required): What this node does
- `node_type` (string, required): Must be `event_loop` (the only valid type)
- `input_keys` (string, required): JSON array of input variable names
- `output_keys` (string, required): JSON array of output variable names
- `system_prompt` (string, optional): System prompt for the LLM
- `tools` (string, optional): JSON array of tool names
- `client_facing` (boolean, optional): Set to true for human-in-the-loop interaction

**Node Type:**

**event_loop**: LLM-powered node with self-correction loop
- Requires: `system_prompt`
- Optional: `tools` (array of tool names, e.g., `["web_search", "web_fetch"]`)
- Optional: `client_facing` (set to true for HITL / user interaction)
- Supports: iterative refinement, judge-based evaluation, tool use, streaming

**Example:**
```json
{
  "node_id": "search_sources",
  "name": "Search Sources",
  "description": "Searches for relevant sources on the topic",
  "node_type": "event_loop",
  "input_keys": "[\"topic\", \"search_queries\"]",
  "output_keys": "[\"sources\", \"source_count\"]",
  "system_prompt": "Search for sources using the provided queries...",
  "tools": "[\"web_search\"]"
}
```

---

### Edge Management

#### `add_edge`
Connect two nodes with an edge to define execution flow.

**Parameters:**
- `edge_id` (string, required): Unique edge identifier
- `source` (string, required): Source node ID
- `target` (string, required): Target node ID
- `condition` (string, optional): When to traverse: `on_success` (default) or `on_failure`
- `condition_expr` (string, optional): Python expression for conditional routing
- `priority` (integer, optional): Edge priority (default: 0)

**Example:**
```json
{
  "edge_id": "search_to_extract",
  "source": "search_sources",
  "target": "extract_content",
  "condition": "on_success"
}
```

---

### Graph Validation

#### `validate_graph`
Validate the complete graph structure.

**Checks:**
- Entry node exists
- All nodes are reachable from entry
- Terminal nodes have no outgoing edges
- No cycles (unless explicitly allowed)
- Context flow: all required inputs are available

**Returns:**
- `valid` (boolean)
- `errors` (array): List of validation errors
- `warnings` (array): Non-critical issues
- `entry_node` (string): Entry node ID
- `terminal_nodes` (array): Terminal node IDs

---

### Graph Export

#### `export_graph`
Export the validated graph as an agent specification.

**What it does:**
1. Validates the graph
2. Validates edge connectivity
3. Writes files to disk:
   - `exports/{agent-name}/agent.json` - Full agent specification
   - `exports/{agent-name}/README.md` - Auto-generated documentation

**Returns:**
- `success` (boolean)
- `files_written` (object): Paths and sizes of written files
- `agent` (object): Agent metadata
- `graph` (object): Graph specification
- `goal` (object): Goal definition
- `required_tools` (array): All tools used by the agent

**Important:** This tool automatically writes files to the `exports/` directory!

---

### Testing

#### `test_node`
Test a single node with sample inputs.

**Parameters:**
- `node_id` (string, required): Node to test
- `test_input` (string, required): JSON object with input values
- `mock_llm_response` (string, optional): Mock LLM response for testing

**Example:**
```json
{
  "node_id": "research_planner",
  "test_input": "{\"topic\": \"LLM compaction\"}"
}
```

#### `test_graph`
Test the complete agent graph with sample inputs.

**Parameters:**
- `test_input` (string, required): JSON object with initial inputs
- `dry_run` (boolean, optional): Simulate without LLM calls (default: true)
- `max_steps` (integer, optional): Maximum execution steps (default: 10)

**Example:**
```json
{
  "test_input": "{\"topic\": \"AI safety\"}",
  "dry_run": true,
  "max_steps": 10
}
```

---

## Example Workflow

Here's a complete workflow for building a research agent:

```python
# 1. Create session
create_session(name="research-agent")

# 2. Define goal
set_goal(
    goal_id="research-goal",
    name="Research Topic Agent",
    description="Research a topic and produce a summary",
    success_criteria=json.dumps([{
        "id": "comprehensive",
        "description": "Cover main aspects",
        "metric": "Key topics addressed",
        "target": "At least 3-5 aspects",
        "weight": 1.0
    }])
)

# 3. Add nodes
add_node(
    node_id="planner",
    name="Research Planner",
    description="Creates research strategy",
    node_type="event_loop",
    input_keys='["topic"]',
    output_keys='["strategy", "queries"]',
    system_prompt="Analyze topic and create research plan..."
)

add_node(
    node_id="searcher",
    name="Search Sources",
    description="Find relevant sources",
    node_type="event_loop",
    input_keys='["queries"]',
    output_keys='["sources"]',
    system_prompt="Search for sources...",
    tools='["web_search"]'
)

# 4. Connect nodes
add_edge(
    edge_id="plan_to_search",
    source="planner",
    target="searcher"
)

# 5. Validate
validate_graph()

# 6. Export
export_graph()
```

The exported agent will be saved to `exports/research-agent/`.

---

## Tips

1. **Start with the goal**: Define clear success criteria before building nodes
2. **Test nodes individually**: Use `test_node` to verify each node works
3. **Use conditional edges for branching**: Define condition_expr on edges for decision points
4. **Validate early, validate often**: Run `validate_graph` after adding nodes/edges
5. **Check exports**: Review the generated README.md to verify your agent structure

---

## Common Issues

### "Node X is unreachable from entry"
- Make sure there's a path of edges from the entry node to all nodes
- Check that you've defined edges connecting your nodes

### "Missing required input Y for node X"
- Ensure previous nodes output the required inputs
- Check your input_keys and output_keys match

### "Router routes don't match edges"
- Don't worry! The export tool auto-generates missing edges from routes
- If you see this warning, it's informational only

### "Cannot find tool Z"
- Verify the tool name matches available tools (e.g., "web_search", "web_fetch")
- Check the `required_tools` section in the exported agent

---

## Resources

- **Framework Documentation**: See [README.md](README.md)
- **Example Agents**: Check the `exports/` directory for examples
- **MCP Protocol**: https://modelcontextprotocol.io
