# Hive Agent Builder Instructions

You have access to MCP tools for building goal-driven AI agents.

## Available MCP Servers

1. **agent-builder** - Tools for creating agent graphs
2. **hive-tools** - Runtime tools (web search, file operations, etc.)

## Agent Building Workflow

### Step 1: Create a Session
```
mcp.agent-builder.create_session(name="my-agent")
```

### Step 2: Register Tools Server
Before adding nodes that use tools, register the hive-tools server:
```
mcp.agent-builder.add_mcp_server(
    name="hive-tools",
    transport="stdio",
    command="python",
    args='["mcp_server.py", "--stdio"]',
    cwd="tools",
    description="Hive tools for web search, file operations"
)
```

### Step 3: Define the Goal
```
mcp.agent-builder.set_goal(
    goal_id="research-goal",
    name="Research a Topic",
    description="Search the web and create a summary",
    success_criteria='[{"id": "sc1", "description": "Found 3+ sources", "metric": "source_count", "target": ">=3"}]'
)
```

### Step 4: Add Nodes

Node types:
- `llm_generate`: Pure LLM text/JSON generation (no tools)
- `llm_tool_use`: LLM with tool access
- `router`: Conditional branching
- `function`: Python function execution

Example:
```
mcp.agent-builder.add_node(
    node_id="search-web",
    name="Search the Web",
    description="Searches for information on the topic",
    node_type="llm_tool_use",
    input_keys='["topic"]',
    output_keys='["search_results"]',
    system_prompt="Search for information about the given topic...",
    tools='["web_search"]'
)
```

### Step 5: Connect Nodes with Edges
```
mcp.agent-builder.add_edge(
    edge_id="e1",
    source="search-web",
    target="summarize",
    condition="on_success"
)
```

### Step 6: Validate and Export
```
mcp.agent-builder.validate_graph()
mcp.agent-builder.export_graph(output_dir="exports/my_agent")
```

## Available Tools (from hive-tools)

When adding `llm_tool_use` nodes, you can use these tools:

| Tool | Description |
|------|-------------|
| `web_search` | Search the web using Brave Search API |
| `web_scrape` | Scrape content from a webpage |
| `pdf_read` | Read and extract text from PDFs |
| `view_file` | Read file contents |
| `write_to_file` | Write content to a file |
| `list_dir` | List directory contents |
| `grep_search` | Search for patterns in files |
| `execute_command_tool` | Run shell commands |

## Important Rules

1. **Always register hive-tools FIRST** before adding nodes that use tools
2. **Only use tools that exist** - check with `mcp.agent-builder.list_mcp_tools()`
3. **entry_points format**: Always use `{"start": "first-node-id"}`
4. **Validate before export** - catches errors early

## Quick Example: Research Agent

```python
# 1. Create session
mcp.agent-builder.create_session(name="research-agent")

# 2. Register tools
mcp.agent-builder.add_mcp_server(
    name="hive-tools",
    transport="stdio",
    command="python",
    args='["mcp_server.py", "--stdio"]',
    cwd="tools"
)

# 3. Set goal
mcp.agent-builder.set_goal(
    goal_id="research",
    name="Research Topic",
    description="Search the web for a topic and write a summary",
    success_criteria='[{"id": "sc1", "description": "Summary written", "metric": "has_summary"}]'
)

# 4. Add nodes
mcp.agent-builder.add_node(
    node_id="search",
    name="Search Web",
    node_type="llm_tool_use",
    input_keys='["topic"]',
    output_keys='["search_results"]',
    system_prompt="Search for information about {topic}",
    tools='["web_search"]'
)

mcp.agent-builder.add_node(
    node_id="summarize",
    name="Summarize",
    node_type="llm_generate",
    input_keys='["search_results"]',
    output_keys='["summary"]',
    system_prompt="Summarize the search results into a coherent report"
)

# 5. Add edges
mcp.agent-builder.add_edge(edge_id="e1", source="search", target="summarize")

# 6. Export
mcp.agent-builder.validate_graph()
mcp.agent-builder.export_graph(output_dir="exports/research_agent")
```

## Running Your Agent

After export:

```bash
cd exports/research_agent
PYTHONPATH=../../core:../../tools/src python -m research_agent run --input '{"topic": "quantum computing"}'
```

## More Information

- Detailed patterns: `.claude/skills/building-agents-construction/SKILL.md`
- Core concepts: `.claude/skills/building-agents-core/SKILL.md`
- MCP server guide: `core/MCP_SERVER_GUIDE.md`
- Example agent: `.claude/skills/building-agents-construction/examples/online_research_agent/`
