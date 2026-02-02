"""
Minimal Manual Agent Example
----------------------------
This example demonstrates how to build and run an agent programmatically
without using the Claude Code CLI or external LLM APIs.

It uses 'function' nodes to define logic in pure Python, making it perfect
for understanding the core runtime loop:
Setup -> Graph definition -> Execution -> Result

Run with:
    PYTHONPATH=core python core/examples/manual_agent.py
"""

import asyncio
from pathlib import Path

from framework.graph import (
    EdgeCondition,
    EdgeSpec,
    Goal,
    GraphSpec,
    NodeSpec,
)
from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime


def safe_print(text: str):
    """Print text safely on Windows terminals that may not support emojis."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode())


# 1. Define Node Logic (Pure Python Functions)
def greet(name: str) -> str:
    return f"Hello, {name}!"


def uppercase(greeting: str) -> str:
    return greeting.upper()


async def main():
    safe_print("🚀 Setting up Manual Agent...")

    # 2. Define the Goal
    goal = Goal(
        id="greet-user",
        name="Greet User",
        description="Generate a friendly uppercase greeting",
        success_criteria=[
            {
                "id": "greeting_generated",
                "description": "Greeting produced",
                "metric": "custom",
                "target": "any",
            }
        ],
    )

    # 3. Define Nodes
    node1 = NodeSpec(
        id="greeter",
        name="Greeter",
        description="Generates a simple greeting",
        node_type="function",
        function="greet",
        input_keys=["name"],
        output_keys=["greeting"],
    )

    node2 = NodeSpec(
        id="uppercaser",
        name="Uppercaser",
        description="Converts greeting to uppercase",
        node_type="function",
        function="uppercase",
        input_keys=["greeting"],
        output_keys=["final_greeting"],
    )

    # 4. Define Edges
    edge1 = EdgeSpec(
        id="greet-to-upper",
        source="greeter",
        target="uppercaser",
        condition=EdgeCondition.ON_SUCCESS,
    )

    # 5. Create Graph
    graph = GraphSpec(
        id="greeting-agent",
        goal_id="greet-user",
        entry_node="greeter",
        terminal_nodes=["uppercaser"],
        nodes=[node1, node2],
        edges=[edge1],
    )

    # 6. Initialize Runtime & Executor
    runtime = Runtime(storage_path=Path("./agent_logs"))
    executor = GraphExecutor(runtime=runtime)

    # 7. Register Function Implementations
    executor.register_function("greeter", greet)
    executor.register_function("uppercaser", uppercase)

    # 8. Execute Agent
    safe_print("▶ Executing agent with input: name='Alice'...")

    result = await executor.execute(
        graph=graph,
        goal=goal,
        input_data={"name": "Alice"},
    )

    # 9. Verify Results
    if result.success:
        safe_print("✅ Success!")
        safe_print("Path taken: greeter -> uppercaser")
        safe_print(f"Final output: {result.output.get('final_greeting')}")
    else:
        safe_print(f"❌ Failed: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
