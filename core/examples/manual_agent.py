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

from framework.graph import EdgeCondition, EdgeSpec, Goal, GraphSpec, NodeSpec
from framework.graph.executor import GraphExecutor
from framework.runtime.console import configure_console_output
from framework.runtime.core import Runtime


# 1. Define Node Logic (Pure Python Functions)
def greet(name: str, style: str = "upper") -> dict[str, str]:
    """Generate a simple greeting and pass through the style."""
    return {"greeting": f"Hello, {name}!", "style": style}


def stylize(greeting: str, style: str = "upper") -> str:
    """Apply a simple style transform to a greeting."""
    style = (style or "").strip().lower()
    if style in {"upper", "uppercase"}:
        return greeting.upper()
    if style in {"lower", "lowercase"}:
        return greeting.lower()
    if style in {"title", "titlecase"}:
        return greeting.title()
    if style in {"reverse", "reversed"}:
        return greeting[::-1]
    if style in {"spaced", "space"}:
        return " ".join(list(greeting))
    return greeting


async def main():
    configure_console_output()
    print("🚀 Setting up Manual Agent...")

    # 2. Define the Goal
    # Every agent needs a goal with success criteria
    goal = Goal(
        id="greet-user",
        name="Greet User",
        description="Generate a friendly greeting with a selectable style",
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
    # Nodes describe steps in the process
    node1 = NodeSpec(
        id="greeter",
        name="Greeter",
        description="Generates a simple greeting and forwards style",
        node_type="function",
        function="greet",  # Matches the registered function name
        input_keys=["name", "style"],
        output_keys=["greeting", "style"],
    )

    node2 = NodeSpec(
        id="stylizer",
        name="Stylizer",
        description="Transforms greeting based on style input",
        node_type="function",
        function="stylize",
        input_keys=["greeting", "style"],
        output_keys=["final_greeting"],
    )

    # 4. Define Edges
    # Edges define the flow between nodes
    edge1 = EdgeSpec(
        id="greet-to-style",
        source="greeter",
        target="stylizer",
        condition=EdgeCondition.ON_SUCCESS,
    )

    # 5. Create Graph
    # The graph works like a blueprint connecting nodes and edges
    graph = GraphSpec(
        id="greeting-agent",
        goal_id="greet-user",
        entry_node="greeter",
        terminal_nodes=["stylizer"],
        nodes=[node1, node2],
        edges=[edge1],
    )

    # 6. Initialize Runtime & Executor
    # Runtime handles state/memory; Executor runs the graph
    from pathlib import Path

    runtime = Runtime(storage_path=Path("./agent_logs"))
    executor = GraphExecutor(runtime=runtime)

    # 7. Register Function Implementations
    # Connect string names in NodeSpecs to actual Python functions
    executor.register_function("greeter", greet)
    executor.register_function("stylizer", stylize)

    # 8. Execute Agent
    print("▶ Executing agent with input: name='Alice'...")

    style = "reverse"
    print(f"Style: {style}")

    result = await executor.execute(
        graph=graph,
        goal=goal,
        input_data={"name": "Alice", "style": style},
    )

    # 9. Verify Results
    if result.success:
        print("\n✅ Success!")
        print(f"Path taken: {' -> '.join(result.path)}")
        print(f"Final output: {result.output.get('final_greeting')}")
    else:
        print(f"\n❌ Failed: {result.error}")


if __name__ == "__main__":
    # Optional: Enable logging to see internal decision flow
    # logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
