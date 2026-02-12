"""
Manual Agent Example with Proper HITL (Using Aden GraphExecutor)
"""

import asyncio
from pathlib import Path
import sys

# Ensure local 'framework' package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from framework.graph import EdgeCondition, EdgeSpec, Goal, GraphSpec, NodeSpec
from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime


# -------------------------------------------------
# 1️⃣ Function Nodes (MUST use **kwargs)
# -------------------------------------------------
def greet(**kwargs):
    name = kwargs.get("name")
    return f"Hello, {name}!"


def uppercase(**kwargs):
    greeting = str(kwargs.get("greeting"))
    return greeting.upper()


def approval(**kwargs):
    # Pass-through so final_greeting stays in memory
    return {"final_greeting": kwargs.get("final_greeting")}


def finalize(**kwargs):
    final_greeting = str(kwargs.get("final_greeting"))
    approval_value = str(kwargs.get("approval"))

    if approval_value.lower() != "yes":
        return "Greeting rejected by human."

    return final_greeting


# -------------------------------------------------
# 2️⃣ Main
# -------------------------------------------------
async def main():
    print("🚀 Setting up Manual Agent with Proper HITL...")

    goal = Goal(
        id="greet-user",
        name="Greet User with Approval",
        description="Generate greeting and confirm with human",
        success_criteria=[
            {
                "id": "approved",
                "description": "Greeting approved",
                "metric": "custom",
                "target": "any",
            }
        ],  # type: ignore
    )

    # ----------------------------
    # Node Definitions
    # ----------------------------
    node1 = NodeSpec(
        id="greeter",
        name="Greeter",
        description="Generate greeting",
        node_type="function",
        function="greet",
        input_keys=["name"],
        output_keys=["greeting"],
    )

    node2 = NodeSpec(
        id="uppercaser",
        name="Uppercaser",
        description="Uppercase greeting",
        node_type="function",
        function="uppercase",
        input_keys=["greeting"],
        output_keys=["final_greeting"],
    )

    node3 = NodeSpec(
        id="approval",
        name="Approval",
        description="Human approval step",
        node_type="function",
        function="approval",
        input_keys=["final_greeting"],
        output_keys=["final_greeting"],
    )

    node4 = NodeSpec(
        id="finalize",
        name="Finalize",
        description="Finalize greeting",
        node_type="function",
        function="finalize",
        input_keys=["final_greeting", "approval"],
        output_keys=["result"],
    )

    # ----------------------------
    # Edges
    # ----------------------------
    edge1 = EdgeSpec(
        id="greet-to-upper",
        source="greeter",
        target="uppercaser",
        condition=EdgeCondition.ON_SUCCESS,
    )

    edge2 = EdgeSpec(
        id="upper-to-approval",
        source="uppercaser",
        target="approval",
        condition=EdgeCondition.ON_SUCCESS,
    )

    edge3 = EdgeSpec(
        id="approval-to-final",
        source="approval",
        target="finalize",
        condition=EdgeCondition.ON_SUCCESS,
    )

    # ----------------------------
    # Graph (Pause Enabled)
    # ----------------------------
    graph = GraphSpec(
        id="greeting-agent-hitl",
        goal_id="greet-user",
        entry_node="greeter",
        terminal_nodes=["finalize"],
        nodes=[node1, node2, node3, node4],
        edges=[edge1, edge2, edge3],
        pause_nodes=["approval"],  # 🔥 HITL pause here
    )

    runtime = Runtime(storage_path=Path("./agent_logs"))
    executor = GraphExecutor(runtime=runtime)

    # Register function nodes
    executor.register_function("greeter", greet)
    executor.register_function("uppercaser", uppercase)
    executor.register_function("approval", approval)
    executor.register_function("finalize", finalize)

    print("▶ Executing agent with input:...")

    person_name = input("Enter the name of person: ").strip()
    # First execution
    result = await executor.execute(
        graph=graph,
        goal=goal,
        input_data={"name": person_name},
    )

    # -------------------------------------------------
    # Proper HITL Pause Handling
    # -------------------------------------------------
    print(result)
    if result.paused_at:
        print(f"\n⏸ Paused at node: {result.path}")

        final_greeting = result.output.get("final_greeting")
        print(f"\nGenerated Greeting:\n{final_greeting}")

        human_input = input("\nApprove this greeting? (yes/no): ").strip()

        # Inject human input into saved memory
        result.session_state["memory"]["approval"] = human_input

        result.session_state["memory"]["path"] = result.path

        # 🔥 CRITICAL: tell executor where to continue
        result.session_state["next_node"] = "finalize"

        # Resume execution
        result = await executor.execute(
            graph=graph,
            goal=goal,
            session_state=result.session_state,
        )

        if str(result.session_state["memory"]["approval"]).lower() == "yes":
            result.session_state['result'] = final_greeting["final_greeting"] # type: ignore
        else:
            result.session_state['result'] = greet(name = person_name)


    # -------------------------------------------------
    # Final Result
    # -------------------------------------------------
    if result.success:
        print("\n✅ Success!")
        print(f"Path taken: {' -> '.join(result.session_state['memory']['path'])}")
        print(f"Final Output: {result.session_state['result']}")
    else:
        print(f"\n❌ Failed: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())