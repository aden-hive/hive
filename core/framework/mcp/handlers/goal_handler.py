"""
Goal definition MCP tools.

Handles setting and validating agent goals with success criteria and constraints.
"""

import json
from typing import Annotated

from framework.graph import Constraint, Goal, SuccessCriterion
from framework.mcp.session import get_session, save_session


def register(mcp):
    """Register goal definition tools on the MCP server."""

    @mcp.tool()
    def set_goal(
        goal_id: Annotated[str, "Unique identifier for the goal"],
        name: Annotated[str, "Human-readable name"],
        description: Annotated[str, "What the agent should accomplish"],
        success_criteria: Annotated[
            str,
            "JSON array of success criteria objects with id, description, metric, target, weight",
        ],
        constraints: Annotated[
            str, "JSON array of constraint objects with id, description, constraint_type, category"
        ] = "[]",
    ) -> str:
        """Define the goal for the agent. Goals define what success looks like."""
        session = get_session()

        # Parse JSON inputs with error handling
        try:
            criteria_list = json.loads(success_criteria)
        except json.JSONDecodeError as e:
            return json.dumps(
                {
                    "valid": False,
                    "errors": [f"Invalid JSON in success_criteria: {e}"],
                    "warnings": [],
                }
            )

        try:
            constraint_list = json.loads(constraints)
        except json.JSONDecodeError as e:
            return json.dumps(
                {
                    "valid": False,
                    "errors": [f"Invalid JSON in constraints: {e}"],
                    "warnings": [],
                }
            )

        # Validate BEFORE object creation
        errors = []
        warnings = []

        if not goal_id:
            errors.append("Goal must have an id")
        if not name:
            errors.append("Goal must have a name")
        if not description:
            errors.append("Goal must have a description")
        if not criteria_list:
            errors.append("Goal must have at least one success criterion")
        if not constraint_list:
            warnings.append("Consider adding constraints")

        # Validate required fields in criteria and constraints
        for i, sc in enumerate(criteria_list):
            if not isinstance(sc, dict):
                errors.append(f"success_criteria[{i}] must be an object")
            else:
                if "id" not in sc:
                    errors.append(f"success_criteria[{i}] missing required field 'id'")
                if "description" not in sc:
                    errors.append(f"success_criteria[{i}] missing required field 'description'")

        for i, c in enumerate(constraint_list):
            if not isinstance(c, dict):
                errors.append(f"constraints[{i}] must be an object")
            else:
                if "id" not in c:
                    errors.append(f"constraints[{i}] missing required field 'id'")
                if "description" not in c:
                    errors.append(f"constraints[{i}] missing required field 'description'")

        # Return early if validation failed
        if errors:
            return json.dumps(
                {
                    "valid": False,
                    "errors": errors,
                    "warnings": warnings,
                }
            )

        # Convert to proper objects (now safe - we validated required fields)
        criteria = [
            SuccessCriterion(
                id=sc["id"],
                description=sc["description"],
                metric=sc.get("metric", ""),
                target=sc.get("target", ""),
                weight=sc.get("weight", 1.0),
            )
            for sc in criteria_list
        ]

        constraint_objs = [
            Constraint(
                id=c["id"],
                description=c["description"],
                constraint_type=c.get("constraint_type", "hard"),
                category=c.get("category", "safety"),
                check=c.get("check", ""),
            )
            for c in constraint_list
        ]

        session.goal = Goal(
            id=goal_id,
            name=name,
            description=description,
            success_criteria=criteria,
            constraints=constraint_objs,
        )

        save_session(session)

        return json.dumps(
            {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
                "goal": session.goal.model_dump(),
                "approval_required": True,
                "approval_question": {
                    "component_type": "goal",
                    "component_name": name,
                    "question": "Do you approve this goal definition?",
                    "header": "Approve Goal",
                    "options": [
                        {
                            "label": "✓ Approve (Recommended)",
                            "description": "Goal looks good, proceed to adding nodes",
                        },
                        {
                            "label": "✗ Reject & Modify",
                            "description": "Need to adjust goal criteria or constraints",
                        },
                        {
                            "label": "⏸ Pause & Review",
                            "description": "I need more time to review this goal",
                        },
                    ],
                },
            },
            default=str,
        )
