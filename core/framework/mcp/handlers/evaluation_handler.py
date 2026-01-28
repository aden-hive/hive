"""
Evaluation rules and plan execution MCP tools.

Handles evaluation rule management, plan creation, validation, and simulation
for the Worker-Judge pattern.
"""

import json
from datetime import datetime
from typing import Annotated

# Module-level storage for evaluation rules
_evaluation_rules: list[dict] = []


def get_evaluation_rules() -> list[dict]:
    """Get the current evaluation rules list."""
    return _evaluation_rules


def register(mcp):
    """Register evaluation and plan tools on the MCP server."""

    @mcp.tool()
    def add_evaluation_rule(
        rule_id: Annotated[str, "Unique identifier for the rule"],
        description: Annotated[str, "Human-readable description of what this rule checks"],
        condition: Annotated[
            str,
            "Python expression with result, step, goal context. E.g., 'result.get(\"success\")'",
        ],
        action: Annotated[str, "Action when rule matches: accept, retry, replan, escalate"],
        feedback_template: Annotated[
            str, "Template for feedback message, can use {result}, {step}"
        ] = "",
        priority: Annotated[int, "Rule priority (higher = checked first)"] = 0,
    ) -> str:
        """
        Add an evaluation rule for the HybridJudge.

        Rules are checked in priority order before falling back to LLM evaluation.
        Use this to define deterministic success/failure conditions.

        Example conditions:
        - 'result.get("success") == True' - Check for explicit success flag
        - 'result.get("error_type") == "timeout"' - Check for specific error type
        - 'len(result.get("data", [])) > 0' - Check for non-empty data
        """
        global _evaluation_rules

        # Validate action
        valid_actions = ["accept", "retry", "replan", "escalate"]
        if action.lower() not in valid_actions:
            return json.dumps(
                {
                    "success": False,
                    "error": f"Invalid action '{action}'. Must be one of: {valid_actions}",
                }
            )

        # Check for duplicate
        if any(r["id"] == rule_id for r in _evaluation_rules):
            return json.dumps(
                {
                    "success": False,
                    "error": f"Rule '{rule_id}' already exists",
                }
            )

        rule = {
            "id": rule_id,
            "description": description,
            "condition": condition,
            "action": action.lower(),
            "feedback_template": feedback_template,
            "priority": priority,
        }

        _evaluation_rules.append(rule)
        _evaluation_rules.sort(key=lambda r: -r["priority"])

        return json.dumps(
            {
                "success": True,
                "rule": rule,
                "total_rules": len(_evaluation_rules),
            }
        )

    @mcp.tool()
    def list_evaluation_rules() -> str:
        """List all configured evaluation rules for the HybridJudge."""
        return json.dumps(
            {
                "rules": _evaluation_rules,
                "total": len(_evaluation_rules),
            }
        )

    @mcp.tool()
    def remove_evaluation_rule(
        rule_id: Annotated[str, "ID of the rule to remove"],
    ) -> str:
        """Remove an evaluation rule."""
        global _evaluation_rules

        for i, rule in enumerate(_evaluation_rules):
            if rule["id"] == rule_id:
                _evaluation_rules.pop(i)
                return json.dumps({"success": True, "removed": rule_id})

        return json.dumps({"success": False, "error": f"Rule '{rule_id}' not found"})

    @mcp.tool()
    def create_plan(
        plan_id: Annotated[str, "Unique identifier for the plan"],
        goal_id: Annotated[str, "ID of the goal this plan achieves"],
        description: Annotated[str, "Description of what this plan does"],
        steps: Annotated[
            str,
            "JSON array of plan steps with id, description, action, inputs, outputs, deps",
        ],
        context: Annotated[str, "JSON object with initial context for execution"] = "{}",
    ) -> str:
        """
        Create a plan for flexible execution.

        Plans are executed by the Worker-Judge loop. Each step specifies:
        - id: Unique step identifier
        - description: What this step does
        - action: Object with action_type and parameters
          - action_type: "llm_call", "tool_use", "function", "code_execution", "sub_graph"
          - For llm_call: prompt, system_prompt
          - For tool_use: tool_name, tool_args
          - For function: function_name, function_args
          - For code_execution: code
        - inputs: Dict mapping input names to values or "$variable" references
        - expected_outputs: List of output keys this step should produce
        - dependencies: List of step IDs that must complete first (deps)

        Example step:
        {
            "id": "step_1",
            "description": "Fetch user data",
            "action": {"action_type": "tool_use", "tool_name": "get_user", ...},
            "inputs": {"user_id": "$input_user_id"},
            "expected_outputs": ["user_data"],
            "dependencies": []
        }
        """
        try:
            steps_list = json.loads(steps)
            context_dict = json.loads(context)
        except json.JSONDecodeError as e:
            return json.dumps({"success": False, "error": f"Invalid JSON: {e}"})

        # Validate steps
        errors = []
        step_ids = set()

        for i, step in enumerate(steps_list):
            if "id" not in step:
                errors.append(f"Step {i} missing 'id'")
            else:
                if step["id"] in step_ids:
                    errors.append(f"Duplicate step id: {step['id']}")
                step_ids.add(step["id"])

            if "description" not in step:
                errors.append(f"Step {i} missing 'description'")

            if "action" not in step:
                errors.append(f"Step {i} missing 'action'")
            elif "action_type" not in step.get("action", {}):
                errors.append(f"Step {i} action missing 'action_type'")

            # Check dependencies exist
            for dep in step.get("dependencies", []):
                if dep not in step_ids:
                    errors.append(f"Step {step.get('id', i)} has unknown dependency: {dep}")

        if errors:
            return json.dumps({"success": False, "errors": errors})

        # Build plan object
        plan = {
            "id": plan_id,
            "goal_id": goal_id,
            "description": description,
            "steps": steps_list,
            "context": context_dict,
            "revision": 1,
            "created_at": datetime.now().isoformat(),
        }

        return json.dumps(
            {
                "success": True,
                "plan": plan,
                "step_count": len(steps_list),
                "note": "Plan created. Use execute_plan to run it with the Worker-Judge loop.",
            },
            indent=2,
        )

    @mcp.tool()
    def validate_plan(
        plan_json: Annotated[str, "JSON string of the plan to validate"],
    ) -> str:
        """
        Validate a plan structure before execution.

        Checks:
        - All required fields present
        - No circular dependencies
        - All dependencies reference existing steps
        - Action types are valid
        - Context flow: all $variable references can be resolved
        """
        try:
            plan = json.loads(plan_json)
        except json.JSONDecodeError as e:
            return json.dumps({"valid": False, "errors": [f"Invalid JSON: {e}"]})

        errors = []
        warnings = []

        # Check required fields
        required = ["id", "goal_id", "steps"]
        for field in required:
            if field not in plan:
                errors.append(f"Missing required field: {field}")

        if "steps" not in plan:
            return json.dumps({"valid": False, "errors": errors})

        steps = plan["steps"]
        step_ids = {s.get("id") for s in steps if "id" in s}
        steps_by_id = {s.get("id"): s for s in steps}

        # Check each step
        valid_action_types = ["llm_call", "tool_use", "function", "code_execution", "sub_graph"]

        for i, step in enumerate(steps):
            step_id = step.get("id", f"step_{i}")

            # Check dependencies
            for dep in step.get("dependencies", []):
                if dep not in step_ids:
                    errors.append(f"Step '{step_id}': unknown dependency '{dep}'")

            # Check action type
            action = step.get("action", {})
            action_type = action.get("action_type")
            if action_type and action_type not in valid_action_types:
                errors.append(f"Step '{step_id}': invalid action_type '{action_type}'")

            # Check action has required params
            if action_type == "llm_call" and not action.get("prompt"):
                warnings.append(f"Step '{step_id}': llm_call without prompt")
            if action_type == "tool_use" and not action.get("tool_name"):
                errors.append(f"Step '{step_id}': tool_use requires tool_name")
            if action_type == "code_execution" and not action.get("code"):
                errors.append(f"Step '{step_id}': code_execution requires code")

        # Check for circular dependencies
        def has_cycle(step_id: str, visited: set, path: set) -> bool:
            if step_id in path:
                return True
            if step_id in visited:
                return False

            visited.add(step_id)
            path.add(step_id)

            step = next((s for s in steps if s.get("id") == step_id), None)
            if step:
                for dep in step.get("dependencies", []):
                    if has_cycle(dep, visited, path):
                        return True

            path.remove(step_id)
            return False

        for step in steps:
            if has_cycle(step.get("id", ""), set(), set()):
                errors.append(f"Circular dependency detected involving step '{step.get('id')}'")
                break

        # === CONTEXT FLOW VALIDATION ===
        step_outputs: dict[str, set[str]] = {}
        for step in steps:
            step_outputs[step.get("id", "")] = set(step.get("expected_outputs", []))

        available_context: dict[str, set[str]] = {}
        computed = set()
        remaining = set(step_ids)

        initial_context = set(plan.get("context", {}).keys())

        for _ in range(len(steps) * 2):
            if not remaining:
                break

            for step_id in list(remaining):
                step = steps_by_id.get(step_id)
                if not step:
                    remaining.discard(step_id)
                    continue

                deps = step.get("dependencies", [])

                if all(d in computed for d in deps):
                    available = set(initial_context)
                    for dep_id in deps:
                        available.update(step_outputs.get(dep_id, set()))
                        available.update(available_context.get(dep_id, set()))

                    available_context[step_id] = available
                    computed.add(step_id)
                    remaining.discard(step_id)
                    break

        # Check each step's inputs can be resolved
        context_errors = []
        context_warnings = []

        for step in steps:
            step_id = step.get("id", "")
            available = available_context.get(step_id, set())
            deps = step.get("dependencies", [])
            inputs = step.get("inputs", {})

            missing_vars = []
            for _, input_value in inputs.items():
                if isinstance(input_value, str) and input_value.startswith("$"):
                    var_name = input_value[1:]
                    if var_name not in available:
                        missing_vars.append(var_name)

            if missing_vars:
                if not deps:
                    context_warnings.append(
                        f"Step '{step_id}' requires ${missing_vars} from initial context. "
                        f"Ensure these are provided when running the agent: {missing_vars}"
                    )
                else:
                    suggestions = []
                    for var in missing_vars:
                        producers = [
                            s.get("id") for s in steps if var in s.get("expected_outputs", [])
                        ]
                        if producers:
                            suggestions.append(
                                f"${var} is produced by {producers} - add as dependency"
                            )
                        else:
                            suggestions.append(
                                f"${var} is not produced by any step"
                                f" - add a step that outputs '{var}'"
                            )

                    context_errors.append(
                        f"Step '{step_id}' references ${missing_vars} but deps "
                        f"{deps} don't provide them. Suggestions: {'; '.join(suggestions)}"
                    )

        errors.extend(context_errors)
        warnings.extend(context_warnings)

        return json.dumps(
            {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
                "step_count": len(steps),
                "context_flow": {step_id: list(keys) for step_id, keys in available_context.items()}
                if available_context
                else None,
            }
        )

    @mcp.tool()
    def simulate_plan_execution(
        plan_json: Annotated[str, "JSON string of the plan to simulate"],
        max_steps: Annotated[int, "Maximum steps to simulate"] = 20,
    ) -> str:
        """
        Simulate plan execution without actually running it.

        Shows the order steps would execute based on dependencies.
        Useful for understanding the execution flow before running.
        """
        try:
            plan = json.loads(plan_json)
        except json.JSONDecodeError as e:
            return json.dumps({"success": False, "error": f"Invalid JSON: {e}"})

        # Validate first
        validation = json.loads(validate_plan(plan_json))
        if not validation["valid"]:
            return json.dumps(
                {
                    "success": False,
                    "error": "Plan is not valid",
                    "validation_errors": validation["errors"],
                }
            )

        steps = plan.get("steps", [])
        completed = set()
        execution_order = []
        iteration = 0

        while len(completed) < len(steps) and iteration < max_steps:
            iteration += 1

            # Find ready steps
            ready = []
            for step in steps:
                step_id = step.get("id")
                if step_id in completed:
                    continue
                deps = set(step.get("dependencies", []))
                if deps.issubset(completed):
                    ready.append(step)

            if not ready:
                break

            # Execute first ready step
            step = ready[0]
            step_id = step.get("id")

            execution_order.append(
                {
                    "iteration": iteration,
                    "step_id": step_id,
                    "description": step.get("description"),
                    "action_type": step.get("action", {}).get("action_type"),
                    "dependencies_met": list(step.get("dependencies", [])),
                    "parallel_candidates": [s.get("id") for s in ready[1:]],
                }
            )

            completed.add(step_id)

        remaining = [s.get("id") for s in steps if s.get("id") not in completed]

        return json.dumps(
            {
                "success": True,
                "execution_order": execution_order,
                "steps_simulated": len(execution_order),
                "remaining_steps": remaining,
                "plan_complete": len(remaining) == 0,
                "note": (
                    "This is a simulation. Actual execution may differ "
                    "based on step results and judge decisions."
                ),
            },
            indent=2,
        )
