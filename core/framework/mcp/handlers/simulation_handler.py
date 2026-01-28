"""
Graph and node simulation MCP tools.

Handles testing individual nodes and simulating complete graph execution
without making actual LLM calls.
"""

import json
from typing import Annotated

from framework.mcp.session import get_session


def register(mcp):
    """Register simulation tools on the MCP server."""

    @mcp.tool()
    def test_node(
        node_id: Annotated[str, "ID of the node to test"],
        test_input: Annotated[str, "JSON object with test input data for the node"],
        mock_llm_response: Annotated[
            str, "Mock LLM response to simulate (for testing without API calls)"
        ] = "",
    ) -> str:
        """
        Test a single node with sample inputs. Use this during HITL approval to show
        humans what the node actually does before they approve it.

        Returns the node's execution result including outputs and any errors.
        """
        session = get_session()

        # Find the node
        node_spec = None
        for n in session.nodes:
            if n.id == node_id:
                node_spec = n
                break

        if node_spec is None:
            return json.dumps({"success": False, "error": f"Node '{node_id}' not found"})

        # Parse test input
        try:
            input_data = json.loads(test_input)
        except json.JSONDecodeError as e:
            return json.dumps({"success": False, "error": f"Invalid JSON input: {e}"})

        # Build a test result showing what WOULD happen
        result = {
            "node_id": node_id,
            "node_type": node_spec.node_type,
            "test_input": input_data,
            "input_keys_read": node_spec.input_keys,
            "output_keys_written": node_spec.output_keys,
        }

        # Simulate based on node type
        if node_spec.node_type == "router":
            result["routing_options"] = node_spec.routes
            result["simulation"] = (
                "Router would evaluate routes based on input and select target node"
            )

        elif node_spec.node_type in ("llm_generate", "llm_tool_use"):
            result["system_prompt"] = node_spec.system_prompt
            result["available_tools"] = node_spec.tools

            if mock_llm_response:
                result["mock_response"] = mock_llm_response
                result["simulation"] = "LLM would receive prompt and produce response"
            else:
                result["simulation"] = "LLM would be called with the system prompt and input data"

        elif node_spec.node_type == "function":
            result["simulation"] = "Function node would execute deterministic logic"

        # Show memory state after (simulated)
        result["expected_memory_state"] = {
            "inputs_available": {
                k: input_data.get(k, "<not provided>") for k in node_spec.input_keys
            },
            "outputs_to_write": node_spec.output_keys,
        }

        return json.dumps(
            {
                "success": True,
                "test_result": result,
                "recommendation": (
                    "Review the simulation above. Does this node behavior match your intent?"
                ),
            },
            indent=2,
        )

    @mcp.tool()
    def test_graph(
        test_input: Annotated[str, "JSON object with initial input data for the graph"],
        max_steps: Annotated[int, "Maximum steps to execute (default 10)"] = 10,
        dry_run: Annotated[bool, "If true, simulate without actual LLM calls"] = True,
    ) -> str:
        """
        Test the complete agent graph with sample inputs. Use this during final approval
        to show humans the full execution flow before they approve the agent.

        In dry_run mode, simulates the execution path without making actual LLM calls.
        """
        from framework.mcp.validation.validators import validate_graph

        session = get_session()

        if not session.goal:
            return json.dumps({"success": False, "error": "No goal defined"})

        if not session.nodes:
            return json.dumps({"success": False, "error": "No nodes defined"})

        # Validate graph first
        validation = json.loads(validate_graph())
        if not validation["valid"]:
            return json.dumps(
                {
                    "success": False,
                    "error": "Graph is not valid",
                    "validation_errors": validation["errors"],
                }
            )

        # Parse test input
        try:
            input_data = json.loads(test_input)
        except json.JSONDecodeError as e:
            return json.dumps({"success": False, "error": f"Invalid JSON input: {e}"})

        # Simulate execution path
        entry_node = validation["entry_node"]
        terminal_nodes = validation["terminal_nodes"]

        execution_trace = []
        current_node_id = entry_node
        steps = 0

        while steps < max_steps:
            steps += 1

            # Find current node
            current_node = None
            for n in session.nodes:
                if n.id == current_node_id:
                    current_node = n
                    break

            if current_node is None:
                execution_trace.append(
                    {
                        "step": steps,
                        "error": f"Node '{current_node_id}' not found",
                    }
                )
                break

            # Record this step
            step_info = {
                "step": steps,
                "node_id": current_node_id,
                "node_name": current_node.name,
                "node_type": current_node.node_type,
                "reads": current_node.input_keys,
                "writes": current_node.output_keys,
            }

            if current_node.node_type in ("llm_generate", "llm_tool_use"):
                step_info["prompt_preview"] = (
                    current_node.system_prompt[:200] + "..."
                    if current_node.system_prompt and len(current_node.system_prompt) > 200
                    else current_node.system_prompt
                )
                step_info["tools_available"] = current_node.tools

            execution_trace.append(step_info)

            # Check if terminal
            if current_node_id in terminal_nodes:
                step_info["is_terminal"] = True
                break

            # Find next node via edges
            next_node = None
            for edge in session.edges:
                if edge.source == current_node_id:
                    if edge.condition.value in ("always", "on_success"):
                        next_node = edge.target
                        step_info["next_node"] = next_node
                        step_info["edge_condition"] = edge.condition.value
                        break

            if next_node is None:
                step_info["note"] = "No outgoing edge found (end of path)"
                break

            current_node_id = next_node

        return json.dumps(
            {
                "success": True,
                "dry_run": dry_run,
                "test_input": input_data,
                "execution_trace": execution_trace,
                "steps_executed": steps,
                "goal": {
                    "name": session.goal.name,
                    "success_criteria": [sc.description for sc in session.goal.success_criteria],
                },
                "recommendation": (
                    "Review the execution trace above. Does this flow achieve the goal?"
                ),
            },
            indent=2,
        )
