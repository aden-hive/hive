---
name: building-agents
description: Build goal-driven agents as Python packages. Creates runnable services with full framework access. Use when asked to create an agent, design a workflow, or build automation.
---

# Building Agents

Build goal-driven agents as **Python service packages** with direct file manipulation.

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

**Goal**: Success criteria and constraints (written to agent.py)

**Node**: Unit of work (written to nodes/**init**.py)

- `llm_generate` - Text generation, parsing
- `llm_tool_use` - Actions requiring tools
- `router` - Conditional branching
- `function` - Deterministic operations

**Edge**: Connection between nodes (written to agent.py)

- `on_success` - Proceed if node succeeds
- `on_failure` - Handle errors
- `always` - Always proceed
- `conditional` - Based on expression

**Pause/Resume**: Multi-turn conversations

- Pause nodes stop execution, wait for user input
- Resume entry points continue from pause with user's response

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

## Workflow: Incremental File Construction

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

## Step-by-Step Guide

### Step 1: Create Package Structure

When user requests an agent, **immediately create the package**:

```python
# 1. Create directory
agent_name = "technical_research_agent"  # snake_case
package_path = f"exports/{agent_name}"

Bash(f"mkdir -p {package_path}/nodes")

# 2. Write skeleton files
Write(
    file_path=f"{package_path}/__init__.py",
    content='''"""
Agent package - will be populated as build progresses.
"""
'''
)

Write(
    file_path=f"{package_path}/nodes/__init__.py",
    content='''"""Node definitions."""
from framework.graph import NodeSpec

# Nodes will be added here as they are approved

__all__ = []
'''
)

Write(
    file_path=f"{package_path}/agent.py",
    content='''"""Agent graph construction."""
from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import GraphExecutor
from framework.runtime import Runtime
from framework.llm.anthropic import AnthropicProvider
from framework.runner.tool_registry import ToolRegistry
from aden_tools.credentials import CredentialManager

# Goal will be added when defined
# Nodes will be imported from .nodes
# Edges will be added when approved
# Agent class will be created when graph is complete
'''
)

Write(
    file_path=f"{package_path}/config.py",
    content='''"""Runtime configuration."""
from dataclasses import dataclass

@dataclass
class RuntimeConfig:
    model: str = "claude-sonnet-4-5-20250929"
    temperature: float = 0.7
    max_tokens: int = 4096

default_config = RuntimeConfig()

# Metadata will be added when goal is set
'''
)

Write(
    file_path=f"{package_path}/__main__.py",
    content=CLI_TEMPLATE  # Full CLI template (see below)
)
```

**Show user:**

```
✅ Package created: exports/technical_research_agent/
📁 Files created:
   - __init__.py (skeleton)
   - __main__.py (CLI ready)
   - agent.py (skeleton)
   - nodes/__init__.py (empty)
   - config.py (skeleton)

You can open these files now and watch them grow as we build!
```

### Step 2: Define Goal

Propose goal, get approval, **write immediately**:

```python
# After user approves goal...

goal_code = f'''
goal = Goal(
    id="{goal_id}",
    name="{name}",
    description="{description}",
    success_criteria=[
        SuccessCriterion(
            id="{sc.id}",
            description="{sc.description}",
            metric="{sc.metric}",
            target="{sc.target}",
            weight={sc.weight},
        ),
        # ... more criteria
    ],
    constraints=[
        Constraint(
            id="{c.id}",
            description="{c.description}",
            constraint_type="{c.constraint_type}",
            category="{c.category}",
        ),
        # ... more constraints
    ],
)
'''

# Append to agent.py
Read(f"{package_path}/agent.py")  # Must read first
Edit(
    file_path=f"{package_path}/agent.py",
    old_string="# Goal will be added when defined",
    new_string=f"# Goal definition\n{goal_code}"
)

# Write metadata to config.py
metadata_code = f'''
@dataclass
class AgentMetadata:
    name: str = "{name}"
    version: str = "1.0.0"
    description: str = "{description}"

metadata = AgentMetadata()
'''

Read(f"{package_path}/config.py")
Edit(
    file_path=f"{package_path}/config.py",
    old_string="# Metadata will be added when goal is set",
    new_string=f"# Agent metadata\n{metadata_code}"
)
```

**Show user:**

```
✅ Goal written to agent.py
✅ Metadata written to config.py

Open exports/technical_research_agent/agent.py to see the goal!
```

### Step 3: Add Nodes (Incremental)

**⚠️ IMPORTANT:** Before adding any node with tools, you MUST:

1. Call `mcp__agent-builder__list_mcp_tools()` to discover available tools
2. Verify each tool exists in the response
3. If a tool doesn't exist, inform the user and ask how to proceed

For each node, **write immediately after approval**:

```python
# After user approves node...

node_code = f'''
{node_id.replace('-', '_')}_node = NodeSpec(
    id="{node_id}",
    name="{name}",
    description="{description}",
    node_type="{node_type}",
    input_keys={input_keys},
    output_keys={output_keys},
    system_prompt="""\\
{system_prompt}
""",
    tools={tools},
    max_retries={max_retries},
)

'''

# Append to nodes/__init__.py
Read(f"{package_path}/nodes/__init__.py")
Edit(
    file_path=f"{package_path}/nodes/__init__.py",
    old_string="__all__ = []",
    new_string=f"{node_code}\n__all__ = []"
)

# Update __all__ exports
all_node_names = [n.replace('-', '_') + '_node' for n in approved_nodes]
all_exports = f"__all__ = {all_node_names}"

Edit(
    file_path=f"{package_path}/nodes/__init__.py",
    old_string="__all__ = []",
    new_string=all_exports
)
```

**Show user after each node:**

```
✅ Added analyze_request_node to nodes/__init__.py
📊 Progress: 1/6 nodes added

Open exports/technical_research_agent/nodes/__init__.py to see it!
```

**Repeat for each node.** User watches the file grow.

#### Optional: Validate Node with MCP Tools

After writing a node, you can optionally use MCP tools for validation:

```python
# Node is already written to file. Now validate it:
mcp__agent-builder__test_node(
    node_id="analyze-request",
    test_input='{"query": "test query"}',
    mock_llm_response='{"analysis": "mock output"}'
)

# Returns validation result showing node behavior
# This is OPTIONAL - for bookkeeping/validation only
# The node already exists in the file!
```

**Key Point:** The node was written to `nodes/__init__.py` FIRST. The MCP tool is just for validation.

### Step 4: Connect Edges

After all nodes approved, add edges:

```python
# Generate edges code
edges_code = "edges = [\n"
for edge in approved_edges:
    edges_code += f'''    EdgeSpec(
        id="{edge.id}",
        source="{edge.source}",
        target="{edge.target}",
        condition=EdgeCondition.{edge.condition.upper()},
'''
    if edge.condition_expr:
        edges_code += f'        condition_expr="{edge.condition_expr}",\n'
    edges_code += f'        priority={edge.priority},\n'
    edges_code += '    ),\n'
edges_code += "]\n"

# Write to agent.py
Read(f"{package_path}/agent.py")
Edit(
    file_path=f"{package_path}/agent.py",
    old_string="# Edges will be added when approved",
    new_string=f"# Edge definitions\n{edges_code}"
)

# Write entry points and terminal nodes
graph_config = f'''
# Graph configuration
entry_node = "{entry_node_id}"
entry_points = {entry_points}
pause_nodes = {pause_nodes}
terminal_nodes = {terminal_nodes}

# Collect all nodes
nodes = [
    {', '.join(node_names)},
]
'''

Edit(
    file_path=f"{package_path}/agent.py",
    old_string="# Agent class will be created when graph is complete",
    new_string=graph_config
)
```

**Show user:**

```
✅ Edges written to agent.py
✅ Graph configuration added

5 edges connecting 6 nodes
```

#### Optional: Validate Graph Structure

After writing edges, optionally validate with MCP tools:

```python
# Edges already written to agent.py. Now validate structure:
mcp__agent-builder__validate_graph()

# Returns: unreachable nodes, missing connections, etc.
# This is OPTIONAL - for validation only
```

### Step 5: Finalize Agent Class

Write the agent class:

```python
agent_class_code = f'''

class {agent_class_name}:
    """
    {agent_description}
    """

    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.pause_nodes = pause_nodes
        self.terminal_nodes = terminal_nodes
        self.executor = None

    def _create_executor(self, mock_mode=False):
        """Create executor instance."""
        import tempfile
        from pathlib import Path

        storage_path = Path(tempfile.gettempdir()) / "{agent_name}"
        storage_path.mkdir(parents=True, exist_ok=True)

        runtime = Runtime(storage_path=storage_path)
        tool_registry = ToolRegistry()

        llm = None
        if not mock_mode:
            creds = CredentialManager()
            if creds.is_available("anthropic"):
                api_key = creds.get("anthropic")
                llm = AnthropicProvider(api_key=api_key, model=self.config.model)

        graph = GraphSpec(
            id="{agent_name}-graph",
            goal_id=self.goal.id,
            version="1.0.0",
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=self.pause_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
        )

        self.executor = GraphExecutor(
            runtime=runtime,
            llm=llm,
            tools=list(tool_registry.get_tools().values()),
            tool_executor=tool_registry.get_executor(),
        )

        self.graph = graph
        return self.executor

    async def run(self, context: dict, mock_mode=False, session_state=None):
        """Run the agent."""
        executor = self._create_executor(mock_mode=mock_mode)
        result = await executor.execute(
            graph=self.graph,
            goal=self.goal,
            input_data=context,
            session_state=session_state,
        )
        return result

    def info(self):
        """Get agent information."""
        return {{
            "name": metadata.name,
            "version": metadata.version,
            "description": metadata.description,
            "goal": {{
                "name": self.goal.name,
                "description": self.goal.description,
            }},
            "nodes": [n.id for n in self.nodes],
            "edges": [e.id for e in self.edges],
            "entry_node": self.entry_node,
            "pause_nodes": self.pause_nodes,
            "terminal_nodes": self.terminal_nodes,
        }}

    def validate(self):
        """Validate agent structure."""
        errors = []
        warnings = []

        node_ids = {{node.id for node in self.nodes}}
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge {{edge.id}}: source '{{edge.source}}' not found")
            if edge.target not in node_ids:
                errors.append(f"Edge {{edge.id}}: target '{{edge.target}}' not found")

        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{{self.entry_node}}' not found")

        return {{
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }}


# Create default instance
default_agent = {agent_class_name}()
'''

# Append agent class
Read(f"{package_path}/agent.py")
Edit(
    file_path=f"{package_path}/agent.py",
    old_string="nodes = [",
    new_string=f"nodes = [\n{agent_class_code}"
)

# Finalize __init__.py exports
init_content = f'''"""
{agent_description}
"""

from .agent import {agent_class_name}, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "{agent_class_name}",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
'''

Read(f"{package_path}/__init__.py")
Edit(
    file_path=f"{package_path}/__init__.py",
    old_string='"""',
    new_string=init_content,
    replace_all=True
)

# Write README
readme_content = f'''# {agent_name.replace('_', ' ').title()}

{agent_description}

## Usage

\`\`\`bash
# Show agent info
python -m {agent_name} info

# Validate structure
python -m {agent_name} validate

# Run agent
python -m {agent_name} run --input '{{"key": "value"}}'

# Interactive shell
python -m {agent_name} shell
\`\`\`

## As Python Module

\`\`\`python
from {agent_name} import default_agent

result = await default_agent.run({{"key": "value"}})
\`\`\`

## Structure

- `agent.py` - Goal, edges, graph construction
- `nodes/__init__.py` - Node definitions
- `config.py` - Runtime configuration
- `__main__.py` - CLI interface
'''

Write(
    file_path=f"{package_path}/README.md",
    content=readme_content
)
```

**Show user:**

```
✅ Agent class written to agent.py
✅ Package exports finalized in __init__.py
✅ README.md generated

🎉 Agent complete: exports/technical_research_agent/

Commands:
  python -m technical_research_agent info
  python -m technical_research_agent validate
  python -m technical_research_agent run --input '{"topic": "..."}'
```

## CLI Template

```python
CLI_TEMPLATE = '''"""
CLI entry point for agent.
"""

import asyncio
import json
import sys
import click

from .agent import default_agent

@click.group()
@click.version_option(version="1.0.0")
def cli():
    """Agent CLI."""
    pass

@cli.command()
@click.option("--input", "-i", "input_json", type=str, required=True)
@click.option("--mock", is_flag=True, help="Run in mock mode")
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
def run(input_json, mock, quiet):
    """Execute the agent."""
    try:
        context = json.loads(input_json)
    except json.JSONDecodeError as e:
        click.echo(f"Error parsing input JSON: {e}", err=True)
        sys.exit(1)

    if not quiet:
        click.echo(f"Running agent with input: {json.dumps(context)}")

    result = asyncio.run(default_agent.run(context, mock_mode=mock))

    output_data = {
        "success": result.success,
        "steps_executed": result.steps_executed,
        "output": result.output,
    }
    if result.error:
        output_data["error"] = result.error
    if result.paused_at:
        output_data["paused_at"] = result.paused_at

    click.echo(json.dumps(output_data, indent=2, default=str))
    sys.exit(0 if result.success else 1)

@cli.command()
@click.option("--json", "output_json", is_flag=True)
def info(output_json):
    """Show agent information."""
    info_data = default_agent.info()
    if output_json:
        click.echo(json.dumps(info_data, indent=2))
    else:
        click.echo(f"Agent: {info_data['name']}")
        click.echo(f"Description: {info_data['description']}")
        click.echo(f"Nodes: {len(info_data['nodes'])}")
        click.echo(f"Edges: {len(info_data['edges'])}")

@cli.command()
def validate():
    """Validate agent structure."""
    validation = default_agent.validate()
    if validation["valid"]:
        click.echo("✓ Agent is valid")
    else:
        click.echo("✗ Agent has errors:")
        for error in validation["errors"]:
            click.echo(f"  ERROR: {error}")
    sys.exit(0 if validation["valid"] else 1)

@cli.command()
def shell():
    """Interactive agent session."""
    click.echo("Interactive mode - enter JSON input:")
    # ... implementation

if __name__ == "__main__":
    cli()
'''
```

## Testing During Build

After nodes are added:

```python
# Test individual node
python -c "
from exports.my_agent.nodes import analyze_request_node
print(analyze_request_node.id)
print(analyze_request_node.input_keys)
"

# Validate current state
PYTHONPATH=core:exports python -m my_agent validate

# Show info
PYTHONPATH=core:exports python -m my_agent info
```

## Approval Pattern

Use AskUserQuestion for all approvals:

```python
response = AskUserQuestion(
    questions=[{
        "question": "Do you approve this [component]?",
        "header": "Approve",
        "options": [
            {
                "label": "✓ Approve (Recommended)",
                "description": "Component looks good, proceed"
            },
            {
                "label": "✗ Reject & Modify",
                "description": "Need to make changes"
            },
            {
                "label": "⏸ Pause & Review",
                "description": "Need more time to review"
            }
        ],
        "multiSelect": false
    }]
)
```

## Pause/Resume Architecture

For agents needing multi-turn conversations:

1. **Pause node**: Execution stops, waits for user input
2. **Resume entry point**: Continues from pause with user's response

```python
# Example pause/resume flow
pause_nodes = ["request-clarification"]
entry_points = {
    "start": "analyze-request",
    "request-clarification_resume": "process-clarification"
}
```

## Practical Example: Hybrid Workflow

Here's how to build a node using both approaches:

```python
# 1. WRITE TO FILE FIRST (Primary - makes it visible)
node_code = '''
search_node = NodeSpec(
    id="search-web",
    node_type="llm_tool_use",
    input_keys=["query"],
    output_keys=["search_results"],
    system_prompt="Search the web for: {query}",
    tools=["web_search"],
)
'''

Edit(
    file_path="exports/research_agent/nodes/__init__.py",
    old_string="# Nodes will be added here",
    new_string=node_code
)

print("✅ Added search_node to nodes/__init__.py")
print("📁 Open exports/research_agent/nodes/__init__.py to see it!")

# 2. OPTIONALLY VALIDATE WITH MCP (Secondary - bookkeeping)
validation = mcp__agent-builder__test_node(
    node_id="search-web",
    test_input='{"query": "python tutorials"}',
    mock_llm_response='{"search_results": [...mock results...]}'
)

print(f"✓ Validation: {validation['success']}")
```

**User experience:**

- Immediately sees node in their editor (from step 1)
- Gets validation feedback (from step 2)
- Can edit the file directly if needed

This combines visibility (files) with validation (MCP tools).

## Anti-Patterns

❌ **Don't rely on `export_graph`** - Write files immediately, not at end
❌ **Don't hide code in session** - Write to files as components approved
❌ **Don't wait to write files** - Agent visible from first step
❌ **Don't batch everything** - Write incrementally

**MCP tools OK for:**
✅ `test_node` - Validate node configuration with mock inputs
✅ `validate_graph` - Check graph structure
✅ `create_session` - Track session state for bookkeeping
✅ Other validation tools

**Just don't:** Use MCP as the primary construction method or rely on export_graph

## Best Practices

✅ **Show progress** after each file write
✅ **Let user open files** during build
✅ **Write incrementally** - one component at a time
✅ **Test as you build** - validate after each addition
✅ **Keep user informed** - show file paths and diffs

## Handoff to testing-agent

When agent is complete:

```
✅ Agent complete: exports/my_agent/

Next steps:
1. Switch to testing-agent skill
2. Generate and approve tests
3. Run evaluation
4. Debug any failures

Command: "Test the agent at exports/my_agent/"
```

---

**Remember: Agent is actively constructed, visible the whole time. No hidden state. No surprise exports. Just transparent, incremental file building.**
