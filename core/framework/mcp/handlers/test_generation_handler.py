"""
Test generation guidelines MCP tools.

Provides constraint and success criteria test guidelines, templates,
and plan loading utilities for the agent testing workflow.
"""

import json
from pathlib import Path
from typing import Annotated

from framework.graph import Constraint, Goal, SuccessCriterion
from framework.graph.plan import Plan
from framework.mcp.session import get_current_session_raw
from framework.testing.prompts import PYTEST_TEST_FILE_HEADER


def _get_agent_module_from_path(agent_path: str) -> str:
    """Extract agent module name from path like 'exports/my_agent' -> 'my_agent'."""
    path = Path(agent_path)
    return path.name


def _format_constraint(constraint: Constraint) -> str:
    """Format a single constraint for display."""
    severity = "HARD" if constraint.constraint_type == "hard" else "SOFT"
    return f"""### Constraint: {constraint.id}
- Type: {severity} ({constraint.constraint_type})
- Category: {constraint.category}
- Description: {constraint.description}
- Check: {constraint.check}"""


def _format_constraints(constraints: list[Constraint]) -> str:
    """Format constraints for display."""
    lines = []
    for c in constraints:
        lines.append(_format_constraint(c))
        lines.append("")
    return "\n".join(lines)


def _format_criterion(criterion: SuccessCriterion) -> str:
    """Format a single success criterion for display."""
    return f"""### Success Criterion: {criterion.id}
- Description: {criterion.description}
- Metric: {criterion.metric}
- Target: {criterion.target}
- Weight: {criterion.weight}
- Currently met: {criterion.met}"""


def _format_success_criteria(criteria: list[SuccessCriterion]) -> str:
    """Format success criteria for display."""
    lines = []
    for c in criteria:
        lines.append(_format_criterion(c))
        lines.append("")
    return "\n".join(lines)


# Test template for Claude to use when writing tests
CONSTRAINT_TEST_TEMPLATE = '''@pytest.mark.asyncio
async def test_constraint_{constraint_id}_{scenario}(mock_mode):
    """Test: {description}"""
    result = await default_agent.run({{"key": "value"}}, mock_mode=mock_mode)

    # IMPORTANT: result is an ExecutionResult object with these attributes:
    # - result.success: bool - whether the agent succeeded
    # - result.output: dict - the agent's output data (access data here!)
    # - result.error: str or None - error message if failed

    assert result.success, f"Agent failed: {{result.error}}"

    # Access output data via result.output
    output_data = result.output or {{}}

    # Add constraint-specific assertions here
    assert condition, "Error message explaining what failed"
'''

SUCCESS_TEST_TEMPLATE = '''@pytest.mark.asyncio
async def test_success_{criteria_id}_{scenario}(mock_mode):
    """Test: {description}"""
    result = await default_agent.run({{"key": "value"}}, mock_mode=mock_mode)

    # IMPORTANT: result is an ExecutionResult object with these attributes:
    # - result.success: bool - whether the agent succeeded
    # - result.output: dict - the agent's output data (access data here!)
    # - result.error: str or None - error message if failed

    assert result.success, f"Agent failed: {{result.error}}"

    # Access output data via result.output
    output_data = result.output or {{}}

    # Add success criteria-specific assertions here
    assert condition, "Error message explaining what failed"
'''


def load_plan_from_json(plan_json: str | dict) -> Plan:
    """
    Load a Plan object from exported JSON.

    Args:
        plan_json: JSON string or dict from export_graph()

    Returns:
        Plan object ready for FlexibleGraphExecutor
    """
    from framework.graph.plan import Plan

    return Plan.from_json(plan_json)


def register(mcp):
    """Register test generation tools on the MCP server."""

    @mcp.tool()
    def generate_constraint_tests(
        goal_id: Annotated[str, "ID of the goal to generate tests for"],
        goal_json: Annotated[
            str,
            """JSON string of the Goal object. Constraint fields:
- id: string (required)
- description: string (required)
- constraint_type: "hard" or "soft" (required)
- category: string (optional, default: "general")
- check: string (optional, how to validate: "llm_judge", expression, or function name)""",
        ],
        agent_path: Annotated[str, "Path to agent export folder (e.g., 'exports/my_agent')"] = "",
    ) -> str:
        """
        Get constraint test guidelines for a goal.

        Returns formatted guidelines and goal data. The calling LLM should use these
        to write tests directly using the Write tool.

        NOTE: This tool no longer generates tests via LLM. Instead, it returns
        guidelines and templates for the calling agent (Claude) to write tests directly.
        """
        try:
            goal = Goal.model_validate_json(goal_json)
        except Exception as e:
            return json.dumps({"error": f"Invalid goal JSON: {e}"})

        _session = get_current_session_raw()

        # Derive agent_path from session if not provided
        if not agent_path and _session:
            agent_path = f"exports/{_session.name}"

        if not agent_path:
            return json.dumps({"error": "agent_path required (e.g., 'exports/my_agent')"})

        agent_module = _get_agent_module_from_path(agent_path)

        # Format constraints for display
        constraints_formatted = (
            _format_constraints(goal.constraints) if goal.constraints else "No constraints defined"
        )

        # Generate the file header that should be used
        file_header = PYTEST_TEST_FILE_HEADER.format(
            test_type="Constraint",
            agent_name=agent_module,
            description=f"Tests for constraints defined in goal: {goal.name}",
            agent_module=agent_module,
        )

        # Return guidelines + data for Claude to write tests directly
        return json.dumps(
            {
                "goal_id": goal_id,
                "agent_path": agent_path,
                "agent_module": agent_module,
                "output_file": f"{agent_path}/tests/test_constraints.py",
                "constraints": [c.model_dump() for c in goal.constraints]
                if goal.constraints
                else [],
                "constraints_formatted": constraints_formatted,
                "test_guidelines": {
                    "max_tests": 5,
                    "naming_convention": "test_constraint_<constraint_id>_<scenario>",
                    "required_decorator": "@pytest.mark.asyncio",
                    "required_fixture": "mock_mode",
                    "agent_call_pattern": (
                        "await default_agent.run(input_dict, mock_mode=mock_mode)"
                    ),
                    "result_type": ("ExecutionResult with .success, .output (dict), .error"),
                    "critical_rules": [
                        "Every test function MUST be async with @pytest.mark.asyncio",
                        "Every test MUST accept mock_mode as a parameter",
                        "Use await default_agent.run(input, mock_mode=mock_mode)",
                        "default_agent is already imported - do NOT add imports",
                        "NEVER call result.get() - use result.output.get() instead",
                        "Always check result.success before accessing result.output",
                    ],
                },
                "file_header": file_header,
                "test_template": CONSTRAINT_TEST_TEMPLATE,
                "instruction": (
                    "Write tests directly to output_file using Write tool. "
                    "Use file_header as start, add test functions per "
                    "test_template. Generate up to 5 tests covering "
                    "the most critical constraints."
                ),
            }
        )

    @mcp.tool()
    def generate_success_tests(
        goal_id: Annotated[str, "ID of the goal to generate tests for"],
        goal_json: Annotated[str, "JSON string of the Goal object"],
        node_names: Annotated[str, "Comma-separated list of agent node names"] = "",
        tool_names: Annotated[str, "Comma-separated list of available tool names"] = "",
        agent_path: Annotated[str, "Path to agent export folder (e.g., 'exports/my_agent')"] = "",
    ) -> str:
        """
        Get success criteria test guidelines for a goal.

        Returns formatted guidelines and goal data. The calling LLM should use these
        to write tests directly using the Write tool.

        NOTE: This tool no longer generates tests via LLM. Instead, it returns
        guidelines and templates for the calling agent (Claude) to write tests directly.
        """
        try:
            goal = Goal.model_validate_json(goal_json)
        except Exception as e:
            return json.dumps({"error": f"Invalid goal JSON: {e}"})

        _session = get_current_session_raw()

        # Derive agent_path from session if not provided
        if not agent_path and _session:
            agent_path = f"exports/{_session.name}"

        if not agent_path:
            return json.dumps({"error": "agent_path required (e.g., 'exports/my_agent')"})

        agent_module = _get_agent_module_from_path(agent_path)

        # Parse node/tool names for context
        nodes = [n.strip() for n in node_names.split(",") if n.strip()]
        tools = [t.strip() for t in tool_names.split(",") if t.strip()]

        # Format success criteria for display
        criteria_formatted = (
            _format_success_criteria(goal.success_criteria)
            if goal.success_criteria
            else "No success criteria defined"
        )

        # Generate the file header that should be used
        file_header = PYTEST_TEST_FILE_HEADER.format(
            test_type="Success criteria",
            agent_name=agent_module,
            description=(f"Tests for success criteria defined in goal: {goal.name}"),
            agent_module=agent_module,
        )

        # Return guidelines + data for Claude to write tests directly
        return json.dumps(
            {
                "goal_id": goal_id,
                "agent_path": agent_path,
                "agent_module": agent_module,
                "output_file": f"{agent_path}/tests/test_success_criteria.py",
                "success_criteria": [c.model_dump() for c in goal.success_criteria]
                if goal.success_criteria
                else [],
                "success_criteria_formatted": criteria_formatted,
                "agent_context": {
                    "node_names": nodes if nodes else ["(not specified)"],
                    "tool_names": tools if tools else ["(not specified)"],
                },
                "test_guidelines": {
                    "max_tests": 12,
                    "naming_convention": ("test_success_<criteria_id>_<scenario>"),
                    "required_decorator": "@pytest.mark.asyncio",
                    "required_fixture": "mock_mode",
                    "agent_call_pattern": (
                        "await default_agent.run(input_dict, mock_mode=mock_mode)"
                    ),
                    "result_type": ("ExecutionResult with .success, .output (dict), .error"),
                    "critical_rules": [
                        "Every test function MUST be async with @pytest.mark.asyncio",
                        "Every test MUST accept mock_mode as a parameter",
                        "Use await default_agent.run(input, mock_mode=mock_mode)",
                        "default_agent is already imported - do NOT add imports",
                        "NEVER call result.get() - use result.output.get() instead",
                        "Always check result.success before accessing result.output",
                    ],
                },
                "file_header": file_header,
                "test_template": SUCCESS_TEST_TEMPLATE,
                "instruction": (
                    "Write tests directly to output_file using Write tool. "
                    "Use file_header as start, add test functions per "
                    "test_template. Generate up to 12 tests covering "
                    "the most critical success criteria."
                ),
            }
        )
