# Python-Only Quick Start Guide

A minimal, beginner-friendly guide to building and running your first Hive agent using **pure Python** — no Claude Code, MCP, or external APIs required.

## Who is this for?

This guide is perfect if you:
- Are new to the Hive/Aden Agent Framework
- Come from a Python or ML background
- Want to understand the core concepts before diving into advanced features
- Prefer code-first learning over CLI wizards

## What You'll Learn

1. How agents are structured (Goals, Nodes, Edges, Graphs)
2. How to define agent logic in pure Python
3. How to execute an agent and inspect the results

---

## Prerequisites

- **Python 3.11+** installed
- Basic Python knowledge

That's it! No API keys, no Claude Code, no external services.

---

## Setup (5 minutes)

```bash
# 1. Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive

# 2. Create and activate a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install the framework
cd core && pip install -e . && cd ..

# 4. Verify installation
python -c "import framework; print('✓ Framework installed successfully')"
```

---

## Your First Agent (10 minutes)

Let's build a simple agent that greets a user and converts the greeting to uppercase.

### Step 1: Understand the Core Concepts

| Concept | Description | Example |
|---------|-------------|---------|
| **Goal** | What the agent is trying to achieve | "Generate a friendly greeting" |
| **Node** | A single step in the workflow | "Greeter", "Uppercaser" |
| **Edge** | Connection between nodes | Greeter → Uppercaser |
| **Graph** | The complete workflow blueprint | All nodes + edges combined |

### Step 2: Create Your Agent

Create a file called `my_first_agent.py`:

```python
"""
My First Hive Agent
-------------------
A minimal example that runs entirely in Python with no external dependencies.
"""

import asyncio
from framework.graph import EdgeCondition, EdgeSpec, Goal, GraphSpec, NodeSpec
from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime
from pathlib import Path


# ============================================
# STEP 1: Define Your Node Functions
# ============================================
# These are simple Python functions that define what each node does.

def greet(name: str) -> str:
    """Generate a greeting for the given name."""
    return f"Hello, {name}! Welcome to Hive."


def to_uppercase(text: str) -> str:
    """Convert text to uppercase."""
    return text.upper()


# ============================================
# STEP 2: Define the Goal
# ============================================
# A Goal describes what the agent is trying to achieve.

goal = Goal(
    id="greeting-goal",
    name="Generate Greeting",
    description="Create a personalized uppercase greeting",
    success_criteria=[
        {
            "id": "greeting_created",
            "description": "A greeting was successfully generated",
            "metric": "custom",
            "target": "any",
        }
    ],
)


# ============================================
# STEP 3: Define the Nodes
# ============================================
# Each node represents a step in your agent's workflow.

greeter_node = NodeSpec(
    id="greeter",
    name="Greeter",
    description="Generates a personalized greeting",
    node_type="function",        # 'function' means it runs a Python function
    function="greet",            # Name of the function to call
    input_keys=["name"],         # Input parameters
    output_keys=["greeting"],    # Output values
)

uppercase_node = NodeSpec(
    id="uppercase",
    name="Uppercase Converter",
    description="Converts text to uppercase",
    node_type="function",
    function="to_uppercase",
    input_keys=["greeting"],     # Takes output from previous node
    output_keys=["final_result"],
)


# ============================================
# STEP 4: Define the Edges (Flow)
# ============================================
# Edges connect nodes and define the execution flow.

edge = EdgeSpec(
    id="greet-to-upper",
    source="greeter",            # From this node...
    target="uppercase",          # ...to this node
    condition=EdgeCondition.ON_SUCCESS,  # Only if the first succeeds
)


# ============================================
# STEP 5: Create the Graph
# ============================================
# The Graph combines everything into an executable workflow.

graph = GraphSpec(
    id="greeting-agent",
    goal_id="greeting-goal",
    entry_node="greeter",        # Where to start
    terminal_nodes=["uppercase"], # Where to end
    nodes=[greeter_node, uppercase_node],
    edges=[edge],
)


# ============================================
# STEP 6: Execute the Agent
# ============================================

async def run_agent():
    print("🚀 Starting My First Hive Agent...\n")
    
    # Initialize the runtime (manages state and memory)
    runtime = Runtime(storage_path=Path("./agent_output"))
    
    # Create the executor (runs the graph)
    executor = GraphExecutor(runtime=runtime)
    
    # Register our Python functions with the executor
    # The function name must match the 'function' field in NodeSpec
    executor.register_function("greeter", greet)
    executor.register_function("uppercase", to_uppercase)
    
    # Run the agent with input data
    input_data = {"name": "Alice"}
    print(f"📥 Input: {input_data}\n")
    
    result = await executor.execute(
        graph=graph,
        goal=goal,
        input_data=input_data
    )
    
    # Display results
    print("=" * 50)
    if result.success:
        print("✅ Agent completed successfully!")
        print(f"📍 Execution path: {' → '.join(result.path)}")
        print(f"📤 Output: {result.output}")
    else:
        print(f"❌ Agent failed: {result.error}")
    print("=" * 50)


# Run the agent
if __name__ == "__main__":
    asyncio.run(run_agent())
```

### Step 3: Run Your Agent

```bash
PYTHONPATH=core python my_first_agent.py
```

**Expected Output:**
```
🚀 Starting My First Hive Agent...

📥 Input: {'name': 'Alice'}

==================================================
✅ Agent completed successfully!
📍 Execution path: greeter → uppercase
📤 Output: {'final_result': 'HELLO, ALICE! WELCOME TO HIVE.'}
==================================================
```

---

## Understanding the Flow

```
┌─────────────────────────────────────────────────────────────┐
│                        AGENT FLOW                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   Input: {"name": "Alice"}                                  │
│              │                                              │
│              ▼                                              │
│   ┌─────────────────────┐                                   │
│   │     GREETER NODE    │                                   │
│   │  greet("Alice")     │ → "Hello, Alice! Welcome to Hive."│
│   └─────────────────────┘                                   │
│              │                                              │
│              ▼ (ON_SUCCESS)                                 │
│   ┌─────────────────────┐                                   │
│   │   UPPERCASE NODE    │                                   │
│   │  to_uppercase(...)  │ → "HELLO, ALICE! WELCOME TO HIVE."│
│   └─────────────────────┘                                   │
│              │                                              │
│              ▼                                              │
│   Output: {"final_result": "HELLO, ALICE!..."}              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Takeaways

1. **Agents are graphs** — A series of connected nodes that execute in order
2. **Nodes are steps** — Each node performs a specific task (Python function, LLM call, etc.)
3. **Edges control flow** — Define how execution moves between nodes
4. **Goals define success** — What the agent is trying to achieve

---

## Next Steps

Now that you understand the basics, you can:

| Next Step | Description | Link |
|-----------|-------------|------|
| **Add more nodes** | Build more complex workflows | See `core/examples/` |
| **Use LLM nodes** | Add AI-powered reasoning | [ENVIRONMENT_SETUP.md](../ENVIRONMENT_SETUP.md) |
| **Try Claude Code** | Use interactive skills to build agents | [getting-started.md](getting-started.md) |
| **Add tools** | Give your agent capabilities (web search, file access) | [tools/README.md](../tools/README.md) |

---

## Running the Built-in Example

The framework includes a similar example you can run immediately:

```bash
# View the example
cat core/examples/manual_agent.py

# Run it
PYTHONPATH=core python core/examples/manual_agent.py
```

---

## FAQ

### Q: Do I need an API key?
**A:** No! This guide uses `function` nodes that run pure Python code. API keys are only needed for LLM-powered nodes.

### Q: What is Claude Code?
**A:** Claude Code is an optional CLI tool that provides interactive skills for building agents. You can explore it later — it's not required for this quick start.

### Q: What is MCP?
**A:** MCP (Model Context Protocol) is a standard for connecting AI models to tools. Hive includes MCP tools, but they're optional for basic agents.

### Q: Can I use this in production?
**A:** Yes! Function-based agents are lightweight and fast. For complex reasoning tasks, you'll want to add LLM nodes later.

---

## Getting Help

- **Documentation:** [docs/](.)
- **Examples:** [core/examples/](../core/examples/)
- **Issues:** [GitHub Issues](https://github.com/adenhq/hive/issues)
- **Discord:** [Join Community](https://discord.com/invite/MXE49hrKDk)
