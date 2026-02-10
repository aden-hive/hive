"""
Minimal Manual Agent Example
----------------------------
This example demonstrates how to build and run an agent programmatically.
"""

import asyncio
from pathlib import Path

# Fix: Import Pydantic to ensure types are ready
from pydantic import BaseModel

from framework.graph import EdgeCondition, EdgeSpec, Goal, GraphSpec, NodeSpec
from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime


# 1. Define Node Logic
def greet(name: str) -> str:
    """Generate a simple greeting."""
    return f"Hello, {name}!"


def uppercase(greeting: str) -> str:
    """Convert text to uppercase."""
    return greeting.upper()


async def main():
    print("🚀 Setting up Manual Agent...")

    # 2. Define Goal
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
    # CRITICAL FIX: The "function" name and "id" must match the registration key exactly.
    node1 = NodeSpec(
        id="greeter",
        name="Greeter",
        description="Generates a simple greeting",
        node_type="function",
        function="greeter",  # ALIGNED with ID
        input_keys=["name"],
        output_keys=["greeting"],
    )

    node2 = NodeSpec(
        id="uppercaser",
        name="Uppercaser",
        description="Converts greeting to uppercase",
        node_type="function",
        function="uppercaser", # ALIGNED with ID
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

    # 6. Initialize Runtime
    runtime = Runtime(storage_path=Path("./agent_logs"))
    executor = GraphExecutor(runtime=runtime)

    # 7. Register Functions (THE FIX)
    # We register using the keys "greeter" and "uppercaser" to match the Node IDs exactly.
    executor.register_function("greeter", greet)
    executor.register_function("uppercaser", uppercase)

    # 8. Execute
    print("▶ Executing agent with input: name='Alice'...")
    result = await executor.execute(graph=graph, goal=goal, input_data={"name": "Alice"})

    # 9. Verify
    if result.success:
        print("\n✅ Success!")
        print(f"Path taken: {' -> '.join(result.path)}")
        print(f"Final output: {result.output.get('final_greeting')}")
    else:
        print(f"\n❌ Failed: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
