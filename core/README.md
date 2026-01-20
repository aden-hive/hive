# Framework

A goal-driven agent runtime with Builder-friendly observability.

## Overview

Framework provides a runtime framework that captures **decisions**, not just actions. This enables a "Builder" LLM to analyze and improve agent behavior by understanding:

- What the agent was trying to accomplish
- What options it considered
- What it chose and why
- What happened as a result

## Installation

```bash
pip install -e .
```

## MCP Server Setup

The framework includes an MCP (Model Context Protocol) server for building agents. To set up the MCP server:

### Automated Setup

**Using bash (Linux/macOS):**
```bash
./setup_mcp.sh
```

**Using Python (cross-platform):**
```bash
python setup_mcp.py
```

The setup script will:
1. Install the framework package
2. Install MCP dependencies (mcp, fastmcp)
3. Create/verify `.mcp.json` configuration
4. Test the MCP server module

### Manual Setup

If you prefer manual setup:

```bash
# Install framework
pip install -e .

# Install MCP dependencies
pip install mcp fastmcp

# Test the server
python -m framework.mcp.agent_builder_server
```

### Using with MCP Clients

To use the agent builder with Claude Desktop or other MCP clients, add this to your MCP client configuration:

```json
{
  "mcpServers": {
    "agent-builder": {
      "command": "python",
      "args": ["-m", "framework.mcp.agent_builder_server"],
      "cwd": "/path/to/hive/core"
    }
  }
}
```

The MCP server provides tools for:
- Creating agent building sessions
- Defining goals with success criteria
- Adding nodes (llm_generate, llm_tool_use, router, function)
- Connecting nodes with edges
- **Registering MCP servers as tool sources** ✨
- **Discovering tools from MCP servers** ✨
- Validating and exporting agent graphs
- Testing nodes and full agent graphs

When you register an MCP server during agent building, the tools from that server become available to your agent, and an `mcp_servers.json` configuration file is automatically created on export.

See [MCP_SERVER_GUIDE.md](MCP_SERVER_GUIDE.md) for agent builder instructions and [MCP_BUILDER_TOOLS_GUIDE.md](MCP_BUILDER_TOOLS_GUIDE.md) for MCP integration tools.

## MCP Tool Integration

The framework also supports **connecting to MCP servers as tool providers**, allowing your agents to use tools from external MCP servers (like aden-tools). This enables you to extend your agents with powerful external capabilities.

### Quick Example

```python
from framework.runner.runner import AgentRunner

# Load an agent
runner = AgentRunner.load("exports/task-planner")

# Register an MCP server with tools
runner.register_mcp_server(
    name="aden-tools",
    transport="stdio",
    command="python",
    args=["mcp_server.py", "--stdio"],
    cwd="../aden-tools"
)

# Tools from the MCP server are now available to your agent
result = await runner.run({"query": "Search for AI news"})
```

### Auto-loading MCP Servers

Create `mcp_servers.json` in your agent folder:

```json
{
  "servers": [
    {
      "name": "aden-tools",
      "transport": "stdio",
      "command": "python",
      "args": ["mcp_server.py", "--stdio"],
      "cwd": "../aden-tools"
    }
  ]
}
```

MCP servers will be automatically loaded when you load the agent.

### Available Tools from aden-tools

When you register the aden-tools MCP server, these tools become available:
- `web_search` - Search the web using Brave Search API
- `web_scrape` - Extract content from web pages
- `file_read` - Read file contents
- `file_write` - Write content to files
- `pdf_read` - Extract text from PDF files

See [MCP_INTEGRATION_GUIDE.md](MCP_INTEGRATION_GUIDE.md) for detailed instructions on MCP tool integration.

## Quick Start

### Running Agents

The framework comes with pre-built example agents in the `exports/` directory:

```bash
# List available agents
python -m framework list exports/

# Show agent information
python -m framework info exports/task-planner

# Run an agent
python -m framework run exports/task-planner --input '{"objective": "Build a web scraper"}'

# Interactive shell mode (with human-in-the-loop approval)
python -m framework shell exports/task-planner
```

### Available Commands

- `run` - Execute an exported agent with given input
- `info` - Display agent details (goal, nodes, edges, success criteria)
- `validate` - Check that an agent is valid and runnable
- `list` - List all exported agents in a directory
- `dispatch` - Route requests to multiple agents using the orchestrator
- `shell` - Start an interactive session with an agent

### Building Agents Programmatically

You can build agents using the MCP server (recommended) or programmatically:

```python
from framework import Runtime

# Initialize runtime with storage path
runtime = Runtime("./storage")

# Start a run for a goal
run_id = runtime.start_run(
    goal_id="data-processor",
    goal_description="Process data with quality checks",
    input_data={"dataset": "customers.csv"}
)

# Set the current node context
runtime.set_node("processor-node")

# Record a decision
decision_id = runtime.decide(
    intent="Choose how to process the data",
    options=[
        {
            "id": "fast",
            "description": "Quick processing",
            "action_type": "tool_call",
            "pros": ["Fast"],
            "cons": ["Less accurate"]
        },
        {
            "id": "thorough",
            "description": "Detailed processing",
            "action_type": "tool_call",
            "pros": ["Accurate"],
            "cons": ["Slower"]
        },
    ],
    chosen="thorough",
    reasoning="Accuracy is more important for this task"
)

# Record the outcome of the decision
runtime.record_outcome(
    decision_id=decision_id,
    success=True,
    result={"processed": 100},
    summary="Processed 100 items with detailed analysis"
)

# End the run
runtime.end_run(
    success=True,
    narrative="Successfully processed all data",
    output_data={"total_processed": 100}
)
```

### Analyzing Agent Behavior with Builder

The BuilderQuery interface allows you to analyze agent runs and identify improvements:

```python
from framework import BuilderQuery

# Initialize Builder query interface
query = BuilderQuery("./storage")

# Find patterns across runs for a goal
patterns = query.find_patterns("data-processor")
if patterns:
    print(f"Success rate: {patterns.success_rate:.1%}")
    print(f"Runs analyzed: {patterns.run_count}")

    # Show problematic nodes
    for node_id, failure_rate in patterns.problematic_nodes:
        print(f"Node '{node_id}' has {failure_rate:.1%} failure rate")

# Analyze a specific failure
analysis = query.analyze_failure("run_20260119_143022_abc123")
if analysis:
    print(f"Failure point: {analysis.failure_point}")
    print(f"Root cause: {analysis.root_cause}")
    print(f"\nSuggestions:")
    for suggestion in analysis.suggestions:
        print(f"  - {suggestion}")

# Get improvement recommendations for a goal
suggestions = query.suggest_improvements("data-processor")
for s in suggestions:
    print(f"[{s['priority']}] {s['recommendation']}")
    print(f"  Reason: {s['reason']}")

# Get performance metrics for a specific node
perf = query.get_node_performance("processor-node")
print(f"Node: {perf['node_id']}")
print(f"Success rate: {perf['success_rate']:.1%}")
print(f"Avg latency: {perf['avg_latency_ms']:.0f}ms")
```

## Architecture

The framework consists of several layers:

```
┌─────────────────┐
│  Human Engineer │  ← Supervision, approval via HITL
└────────┬────────┘
         │
┌────────▼────────┐
│   Builder LLM   │  ← Analyzes runs, suggests improvements (via MCP)
│  (BuilderQuery) │
└────────┬────────┘
         │
┌────────▼────────┐
│   Agent Graph   │  ← Node-based execution flow
│   (AgentRunner) │     (llm_generate, llm_tool_use, router, function)
└────────┬────────┘
         │
┌────────▼────────┐
│    Runtime      │  ← Records decisions, outcomes, problems
│   (Decision DB) │
└─────────────────┘
```

## Key Concepts

### Graph-Based Agents

Agents are defined as directed graphs with:
- **Nodes**: Execution steps (llm_generate, llm_tool_use, router, function)
- **Edges**: Control flow between nodes, including conditional routing
- **Goal**: What the agent is designed to accomplish with success criteria
- **Constraints**: Hard and soft limits on agent behavior

### Decision Recording

- **Decision**: The atomic unit of agent behavior. Captures intent, options, choice, and reasoning.
- **Outcome**: Result of executing a decision (success/failure, latency, tokens, state changes)
- **Run**: A complete execution trace with all decisions and outcomes
- **Problem**: Issues reported during execution with severity and suggested fixes

### Analysis & Improvement

- **Runtime**: Interface agents use to record their behavior during execution
- **BuilderQuery**: Interface for analyzing agent runs and identifying patterns
- **PatternAnalysis**: Cross-run analysis showing success rates, common failures, problematic nodes
- **FailureAnalysis**: Deep dive into why a specific run failed with suggestions

### Human-in-the-Loop (HITL)

- **Approval Callbacks**: Nodes can require human approval before execution
- **Interactive Shell**: Chat-like interface for running agents with approval prompts
- **Session State**: Agents can pause and resume based on user input

### Multi-Agent Orchestration

- **AgentOrchestrator**: Dispatch requests to multiple agents
- **Agent Discovery**: Automatically discover and register agents from a directory
- **Dispatch Strategy**: Route requests to the most appropriate agent(s)

## Example Agents

The `exports/` directory contains example agents you can run or use as templates:

- **task-planner**: Breaks down complex objectives into actionable tasks with dependencies
- **research-summary-agent**: Conducts research and generates summaries
- **outbound-sales-agent**: Handles outbound sales workflows
- **youtube-comments-research**: Analyzes YouTube comments for insights

Each agent includes:
- `agent.json`: Graph definition with nodes, edges, goal, and constraints
- `README.md`: Agent documentation
- `tools.py` (optional): Custom tool implementations

## Requirements

- Python 3.11+
- pydantic >= 2.0
- anthropic >= 0.40.0 (for LLM-powered agents)
- mcp, fastmcp (optional, for MCP server)
