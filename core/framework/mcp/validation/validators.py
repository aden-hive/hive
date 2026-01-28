"""
Validation logic for agent graphs and tool credentials.

Provides graph structure validation, context flow analysis, and
credential verification for MCP tools.
"""

import json

from framework.mcp.session import get_session


def validate_tool_credentials(tools_list: list[str]) -> dict | None:
    """
    Validate that credentials are available for the specified tools.

    Returns None if all credentials are available, or an error dict if any are missing.
    """
    if not tools_list:
        return None

    try:
        from aden_tools.credentials import CredentialManager

        cred_manager = CredentialManager()
        missing_creds = cred_manager.get_missing_for_tools(tools_list)

        if missing_creds:
            cred_errors = []
            for cred_name, spec in missing_creds:
                affected_tools = [t for t in tools_list if t in spec.tools]
                cred_errors.append(
                    {
                        "credential": cred_name,
                        "env_var": spec.env_var,
                        "tools_affected": affected_tools,
                        "help_url": spec.help_url,
                        "description": spec.description,
                    }
                )

            return {
                "valid": False,
                "errors": [f"Missing credentials for tools: {[e['env_var'] for e in cred_errors]}"],
                "missing_credentials": cred_errors,
                "action_required": "Add the credentials to your .env file and retry",
                "example": f"Add to .env:\n{cred_errors[0]['env_var']}=your_key_here",
                "message": (
                    "Cannot add node: missing API credentials. "
                    "Add them to .env and retry this command."
                ),
            }
    except ImportError as e:
        # Return a warning that credential validation was skipped
        return {
            "valid": True,
            "warnings": [
                f"⚠️ Credential validation SKIPPED: aden_tools not available ({e}). "
                "Tools may fail at runtime if credentials are missing. "
                "Add tools/src to PYTHONPATH to enable validation."
            ],
        }

    return None


def register(mcp):
    """Register graph validation tools on the MCP server."""

    @mcp.tool()
    def validate_graph() -> str:
        """Validate the graph. Checks for unreachable nodes and context flow."""
        session = get_session()
        errors = []
        warnings = []

        if not session.goal:
            errors.append("No goal defined")
            return json.dumps({"valid": False, "errors": errors})

        if not session.nodes:
            errors.append("No nodes defined")
            return json.dumps({"valid": False, "errors": errors})

        # === DETECT PAUSE/RESUME ARCHITECTURE ===
        pause_nodes = [n.id for n in session.nodes if "PAUSE" in n.description.upper()]
        resume_entry_points = [
            n.id
            for n in session.nodes
            if "RESUME" in n.description.upper() and "ENTRY" in n.description.upper()
        ]

        is_pause_resume_agent = len(pause_nodes) > 0 or len(resume_entry_points) > 0

        if is_pause_resume_agent:
            warnings.append(
                f"Pause/resume architecture detected. Pause nodes: {pause_nodes}, "
                f"Resume entry points: {resume_entry_points}"
            )

        # Find entry node (no incoming edges)
        entry_candidates = []
        for node in session.nodes:
            if not any(e.target == node.id for e in session.edges):
                entry_candidates.append(node.id)

        if not entry_candidates:
            errors.append("No entry node found (all nodes have incoming edges)")
        elif len(entry_candidates) > 1 and not is_pause_resume_agent:
            warnings.append(f"Multiple entry candidates: {entry_candidates}")

        # Find terminal nodes (no outgoing edges)
        terminal_candidates = []
        for node in session.nodes:
            if not any(e.source == node.id for e in session.edges):
                terminal_candidates.append(node.id)

        if not terminal_candidates:
            warnings.append("No terminal nodes found")

        # Check reachability
        if entry_candidates:
            reachable = set()

            if is_pause_resume_agent:
                to_visit = list(entry_candidates)
            else:
                to_visit = [entry_candidates[0]]

            while to_visit:
                current = to_visit.pop()
                if current in reachable:
                    continue
                reachable.add(current)
                for edge in session.edges:
                    if edge.source == current:
                        to_visit.append(edge.target)
                for node in session.nodes:
                    if node.id == current and node.routes:
                        for tgt in node.routes.values():
                            to_visit.append(tgt)

            unreachable = [n.id for n in session.nodes if n.id not in reachable]
            if unreachable:
                if is_pause_resume_agent:
                    unreachable_non_resume = [
                        n for n in unreachable if n not in resume_entry_points
                    ]
                    if unreachable_non_resume:
                        warnings.append(
                            f"Nodes unreachable from primary entry "
                            f"(may be resume-only nodes): {unreachable_non_resume}"
                        )
                else:
                    errors.append(f"Unreachable nodes: {unreachable}")

        # === CONTEXT FLOW VALIDATION ===
        dependencies: dict[str, list[str]] = {node.id: [] for node in session.nodes}
        for edge in session.edges:
            if edge.target in dependencies:
                dependencies[edge.target].append(edge.source)

        node_outputs: dict[str, set[str]] = {
            node.id: set(node.output_keys) for node in session.nodes
        }

        available_context: dict[str, set[str]] = {}
        computed = set()
        nodes_by_id = {n.id: n for n in session.nodes}

        initial_context_keys: set[str] = set()

        remaining = {n.id for n in session.nodes}
        max_iterations = len(session.nodes) * 2

        for _ in range(max_iterations):
            if not remaining:
                break

            for node_id in list(remaining):
                deps = dependencies.get(node_id, [])

                if all(d in computed for d in deps):
                    available = set(initial_context_keys)
                    for dep_id in deps:
                        available.update(node_outputs.get(dep_id, set()))
                        available.update(available_context.get(dep_id, set()))

                    available_context[node_id] = available
                    computed.add(node_id)
                    remaining.remove(node_id)
                    break

        # Check each node's input requirements
        context_errors = []
        context_warnings = []
        missing_inputs: dict[str, list[str]] = {}

        for node in session.nodes:
            available = available_context.get(node.id, set())

            for input_key in node.input_keys:
                if input_key not in available:
                    if node.id not in missing_inputs:
                        missing_inputs[node.id] = []
                    missing_inputs[node.id].append(input_key)

        # Generate helpful error messages
        for node_id, missing in missing_inputs.items():
            node = nodes_by_id.get(node_id)
            deps = dependencies.get(node_id, [])

            is_resume_entry = node_id in resume_entry_points

            if not deps:
                if is_resume_entry:
                    context_warnings.append(
                        f"Resume entry node '{node_id}' requires inputs {missing} from "
                        "resumed invocation context. These will be provided by the "
                        "runtime when resuming (e.g., user's answers)."
                    )
                else:
                    context_warnings.append(
                        f"Node '{node_id}' requires inputs {missing} from initial context. "
                        f"Ensure these are provided when running the agent."
                    )
            else:
                external_input_keys = ["input", "user_response", "user_input", "answer", "answers"]
                unproduced_external = [k for k in missing if k in external_input_keys]

                if is_resume_entry and unproduced_external:
                    other_missing = [k for k in missing if k not in external_input_keys]

                    if unproduced_external:
                        context_warnings.append(
                            f"Resume entry node '{node_id}' expects external inputs "
                            f"{unproduced_external} from resumed invocation. "
                            "These will be injected by the runtime when user responds."
                        )

                    if other_missing:
                        suggestions = []
                        for key in other_missing:
                            producers = [n.id for n in session.nodes if key in n.output_keys]
                            if producers:
                                suggestions.append(
                                    f"'{key}' is produced by {producers} - ensure edge exists"
                                )
                            else:
                                suggestions.append(
                                    f"'{key}' is not produced"
                                    " - add node or include in external inputs"
                                )

                        context_errors.append(
                            f"Resume node '{node_id}' requires {other_missing} but "
                            f"dependencies {deps} don't provide them. "
                            f"Suggestions: {'; '.join(suggestions)}"
                        )
                else:
                    suggestions = []
                    for key in missing:
                        producers = [n.id for n in session.nodes if key in n.output_keys]
                        if producers:
                            suggestions.append(
                                f"'{key}' is produced by {producers} - add dependency edge"
                            )
                        else:
                            suggestions.append(
                                f"'{key}' is not produced by any node - add a node that outputs it"
                            )

                    context_errors.append(
                        f"Node '{node_id}' requires {missing} but dependencies "
                        f"{deps} don't provide them. Suggestions: {'; '.join(suggestions)}"
                    )

        errors.extend(context_errors)
        warnings.extend(context_warnings)

        return json.dumps(
            {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
                "entry_node": entry_candidates[0] if entry_candidates else None,
                "terminal_nodes": terminal_candidates,
                "node_count": len(session.nodes),
                "edge_count": len(session.edges),
                "pause_resume_detected": is_pause_resume_agent,
                "pause_nodes": pause_nodes,
                "resume_entry_points": resume_entry_points,
                "all_entry_points": entry_candidates,
                "context_flow": {node_id: list(keys) for node_id, keys in available_context.items()}
                if available_context
                else None,
            }
        )
