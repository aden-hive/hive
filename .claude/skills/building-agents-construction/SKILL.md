---
name: building-agents-construction
description: Step-by-step guide for building goal-driven agents. Creates package structure, defines goals, adds nodes, connects edges, and finalizes agent class. Use when actively building an agent.
license: Apache-2.0
metadata:
  author: hive
  version: "1.0"
  type: procedural
  part_of: building-agents
  requires: building-agents-core
---

# Building Agents - Construction Process

Step-by-step guide for building goal-driven agent packages.

**Prerequisites:** Read `building-agents-core` for fundamental concepts.

## CRITICAL: entry_points Format Reference

**⚠️ Common Mistake Prevention:**

The `entry_points` parameter in GraphSpec has a specific format that is easy to get wrong. This section exists because this mistake has caused production bugs.

### Correct Format

```python
entry_points = {"start": "first-node-id"}
```

**Examples from working agents:**

```python
# From exports/outbound_sales_agent/agent.py
entry_node = "lead-qualification"
entry_points = {"start": "lead-qualification"}

# From exports/support_ticket_agent/agent.py (FIXED)
entry_node = "parse-ticket"
entry_points = {"start": "parse-ticket"}
```

### WRONG Formats (DO NOT USE)

```python
# ❌ WRONG: Using node ID as key with input keys as value
entry_points = {
    "parse-ticket": ["ticket_content", "customer_id", "ticket_id"]
}
# Error: ValidationError: Input should be a valid string, got list

# ❌ WRONG: Using set instead of dict
entry_points = {"parse-ticket"}
# Error: ValidationError: Input should be a valid dictionary, got set

# ❌ WRONG: Missing "start" key
entry_points = {"entry": "parse-ticket"}
# Error: Graph execution fails, cannot find entry point
```

### Validation Check

After writing graph configuration, ALWAYS validate:

```python
# Check 1: Must be a dict
assert isinstance(entry_points, dict), f"entry_points must be dict, got {type(entry_points)}"

# Check 2: Must have "start" key
assert "start" in entry_points, f"entry_points must have 'start' key, got keys: {entry_points.keys()}"

# Check 3: "start" value must match entry_node
assert entry_points["start"] == entry_node, f"entry_points['start']={entry_points['start']} must match entry_node={entry_node}"

# Check 4: Value must be a string (node ID)
assert isinstance(entry_points["start"], str), f"entry_points['start'] must be string, got {type(entry_points['start'])}"
```

**Why this matters:** GraphSpec uses Pydantic validation. The wrong format causes ValidationError at runtime, which blocks all agent execution and tests. This bug is not caught until you try to run the agent.

## LLM Provider Configuration

**Default:** All agents use **LiteLLM** with **Cerebras** as the primary provider for cost-effective, high-performance inference.

### Environment Setup

Set your Cerebras API key:
```bash
export CEREBRAS_API_KEY="your-api-key-here"
```

Or configure via aden_tools credentials:
```bash
# Store credential
aden credentials set cerebras YOUR_API_KEY
```

### Model Configuration

Default model in [config.py](config.py):
```python
model: str = "cerebras/zai-glm-4.7"  # Fast, cost-effective
```

### Supported Providers via LiteLLM

The framework uses LiteLLM, which supports multiple providers. Priority order:
1. **Cerebras** (default) - `cerebras/zai-glm-4.7`
2. **OpenAI** - `gpt-4o-mini`, `gpt-4o`
3. **Anthropic** - `claude-haiku-4-5-20251001`, `claude-sonnet-4-5-20250929`
4. **Local** - `ollama/llama3`

To use a different provider, change the model in [config.py](config.py) and ensure the corresponding API key is available:
- Cerebras: `CEREBRAS_API_KEY` or `aden credentials set cerebras`
- OpenAI: `OPENAI_API_KEY` or `aden credentials set openai`
- Anthropic: `ANTHROPIC_API_KEY` or `aden credentials set anthropic`

## Building Session Management with MCP

**MANDATORY**: Use the agent-builder MCP server's BuildSession system for automatic bookkeeping and persistence.

### Available MCP Session Tools

```python
# Create new session (call FIRST before building)
mcp__agent-builder__create_session(name="Support Ticket Agent")
# Returns: session_id, automatically sets as active session

# Get current session status (use for progress tracking)
status = mcp__agent-builder__get_session_status()
# Returns: {
#   "session_id": "build_20250122_...",
#   "name": "Support Ticket Agent",
#   "has_goal": true,
#   "node_count": 5,
#   "edge_count": 7,
#   "nodes": ["parse-ticket", "categorize", ...],
#   "edges": [("parse-ticket", "categorize"), ...]
# }

# List all saved sessions
mcp__agent-builder__list_sessions()

# Load previous session
mcp__agent-builder__load_session_by_id(session_id="build_...")

# Delete session
mcp__agent-builder__delete_session(session_id="build_...")
```

### How MCP Session Works

The BuildSession class (in `core/framework/mcp/agent_builder_server.py`) automatically:
- **Persists to disk** after every operation (`_save_session()` called automatically)
- **Tracks all components**: goal, nodes, edges, mcp_servers
- **Maintains timestamps**: created_at, last_modified
- **Stores to**: `~/.claude-code-agent-builder/sessions/`

When you call MCP tools like:
- `mcp__agent-builder__set_goal(...)` - Automatically added to session.goal and saved
- `mcp__agent-builder__add_node(...)` - Automatically added to session.nodes and saved
- `mcp__agent-builder__add_edge(...)` - Automatically added to session.edges and saved

**No manual bookkeeping needed** - the MCP server handles it all!

### Show Progress to User

```python
# Get session status to show progress
status = json.loads(mcp__agent-builder__get_session_status())

print(f"\n📊 Building Progress:")
print(f"   Session: {status['name']}")
print(f"   Goal defined: {status['has_goal']}")
print(f"   Nodes: {status['node_count']}")
print(f"   Edges: {status['edge_count']}")
print(f"   Nodes added: {', '.join(status['nodes'])}")
```

**Benefits:**
- Automatic persistence - survive crashes/restarts
- Clear audit trail - all operations logged
- Session resume - continue from where you left off
- Progress tracking built-in
- No manual state management needed

## Step-by-Step Guide

### Step 1: Create Building Session & Package Structure

When user requests an agent, **immediately create MCP session and package**:

```python
# 0. FIRST: Create MCP building session
agent_name = "technical_research_agent"  # snake_case
session_result = mcp__agent-builder__create_session(name=agent_name.replace('_', ' ').title())
session_id = json.loads(session_result)["session_id"]
print(f"✅ Created building session: {session_id}")

# 1. Create directory
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
from framework.llm.litellm import LiteLLMProvider
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
    model: str = "cerebras/zai-glm-4.7"
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
        # 3-5 success criteria total
    ],
    constraints=[
        Constraint(
            id="{c.id}",
            description="{c.description}",
            constraint_type="{c.constraint_type}",
            category="{c.category}",
        ),
        # 1-5 constraints total
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

**Note:** Goal is automatically tracked in MCP session. Use `mcp__agent-builder__get_session_status()` to check progress.

### Step 3: Add Nodes (Incremental)

**⚠️ CRITICAL VALIDATION REQUIREMENTS:**

Before adding any node with tools:
1. Call `mcp__agent-builder__list_mcp_tools()` to discover available tools
2. Verify each tool exists in the response
3. If a tool doesn't exist, inform the user and ask how to proceed

After writing each node:
4. **MANDATORY**: Validate with `mcp__agent-builder__test_node()` before proceeding
5. **MANDATORY**: Check MCP session status to track progress
6. Only proceed to next node after validation passes

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

    # OPTIONAL: Add schemas for OutputCleaner validation (recommended for critical paths)
    # input_schema={{
    #     "field_name": {{"type": "string", "required": True, "description": "Field description"}},
    # }},
    # output_schema={{
    #     "result": {{"type": "dict", "required": True, "description": "Analysis result"}},
    # }},
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

#### MANDATORY: Validate Each Node with MCP Tools

After writing EVERY node, you MUST validate before proceeding:

```python
# Node is already written to file. Now VALIDATE IT (REQUIRED):
validation_result = json.loads(mcp__agent-builder__test_node(
    node_id="analyze-request",
    test_input='{"query": "test query"}',
    mock_llm_response='{"analysis": "mock output"}'
))

# Check validation result
if validation_result["valid"]:
    # Show user validation passed
    print(f"✅ Node validation passed: analyze-request")

    # Show session progress
    status = json.loads(mcp__agent-builder__get_session_status())
    print(f"📊 Session progress: {status['node_count']} nodes added")
else:
    # STOP - Do not proceed until fixed
    print(f"❌ Node validation FAILED:")
    for error in validation_result["errors"]:
        print(f"   - {error}")
    print("⚠️ Must fix node before proceeding to next component")
    # Ask user how to proceed
```

**CRITICAL:** Do NOT proceed to the next node until validation passes. Bugs caught here prevent wasted work later.

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
# ⚠️ CRITICAL: entry_points format must be {"start": "node_id"}
# Common mistake: {"node_id": ["input_keys"]} is WRONG
# Correct format: {"start": "first-node-id"}
# Reference: See exports/outbound_sales_agent/agent.py for example

graph_config = f'''
# Graph configuration
entry_node = "{entry_node_id}"
entry_points = {{"start": "{entry_node_id}"}}  # CRITICAL: Must be {{"start": "node-id"}}
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

#### MANDATORY: Validate Graph Structure

After writing edges, you MUST validate before proceeding to finalization:

```python
# Edges already written to agent.py. Now VALIDATE STRUCTURE (REQUIRED):
graph_validation = json.loads(mcp__agent-builder__validate_graph())

# Check for structural issues
if graph_validation["valid"]:
    print("✅ Graph structure validated successfully")

    # Show session summary
    status = json.loads(mcp__agent-builder__get_session_status())
    print(f"   - Nodes: {status['node_count']}")
    print(f"   - Edges: {status['edge_count']}")
    print(f"   - Entry point: {entry_node_id}")
else:
    print("❌ Graph validation FAILED:")
    for error in graph_validation["errors"]:
        print(f"   ERROR: {error}")
    print("\n⚠️ Must fix graph structure before finalizing agent")
    # Ask user how to proceed

# Additional validation: Check entry_points format
if not isinstance(entry_points, dict):
    print("❌ CRITICAL ERROR: entry_points must be a dict")
    print(f"   Current value: {entry_points} (type: {type(entry_points)})")
    print("   Correct format: {'start': 'node-id'}")
    # STOP - This is the mistake that caused the support_ticket_agent bug

if entry_points.get("start") != entry_node_id:
    print("❌ CRITICAL ERROR: entry_points['start'] must match entry_node")
    print(f"   entry_points: {entry_points}")
    print(f"   entry_node: {entry_node_id}")
    print("   They must be consistent!")
```

**CRITICAL:** Do NOT proceed to Step 5 (finalization) until graph validation passes. This checkpoint prevents structural bugs from reaching production.

### Step 5: Finalize Agent Class

**Pre-flight checks before finalization:**

```python
# MANDATORY: Verify all validations passed before finalizing
print("\n🔍 Pre-finalization Checklist:")

# Get current session status
status = json.loads(mcp__agent-builder__get_session_status())

checks_passed = True

# Check 1: Goal defined
if not status["has_goal"]:
    print("❌ No goal defined")
    checks_passed = False
else:
    print(f"✅ Goal defined: {status['goal_name']}")

# Check 2: Nodes added
if status["node_count"] == 0:
    print("❌ No nodes added")
    checks_passed = False
else:
    print(f"✅ {status['node_count']} nodes added: {', '.join(status['nodes'])}")

# Check 3: Edges added
if status["edge_count"] == 0:
    print("❌ No edges added")
    checks_passed = False
else:
    print(f"✅ {status['edge_count']} edges added")

# Check 4: Entry points format correct
if not isinstance(entry_points, dict) or "start" not in entry_points:
    print("❌ CRITICAL: entry_points format incorrect")
    print(f"   Current: {entry_points}")
    print("   Required: {'start': 'node-id'}")
    checks_passed = False
else:
    print(f"✅ Entry points valid: {entry_points}")

if not checks_passed:
    print("\n⚠️ CANNOT PROCEED to finalization until all checks pass")
    print("   Fix the issues above first")
    # Ask user how to proceed or stop here
    return

print("\n✅ All pre-flight checks passed - proceeding to finalization\n")
```

Write the agent class:

````python
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
            # Try Cerebras first, fall back to other providers
            if creds.is_available("cerebras"):
                api_key = creds.get("cerebras")
                llm = LiteLLMProvider(api_key=api_key, model=self.config.model)
            elif creds.is_available("openai"):
                api_key = creds.get("openai")
                llm = LiteLLMProvider(api_key=api_key, model=self.config.model)
            elif creds.is_available("anthropic"):
                api_key = creds.get("anthropic")
                llm = LiteLLMProvider(api_key=api_key, model=self.config.model)

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

```bash
# Show agent info
python -m {agent_name} info

# Validate structure
python -m {agent_name} validate

# Run agent
python -m {agent_name} run --input '{{"key": "value"}}'

# Interactive shell
python -m {agent_name} shell
````

## As Python Module

```python
from {agent_name} import default_agent

result = await default_agent.run({{"key": "value"}})
```

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

**Final session summary:**

```python
# Show final MCP session status
status = json.loads(mcp__agent-builder__get_session_status())

print("\n📊 Build Session Summary:")
print(f"   Session ID: {status['session_id']}")
print(f"   Agent: {status['name']}")
print(f"   Goal: {status['goal_name']}")
print(f"   Nodes: {status['node_count']}")
print(f"   Edges: {status['edge_count']}")
print(f"   MCP Servers: {status['mcp_servers_count']}")
print("\n✅ Agent construction complete with full validation")
print(f"\nSession saved to: ~/.claude-code-agent-builder/sessions/{status['session_id']}.json")
````

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
````

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

## Framework Features

### OutputCleaner - Automatic I/O Validation and Cleaning

**NEW FEATURE**: The framework automatically validates and cleans node outputs between edges using a fast LLM (Cerebras llama-3.3-70b).

**What it does**:
- ✅ Validates output matches next node's input schema
- ✅ Detects JSON parsing trap (entire response in one key)
- ✅ Cleans malformed output automatically (~200-500ms, ~$0.001 per cleaning)
- ✅ Boosts success rates by 1.8-2.2x
- ✅ **Enabled by default** - no code changes needed!

**How to leverage it**:

Add `input_schema` and `output_schema` to critical nodes for better validation:

```python
critical_node = NodeSpec(
    id="approval-decision",
    name="Approval Decision",
    node_type="llm_generate",
    input_keys=["analysis", "risk_score"],
    output_keys=["decision", "reason"],

    # Schemas enable OutputCleaner to validate and clean better
    input_schema={
        "analysis": {
            "type": "dict",
            "required": True,
            "description": "Contract analysis with findings"
        },
        "risk_score": {
            "type": "number",
            "required": True,
            "description": "Risk score 0-10"
        },
    },
    output_schema={
        "decision": {
            "type": "string",
            "required": True,
            "description": "Approval decision: APPROVED, REJECTED, or ESCALATE"
        },
        "reason": {
            "type": "string",
            "required": True,
            "description": "Justification for the decision"
        },
    },

    system_prompt="""...""",
)
```

**Supported schema types**:
- `"string"` or `"str"` - String values
- `"int"` or `"integer"` - Integer numbers
- `"float"` - Float numbers
- `"number"` - Int or float
- `"bool"` or `"boolean"` - Boolean values
- `"dict"` or `"object"` - Dictionary/object
- `"list"` or `"array"` - List/array
- `"any"` - Any type (no validation)

**When to add schemas**:
- ✅ Critical paths where failure cascades
- ✅ Expensive nodes where retry is costly
- ✅ Nodes with strict output requirements
- ✅ Nodes that frequently produce malformed output

**When to skip schemas**:
- ❌ Simple pass-through nodes
- ❌ Terminal nodes (no next node to affect)
- ❌ Fast local operations
- ❌ Nodes with robust error handling

**Monitoring**: Check logs for cleaning events:
```
⚠ Output validation failed for analyze → recommend: 1 error(s)
🧹 Cleaning output from 'analyze' using cerebras/llama-3.3-70b
✓ Output cleaned successfully
```

If you see frequent cleanings on the same edge:
1. Review the source node's system prompt
2. Add explicit JSON formatting instructions
3. Consider improving output structure

### System Prompt Best Practices

**For nodes with multiple output_keys, ALWAYS enforce JSON**:

```python
system_prompt="""You are a contract analyzer.

CRITICAL: Return ONLY raw JSON. NO markdown, NO code blocks, NO ```json```.
Just the JSON object starting with { and ending with }.

Return ONLY this JSON structure:
{
  "analysis": {...},
  "risk_score": 7.5,
  "compliance_issues": [...]
}

Do NOT include any explanatory text before or after the JSON.
"""
```

**Why this matters**:
- LLMs often wrap JSON in markdown (` ```json\n{...}\n``` `)
- LLMs add explanations before/after JSON
- Without explicit instructions, output may be malformed
- OutputCleaner can fix these, but better to prevent them

## Next Steps

After completing construction:

**If agent structure complete:**

- Validate: `python -m agent_name validate`
- Test basic execution: `python -m agent_name info`
- Proceed to testing-agent skill for comprehensive tests

**If implementation needed:**

- Check for STATUS.md or IMPLEMENTATION_GUIDE.md in agent directory
- May need Python functions or MCP tool integration

## Related Skills

- **building-agents-core** - Fundamental concepts
- **building-agents-patterns** - Best practices and examples
- **testing-agent** - Test and validate completed agents
- **agent-workflow** - Complete workflow orchestrator
