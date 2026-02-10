"""
Validates agent.json configuration at load time.

Catches missing fields, type errors, and structural issues early
instead of failing at runtime with confusing errors.

Fixes: https://github.com/adenhq/hive/issues/2039
"""

from __future__ import annotations

from typing import Any


class AgentConfigError(ValueError):
    """Raised when agent.json has invalid or missing configuration."""

    def __init__(self, errors: list[str], config_path: str = "agent.json"):
        self.errors = errors
        self.config_path = config_path
        error_list = "\n  - ".join(errors)
        super().__init__(
            f"Invalid {config_path}:\n  - {error_list}\n\n"
            f"See docs/getting-started.md for the required agent.json schema."
        )


# Valid node types — must match GraphExecutor.VALID_NODE_TYPES
VALID_NODE_TYPES = {
    "llm_tool_use",
    "llm_generate",
    "router",
    "function",
    "human_input",
    "event_loop",
}


def validate_agent_config(config: dict[str, Any], config_path: str = "agent.json") -> None:
    """
    Validate an agent configuration dictionary.

    Raises AgentConfigError with all validation errors if the config is invalid.
    Reports all errors at once for a better developer experience.

    Args:
        config: The parsed agent.json dictionary
        config_path: Path to config file (for error messages)

    Raises:
        AgentConfigError: If any validation checks fail
    """
    errors: list[str] = []

    # --- Required top-level fields ---
    REQUIRED_FIELDS: dict[str, type] = {
        "id": str,
        "name": str,
        "nodes": list,
        "edges": list,
        "entry_node": str,
        "goal": dict,
    }

    for field_name, expected_type in REQUIRED_FIELDS.items():
        if field_name not in config:
            errors.append(f"Missing required field: '{field_name}'")
        elif not isinstance(config[field_name], expected_type):
            actual = type(config[field_name]).__name__
            errors.append(
                f"Field '{field_name}' must be {expected_type.__name__}, got {actual}"
            )

    # Stop early if basic structure is broken — further checks depend on these
    if errors:
        raise AgentConfigError(errors, config_path)

    # --- Validate nodes ---
    node_ids: set[str] = set()
    for i, node in enumerate(config["nodes"]):
        if not isinstance(node, dict):
            errors.append(f"nodes[{i}]: must be a dict, got {type(node).__name__}")
            continue

        node_id = node.get("id")

        if node_id is None:
            errors.append(f"nodes[{i}]: missing required field 'id'")
        elif not isinstance(node_id, str):
            errors.append(
                f"nodes[{i}]: 'id' must be a string, got {type(node_id).__name__}"
            )
        else:
            if node_id in node_ids:
                errors.append(f"nodes[{i}]: duplicate node id '{node_id}'")
            node_ids.add(node_id)

        if "name" not in node:
            errors.append(f"nodes[{i}]: missing required field 'name'")

        node_type = node.get("node_type")
        if node_type is None:
            errors.append(f"nodes[{i}]: missing required field 'node_type'")
        elif node_type not in VALID_NODE_TYPES:
            node_label = node_id or f"index {i}"
            errors.append(
                f"nodes[{i}] (id='{node_label}'): "
                f"invalid node_type '{node_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_NODE_TYPES))}"
            )

        # llm_tool_use nodes must declare tools
        if node_type == "llm_tool_use" and not node.get("tools"):
            node_label = node_id or f"index {i}"
            errors.append(
                f"nodes[{i}] (id='{node_label}'): node_type is 'llm_tool_use' "
                f"but no tools are declared. Either add tools or use 'llm_generate'."
            )

    # --- Validate entry_node references an existing node ---
    entry_node = config["entry_node"]
    if node_ids and entry_node not in node_ids:
        errors.append(
            f"entry_node '{entry_node}' does not match any node id. "
            f"Available node ids: {sorted(node_ids)}"
        )

    # --- Validate edges ---
    for i, edge in enumerate(config["edges"]):
        if not isinstance(edge, dict):
            errors.append(f"edges[{i}]: must be a dict, got {type(edge).__name__}")
            continue

        source = edge.get("source")
        target = edge.get("target")

        if source is None:
            errors.append(f"edges[{i}]: missing required field 'source'")
        elif node_ids and source not in node_ids:
            errors.append(
                f"edges[{i}]: source '{source}' is not a valid node id. "
                f"Available: {sorted(node_ids)}"
            )

        if target is None:
            errors.append(f"edges[{i}]: missing required field 'target'")
        elif node_ids and target not in node_ids:
            errors.append(
                f"edges[{i}]: target '{target}' is not a valid node id. "
                f"Available: {sorted(node_ids)}"
            )

    # --- Validate goal ---
    goal = config["goal"]
    for required_goal_field in ("id", "name", "description"):
        if required_goal_field not in goal:
            errors.append(f"goal: missing required field '{required_goal_field}'")

    if errors:
        raise AgentConfigError(errors, config_path)
