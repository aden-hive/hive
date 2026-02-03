"""
MCP Server for Agent Building Tools

Exposes tools for building goal-driven agents via the Model Context Protocol.

Usage:
    python -m framework.mcp.agent_builder_server
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated

from mcp.server import FastMCP

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, NodeSpec, SuccessCriterion
from framework.graph.plan import Plan

# Testing framework imports
from framework.testing.prompts import (
    PYTEST_TEST_FILE_HEADER,
)
from framework.utils.io import atomic_write

# Initialize MCP server
mcp = FastMCP("agent-builder")


# Session persistence directory
SESSIONS_DIR = Path(".agent-builder-sessions")
ACTIVE_SESSION_FILE = SESSIONS_DIR / ".active"


# Session storage
class BuildSession:
    """Build session with persistence support."""

    def __init__(self, name: str, session_id: str | None = None):
        self.id = session_id or f"build_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.name = name
        self.goal: Goal | None = None
        self.nodes: list[NodeSpec] = []
        self.edges: list[EdgeSpec] = []
        self.mcp_servers: list[dict] = []  # MCP server configurations
        self.created_at = datetime.now().isoformat()
        self.last_modified = datetime.now().isoformat()

    def to_dict(self) -> dict:
        """Serialize session to dictionary."""
        return {
            "session_id": self.id,
            "name": self.name,
            "goal": self.goal.model_dump() if self.goal else None,
            "nodes": [n.model_dump() for n in self.nodes],
            "edges": [e.model_dump() for e in self.edges],
            "mcp_servers": self.mcp_servers,
            "created_at": self.created_at,
            "last_modified": self.last_modified,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BuildSession":
        """Deserialize session from dictionary."""
        session = cls(name=data["name"], session_id=data["session_id"])
        session.created_at = data.get("created_at", session.created_at)
        session.last_modified = data.get("last_modified", session.last_modified)

        # Restore goal
        if data.get("goal"):
            goal_data = data["goal"]
            session.goal = Goal(
                id=goal_data["id"],
                name=goal_data["name"],
                description=goal_data["description"],
                success_criteria=[
                    SuccessCriterion(**sc) for sc in goal_data.get("success_criteria", [])
                ],
                constraints=[Constraint(**c) for c in goal_data.get("constraints", [])],
            )

        # Restore nodes
        session.nodes = [NodeSpec(**n) for n in data.get("nodes", [])]

        # Restore edges
        edges_data = data.get("edges", [])
        for e in edges_data:
            # Convert condition string back to enum
            condition_str = e.get("condition")
            if isinstance(condition_str, str):
                condition_map = {
                    "always": EdgeCondition.ALWAYS,
                    "on_success": EdgeCondition.ON_SUCCESS,
                    "on_failure": EdgeCondition.ON_FAILURE,
                    "conditional": EdgeCondition.CONDITIONAL,
                    "llm_decide": EdgeCondition.LLM_DECIDE,
                }
                e["condition"] = condition_map.get(condition_str, EdgeCondition.ON_SUCCESS)
            session.edges.append(EdgeSpec(**e))

        # Restore MCP servers
        session.mcp_servers = data.get("mcp_servers", [])

        return session


# Global session
_session: BuildSession | None = None


def _ensure_sessions_dir():
    """Ensure sessions directory exists."""
    SESSIONS_DIR.mkdir(exist_ok=True)


def _save_session(session: BuildSession):
    """Save session to disk."""
    _ensure_sessions_dir()

    # Update last modified
    session.last_modified = datetime.now().isoformat()

    # Save session file
    session_file = SESSIONS_DIR / f"{session.id}.json"
    with atomic_write(session_file) as f:
        json.dump(session.to_dict(), f, indent=2, default=str)

    # Update active session pointer
    with atomic_write(ACTIVE_SESSION_FILE) as f:
        f.write(session.id)


def _load_session(session_id: str) -> BuildSession:
    """Load session from disk."""
    session_file = SESSIONS_DIR / f"{session_id}.json"
    if not session_file.exists():
        raise ValueError(f"Session '{session_id}' not found")

    with open(session_file) as f:
        data = json.load(f)

    return BuildSession.from_dict(data)


def _load_active_session() -> BuildSession | None:
    """Load the active session if one exists."""
    if not ACTIVE_SESSION_FILE.exists():
        return None

    try:
        with open(ACTIVE_SESSION_FILE) as f:
            session_id = f.read().strip()

        if session_id:
            return _load_session(session_id)
    except Exception:
        pass

    return None


def get_session() -> BuildSession:
    global _session

    # Try to load active session if no session in memory
    if _session is None:
        _session = _load_active_session()

    if _session is None:
        raise ValueError("No active session. Call create_session first.")

    return _session


# =============================================================================
# MCP TOOLS
# =============================================================================


@mcp.tool()
def create_session(name: Annotated[str, "Name for the agent being built"]) -> str:
    """Create a new agent building session. Call this first before building an agent."""
    global _session
    _session = BuildSession(name)
    _save_session(_session)  # Auto-save
    return json.dumps(
        {
            "session_id": _session.id,
            "name": name,
            "status": "created",
            "persisted": True,
        }
    )


@mcp.tool()
def list_sessions() -> str:
    """List all saved agent building sessions."""
    _ensure_sessions_dir()

    sessions = []
    if SESSIONS_DIR.exists():
        for session_file in SESSIONS_DIR.glob("*.json"):
            try:
                with open(session_file) as f:
                    data = json.load(f)
                    sessions.append(
                        {
                            "session_id": data["session_id"],
                            "name": data["name"],
                            "created_at": data.get("created_at"),
                            "last_modified": data.get("last_modified"),
                            "node_count": len(data.get("nodes", [])),
                            "edge_count": len(data.get("edges", [])),
                            "has_goal": data.get("goal") is not None,
                        }
                    )
            except Exception:
                pass  # Skip corrupted files

    # Check which session is currently active
    active_id = None
    if ACTIVE_SESSION_FILE.exists():
        try:
            with open(ACTIVE_SESSION_FILE) as f:
                active_id = f.read().strip()
        except Exception:
            pass

    return json.dumps(
        {
            "sessions": sorted(sessions, key=lambda s: s["last_modified"], reverse=True),
            "total": len(sessions),
            "active_session_id": active_id,
        },
        indent=2,
    )


@mcp.tool()
def load_session_by_id(session_id: Annotated[str, "ID of the session to load"]) -> str:
    """Load a previously saved agent building session by its ID."""
    global _session

    try:
        _session = _load_session(session_id)

        # Update active session pointer
        with atomic_write(ACTIVE_SESSION_FILE) as f:
            f.write(session_id)

        return json.dumps(
            {
                "success": True,
                "session_id": _session.id,
                "name": _session.name,
                "node_count": len(_session.nodes),
                "edge_count": len(_session.edges),
                "has_goal": _session.goal is not None,
                "created_at": _session.created_at,
                "last_modified": _session.last_modified,
                "message": f"Session '{_session.name}' loaded successfully",
            }
        )
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
def delete_session(session_id: Annotated[str, "ID of the session to delete"]) -> str:
    """Delete a saved agent building session."""
    global _session

    session_file = SESSIONS_DIR / f"{session_id}.json"
    if not session_file.exists():
        return json.dumps({"success": False, "error": f"Session '{session_id}' not found"})

    try:
        # Remove session file
        session_file.unlink()

        # Clear active session if it was the deleted one
        if _session and _session.id == session_id:
            _session = None

        if ACTIVE_SESSION_FILE.exists():
            with open(ACTIVE_SESSION_FILE) as f:
                active_id = f.read().strip()
                if active_id == session_id:
                    ACTIVE_SESSION_FILE.unlink()

        return json.dumps(
            {
                "success": True,
                "deleted_session_id": session_id,
                "message": f"Session '{session_id}' deleted successfully",
            }
        )
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
def set_goal(
    goal_id: Annotated[str, "Unique identifier for the goal"],
    name: Annotated[str, "Human-readable name"],
    description: Annotated[str, "What the agent should accomplish"],
    success_criteria: Annotated[
        str, "JSON array of success criteria objects with id, description, metric, target, weight"
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

    _save_session(session)  # Auto-save

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


def _validate_tool_credentials(tools_list: list[str]) -> dict | None:
    """
    Validate that credentials are available for the specified tools.

    Returns None if all credentials are available, or an error dict if any are missing.
    """
    if not tools_list:
        return None

    try:
        from aden_tools.credentials import CREDENTIAL_SPECS

        store = _get_credential_store()

        # Build tool -> credential mapping
        tool_to_cred: dict[str, str] = {}
        for cred_name, spec in CREDENTIAL_SPECS.items():
            for tool_name in spec.tools:
                tool_to_cred[tool_name] = cred_name

        # Find missing credentials
        cred_errors = []
        checked: set[str] = set()
        for tool_name in tools_list:
            cred_name = tool_to_cred.get(tool_name)
            if cred_name is None or cred_name in checked:
                continue
            checked.add(cred_name)
            spec = CREDENTIAL_SPECS[cred_name]
            cred_id = spec.credential_id or cred_name
            if spec.required and not store.is_available(cred_id):
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

        if cred_errors:
            return {
                "valid": False,
                "errors": [f"Missing credentials for tools: {[e['env_var'] for e in cred_errors]}"],
                "missing_credentials": cred_errors,
                "action_required": "Store credentials via store_credential and retry",
                "example": f"Add to .env:\n{cred_errors[0]['env_var']}=your_key_here",
                "message": (
                    "Cannot add node: missing API credentials. "
                    "Store them via store_credential and retry this command."
                ),
            }
    except ImportError as e:
        # Return a warning that credential validation was skipped
        return {
            "valid": True,
            "warnings": [
                f"Credential validation SKIPPED: aden_tools not available ({e}). "
                "Tools may fail at runtime if credentials are missing. "
                "Add tools/src to PYTHONPATH to enable validation."
            ],
        }

    return None


def _validate_agent_path(agent_path: str) -> tuple[Path | None, str | None]:
    """
    Validate and normalize agent_path.

    Returns:
        (Path, None) if valid
        (None, error_json) if invalid
    """
    if not agent_path:
        return None, json.dumps(
            {
                "success": False,
                "error": "agent_path is required (e.g., 'exports/my_agent')",
            }
        )

    path = Path(agent_path)

    if not path.exists():
        return None, json.dumps(
            {
                "success": False,
                "error": f"Agent path not found: {path}",
                "hint": "Run export_graph to create an agent in exports/ first",
            }
        )

    return path, None


@mcp.tool()
def add_node(
    node_id: Annotated[str, "Unique identifier for the node"],
    name: Annotated[str, "Human-readable name"],
    description: Annotated[str, "What this node does"],
    node_type: Annotated[str, "Type: llm_generate, llm_tool_use, router, or function"],
    input_keys: Annotated[str, "JSON array of keys this node reads from shared memory"],
    output_keys: Annotated[str, "JSON array of keys this node writes to shared memory"],
    system_prompt: Annotated[str, "Instructions for LLM nodes"] = "",
    tools: Annotated[str, "JSON array of tool names for llm_tool_use nodes"] = "[]",
    routes: Annotated[
        str, "JSON object mapping conditions to target node IDs for router nodes"
    ] = "{}",
) -> str:
    """Add a node to the agent graph. Nodes process inputs and produce outputs."""
    session = get_session()

    # Parse JSON inputs
    try:
        input_keys_list = json.loads(input_keys)
        output_keys_list = json.loads(output_keys)
        tools_list = json.loads(tools)
        routes_dict = json.loads(routes)
    except json.JSONDecodeError as e:
        return json.dumps(
            {
                "valid": False,
                "errors": [f"Invalid JSON input: {e}"],
                "warnings": [],
            }
        )

    # Validate credentials for tools BEFORE adding the node
    cred_error = _validate_tool_credentials(tools_list)
    if cred_error:
        return json.dumps(cred_error)

    # Check for duplicate
    if any(n.id == node_id for n in session.nodes):
        return json.dumps({"valid": False, "errors": [f"Node '{node_id}' already exists"]})

    node = NodeSpec(
        id=node_id,
        name=name,
        description=description,
        node_type=node_type,
        input_keys=input_keys_list,
        output_keys=output_keys_list,
        system_prompt=system_prompt or None,
        tools=tools_list,
        routes=routes_dict,
    )

    session.nodes.append(node)

    # Validate
    errors = []
    warnings = []

    if not node_id:
        errors.append("Node must have an id")
    if not name:
        errors.append("Node must have a name")
    if node_type == "llm_tool_use" and not tools_list:
        errors.append(f"Node '{node_id}' of type llm_tool_use must specify tools")
    if node_type == "router" and not routes_dict:
        errors.append(f"Router node '{node_id}' must specify routes")
    if node_type in ("llm_generate", "llm_tool_use") and not system_prompt:
        warnings.append(f"LLM node '{node_id}' should have a system_prompt")

    _save_session(session)  # Auto-save

    return json.dumps(
        {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "node": node.model_dump(),
            "total_nodes": len(session.nodes),
            "approval_required": True,
            "approval_question": {
                "component_type": "node",
                "component_name": name,
                "question": f"Do you approve this {node_type} node: {name}?",
                "header": "Approve Node",
                "options": [
                    {
                        "label": "✓ Approve (Recommended)",
                        "description": f"Node '{name}' looks good, continue building",
                    },
                    {
                        "label": "✗ Reject & Modify",
                        "description": "Need to change node configuration",
                    },
                    {
                        "label": "⏸ Pause & Review",
                        "description": "I need more time to review this node",
                    },
                ],
            },
        },
        default=str,
    )


@mcp.tool()
def add_edge(
    edge_id: Annotated[str, "Unique identifier for the edge"],
    source: Annotated[str, "Source node ID"],
    target: Annotated[str, "Target node ID"],
    condition: Annotated[
        str, "When to traverse: always, on_success, on_failure, conditional"
    ] = "on_success",
    condition_expr: Annotated[str, "Python expression for conditional edges"] = "",
    priority: Annotated[int, "Priority when multiple edges match (higher = first)"] = 0,
) -> str:
    """Connect two nodes with an edge. Edges define how execution flows between nodes."""
    session = get_session()

    # Check for duplicate
    if any(e.id == edge_id for e in session.edges):
        return json.dumps({"valid": False, "errors": [f"Edge '{edge_id}' already exists"]})

    # Map condition string to enum
    condition_map = {
        "always": EdgeCondition.ALWAYS,
        "on_success": EdgeCondition.ON_SUCCESS,
        "on_failure": EdgeCondition.ON_FAILURE,
        "conditional": EdgeCondition.CONDITIONAL,
        "llm_decide": EdgeCondition.LLM_DECIDE,
    }
    edge_condition = condition_map.get(condition, EdgeCondition.ON_SUCCESS)

    edge = EdgeSpec(
        id=edge_id,
        source=source,
        target=target,
        condition=edge_condition,
        condition_expr=condition_expr or None,
        priority=priority,
    )

    session.edges.append(edge)

    # Validate
    errors = []

    if not any(n.id == source for n in session.nodes):
        errors.append(f"Source node '{source}' not found")
    if not any(n.id == target for n in session.nodes):
        errors.append(f"Target node '{target}' not found")
    if edge_condition == EdgeCondition.CONDITIONAL and not condition_expr:
        errors.append(f"Conditional edge '{edge_id}' needs condition_expr")

    _save_session(session)  # Auto-save

    return json.dumps(
        {
            "valid": len(errors) == 0,
            "errors": errors,
            "edge": edge.model_dump(),
            "total_edges": len(session.edges),
            "approval_required": True,
            "approval_question": {
                "component_type": "edge",
                "component_name": f"{source} → {target}",
                "question": f"Do you approve this edge: {source} → {target}?",
                "header": "Approve Edge",
                "options": [
                    {
                        "label": "✓ Approve (Recommended)",
                        "description": "Edge connection looks good",
                    },
                    {
                        "label": "✗ Reject & Modify",
                        "description": "Need to change edge condition or targets",
                    },
                    {
                        "label": "⏸ Pause & Review",
                        "description": "I need more time to review this edge",
                    },
                ],
            },
        },
        default=str,
    )


@mcp.tool()
def update_node(
    node_id: Annotated[str, "ID of the node to update"],
    name: Annotated[str, "Updated human-readable name"] = "",
    description: Annotated[str, "Updated description"] = "",
    node_type: Annotated[str, "Updated type: llm_generate, llm_tool_use, router, or function"] = "",
    input_keys: Annotated[str, "Updated JSON array of input keys"] = "",
    output_keys: Annotated[str, "Updated JSON array of output keys"] = "",
    system_prompt: Annotated[str, "Updated instructions for LLM nodes"] = "",
    tools: Annotated[str, "Updated JSON array of tool names"] = "",
    routes: Annotated[str, "Updated JSON object mapping conditions to target node IDs"] = "",
) -> str:
    """Update an existing node in the agent graph. Only provided fields will be updated."""
    session = get_session()

    # Find the node
    node = None
    for n in session.nodes:
        if n.id == node_id:
            node = n
            break

    if not node:
        return json.dumps({"valid": False, "errors": [f"Node '{node_id}' not found"]})

    # Parse JSON inputs with error handling
    try:
        input_keys_list = json.loads(input_keys) if input_keys else None
        output_keys_list = json.loads(output_keys) if output_keys else None
        tools_list = json.loads(tools) if tools else None
        routes_dict = json.loads(routes) if routes else None
    except json.JSONDecodeError as e:
        return json.dumps(
            {
                "valid": False,
                "errors": [f"Invalid JSON input: {e}"],
                "warnings": [],
            }
        )

    # Validate credentials for new tools BEFORE updating
    if tools_list:
        cred_error = _validate_tool_credentials(tools_list)
        if cred_error:
            return json.dumps(cred_error)

    # Update fields if provided
    if name:
        node.name = name
    if description:
        node.description = description
    if node_type:
        node.node_type = node_type
    if input_keys_list is not None:
        node.input_keys = input_keys_list
    if output_keys_list is not None:
        node.output_keys = output_keys_list
    if system_prompt:
        node.system_prompt = system_prompt
    if tools_list is not None:
        node.tools = tools_list
    if routes_dict is not None:
        node.routes = routes_dict

    # Validate
    errors = []
    warnings = []

    if node.node_type == "llm_tool_use" and not node.tools:
        errors.append(f"Node '{node_id}' of type llm_tool_use must specify tools")
    if node.node_type == "router" and not node.routes:
        errors.append(f"Router node '{node_id}' must specify routes")
    if node.node_type in ("llm_generate", "llm_tool_use") and not node.system_prompt:
        warnings.append(f"LLM node '{node_id}' should have a system_prompt")

    _save_session(session)  # Auto-save

    return json.dumps(
        {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "node": node.model_dump(),
            "total_nodes": len(session.nodes),
            "approval_required": True,
            "approval_question": {
                "component_type": "node",
                "component_name": node.name,
                "question": f"Do you approve this updated {node.node_type} node: {node.name}?",
                "header": "Approve Node Update",
                "options": [
                    {
                        "label": "✓ Approve (Recommended)",
                        "description": f"Updated node '{node.name}' looks good",
                    },
                    {
                        "label": "✗ Reject & Modify",
                        "description": "Need to change node configuration",
                    },
                    {
                        "label": "⏸ Pause & Review",
                        "description": "I need more time to review this update",
                    },
                ],
            },
        },
        default=str,
    )


@mcp.tool()
def delete_node(
    node_id: Annotated[str, "ID of the node to delete"],
) -> str:
    """Delete a node from the agent graph. Also removes all edges connected to this node."""
    session = get_session()

    # Find the node
    node_idx = None
    for i, n in enumerate(session.nodes):
        if n.id == node_id:
            node_idx = i
            break

    if node_idx is None:
        return json.dumps({"valid": False, "errors": [f"Node '{node_id}' not found"]})

    # Remove the node
    removed_node = session.nodes.pop(node_idx)

    # Remove all edges connected to this node
    removed_edges = [e.id for e in session.edges if e.source == node_id or e.target == node_id]
    session.edges = [e for e in session.edges if not (e.source == node_id or e.target == node_id)]

    _save_session(session)  # Auto-save

    return json.dumps(
        {
            "valid": True,
            "deleted_node": removed_node.model_dump(),
            "removed_edges": removed_edges,
            "total_nodes": len(session.nodes),
            "total_edges": len(session.edges),
            "message": f"Node '{node_id}' and {len(removed_edges)} connected edge(s) removed",
        },
        default=str,
    )


@mcp.tool()
def delete_edge(
    edge_id: Annotated[str, "ID of the edge to delete"],
) -> str:
    """Delete an edge from the agent graph."""
    session = get_session()

    # Find the edge
    edge_idx = None
    for i, e in enumerate(session.edges):
        if e.id == edge_id:
            edge_idx = i
            break

    if edge_idx is None:
        return json.dumps({"valid": False, "errors": [f"Edge '{edge_id}' not found"]})

    # Remove the edge
    removed_edge = session.edges.pop(edge_idx)

    _save_session(session)  # Auto-save

    return json.dumps(
        {
            "valid": True,
            "deleted_edge": removed_edge.model_dump(),
            "total_edges": len(session.edges),
            "message": f"Edge '{edge_id}' removed: {removed_edge.source} → {removed_edge.target}",
        },
        default=str,
    )


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
    # Identify pause nodes (nodes marked as PAUSE in description)
    pause_nodes = [n.id for n in session.nodes if "PAUSE" in n.description.upper()]

    # Identify resume entry points (nodes marked as RESUME ENTRY POINT in description)
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
        # Multiple entry points are expected for pause/resume agents
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

        # For pause/resume agents, start from ALL entry points (including resume)
        if is_pause_resume_agent:
            to_visit = list(entry_candidates)  # All nodes without incoming edges
        else:
            to_visit = [entry_candidates[0]]  # Just the primary entry

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
            # For pause/resume agents, nodes might be reachable only from resume entry points
            if is_pause_resume_agent:
                # Filter out resume entry points from unreachable list
                unreachable_non_resume = [n for n in unreachable if n not in resume_entry_points]
                if unreachable_non_resume:
                    warnings.append(
                        f"Nodes unreachable from primary entry "
                        f"(may be resume-only nodes): {unreachable_non_resume}"
                    )
            else:
                errors.append(f"Unreachable nodes: {unreachable}")

    # === CONTEXT FLOW VALIDATION ===
    # Build dependency map (node_id -> list of nodes it depends on)
    dependencies: dict[str, list[str]] = {node.id: [] for node in session.nodes}
    for edge in session.edges:
        if edge.target in dependencies:
            dependencies[edge.target].append(edge.source)

    # Build output map (node_id -> keys it produces)
    node_outputs: dict[str, set[str]] = {node.id: set(node.output_keys) for node in session.nodes}

    # Compute available context for each node (what keys it can read)
    # Using topological order
    available_context: dict[str, set[str]] = {}
    computed = set()
    nodes_by_id = {n.id: n for n in session.nodes}

    # Initial context keys that will be provided at runtime
    # These are typically the inputs like lead_id, gtm_table_id, etc.
    # Entry nodes can only read from initial context
    initial_context_keys: set[str] = set()

    # Compute in topological order
    remaining = {n.id for n in session.nodes}
    max_iterations = len(session.nodes) * 2

    for _ in range(max_iterations):
        if not remaining:
            break

        for node_id in list(remaining):
            deps = dependencies.get(node_id, [])

            # Can compute if all dependencies are computed (or no dependencies)
            if all(d in computed for d in deps):
                # Collect outputs from all dependencies
                available = set(initial_context_keys)
                for dep_id in deps:
                    # Add outputs from dependency
                    available.update(node_outputs.get(dep_id, set()))
                    # Also add what was available to the dependency (transitive)
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

        # Check if this is a resume entry point
        is_resume_entry = node_id in resume_entry_points

        if not deps:
            # Entry node - inputs must come from initial runtime context
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
            # Check if this is a common external input key for resume nodes
            external_input_keys = ["input", "user_response", "user_input", "answer", "answers"]
            unproduced_external = [k for k in missing if k in external_input_keys]

            if is_resume_entry and unproduced_external:
                # Resume entry points can receive external inputs from resumed invocations
                other_missing = [k for k in missing if k not in external_input_keys]

                if unproduced_external:
                    context_warnings.append(
                        f"Resume entry node '{node_id}' expects external inputs "
                        f"{unproduced_external} from resumed invocation. "
                        "These will be injected by the runtime when user responds."
                    )

                if other_missing:
                    # Still need to check other keys
                    suggestions = []
                    for key in other_missing:
                        producers = [n.id for n in session.nodes if key in n.output_keys]
                        if producers:
                            suggestions.append(
                                f"'{key}' is produced by {producers} - ensure edge exists"
                            )
                        else:
                            suggestions.append(
                                f"'{key}' is not produced - add node or include in external inputs"
                            )

                    context_errors.append(
                        f"Resume node '{node_id}' requires {other_missing} but "
                        f"dependencies {deps} don't provide them. "
                        f"Suggestions: {'; '.join(suggestions)}"
                    )
            else:
                # Non-resume node or no external input keys - standard validation
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


def _generate_readme(session: BuildSession, export_data: dict, all_tools: set) -> str:
    """Generate README.md content for the exported agent."""
    goal = session.goal
    nodes = session.nodes
    edges = session.edges

    # Build execution flow diagram
    flow_parts = []
    current = export_data["graph"]["entry_node"]
    visited = set()

    while current and current not in visited:
        visited.add(current)
        flow_parts.append(current)
        # Find next node
        next_node = None
        for edge in edges:
            if edge.source == current:
                next_node = edge.target
                break
        # Check router routes
        for node in nodes:
            if node.id == current and node.routes:
                route_targets = list(node.routes.values())
                if route_targets:
                    flow_parts.append("{" + " | ".join(route_targets) + "}")
                    next_node = None
                break
        current = next_node

    flow_diagram = " → ".join(flow_parts)

    # Build nodes section
    nodes_section = []
    for i, node in enumerate(nodes, 1):
        node_info = [f"{i}. **{node.id}** ({node.node_type})"]
        node_info.append(f"   - {node.description}")
        if node.input_keys:
            node_info.append(f"   - Reads: `{', '.join(node.input_keys)}`")
        if node.output_keys:
            node_info.append(f"   - Writes: `{', '.join(node.output_keys)}`")
        if node.tools:
            node_info.append(f"   - Tools: `{', '.join(node.tools)}`")
        if node.routes:
            routes_str = ", ".join([f"{k}→{v}" for k, v in node.routes.items()])
            node_info.append(f"   - Routes: {routes_str}")
        nodes_section.append("\n".join(node_info))

    # Build success criteria section
    criteria_section = []
    for criterion in goal.success_criteria:
        crit_dict = (
            criterion.model_dump() if hasattr(criterion, "model_dump") else criterion.__dict__
        )
        criteria_section.append(
            f"**{crit_dict.get('description', 'N/A')}** (weight {crit_dict.get('weight', 1.0)})\n"
            f"- Metric: {crit_dict.get('metric', 'N/A')}\n"
            f"- Target: {crit_dict.get('target', 'N/A')}"
        )

    # Build constraints section
    constraints_section = []
    for constraint in goal.constraints:
        const_dict = (
            constraint.model_dump() if hasattr(constraint, "model_dump") else constraint.__dict__
        )
        desc = const_dict.get("description", "N/A")
        ctype = const_dict.get("constraint_type", "hard")
        cat = const_dict.get("category", "N/A")
        constraints_section.append(f"**{desc}** ({ctype})\n- Category: {cat}")

    readme = f"""# {goal.name}

**Version**: 1.0.0
**Type**: Multi-node agent
**Created**: {datetime.now().strftime("%Y-%m-%d")}

## Overview

{goal.description}

## Architecture

### Execution Flow

```
{flow_diagram}
```

### Nodes ({len(nodes)} total)

{chr(10).join(nodes_section)}

### Edges ({len(edges)} total)

"""

    for edge in edges:
        cond = edge.condition.value if hasattr(edge.condition, "value") else edge.condition
        readme += f"- `{edge.source}` → `{edge.target}` (condition: {cond})\n"

    readme += f"""

## Goal Criteria

### Success Criteria

{chr(10).join(criteria_section)}

### Constraints

{chr(10).join(constraints_section) if constraints_section else "None defined"}

## Required Tools

{chr(10).join(f"- `{tool}`" for tool in sorted(all_tools)) if all_tools else "No tools required"}

{"## MCP Tool Sources" if session.mcp_servers else ""}

{
        chr(10).join(
            f'''### {s["name"]} ({s["transport"]})
{s.get("description", "")}

**Configuration:**
'''
            + (
                f'''- Command: `{s.get("command")}`
- Args: `{s.get("args")}`
- Working Directory: `{s.get("cwd")}`'''
                if s["transport"] == "stdio"
                else f'''- URL: `{s.get("url")}`'''
            )
            for s in session.mcp_servers
        )
        if session.mcp_servers
        else ""
    }

{
        "Tools from these MCP servers are automatically loaded when the agent runs."
        if session.mcp_servers
        else ""
    }

## Usage

### Basic Usage

```python
from framework.runner import AgentRunner

# Load the agent
runner = AgentRunner.load("exports/{session.name}")

# Run with input
result = await runner.run({{"input_key": "value"}})

# Access results
print(result.output)
print(result.status)
```

### Input Schema

The agent's entry node `{export_data["graph"]["entry_node"]}` requires:
"""

    entry_node_obj = next((n for n in nodes if n.id == export_data["graph"]["entry_node"]), None)
    if entry_node_obj:
        for input_key in entry_node_obj.input_keys:
            readme += f"- `{input_key}` (required)\n"

    readme += f"""

### Output Schema

Terminal nodes: {", ".join(f"`{t}`" for t in export_data["graph"]["terminal_nodes"])}

## Version History

- **1.0.0** ({datetime.now().strftime("%Y-%m-%d")}): Initial release
  - {len(nodes)} nodes, {len(edges)} edges
  - Goal: {goal.name}
"""

    return readme


@mcp.tool()
def export_graph() -> str:
    """
    Export the validated graph as a GraphSpec for GraphExecutor.

    Exports the complete agent definition including nodes, edges, goal,
    and evaluation rules. The GraphExecutor runs the graph with dynamic
    edge traversal and routing logic.

    AUTOMATICALLY WRITES FILES TO DISK:
    - exports/{agent-name}/agent.json - Full agent specification
    - exports/{agent-name}/README.md - Documentation
    """
    from pathlib import Path

    session = get_session()

    # Validate first
    validation = json.loads(validate_graph())
    if not validation["valid"]:
        return json.dumps({"success": False, "errors": validation["errors"]})

    entry_node = validation["entry_node"]
    terminal_nodes = validation["terminal_nodes"]

    # Extract pause/resume configuration from validation
    pause_nodes = validation.get("pause_nodes", [])
    resume_entry_points = validation.get("resume_entry_points", [])

    # Build entry_points dict for pause/resume architecture
    entry_points = {}
    if entry_node:
        entry_points["start"] = entry_node

    # Add resume entry points with {pause_node}_resume naming convention
    if pause_nodes and resume_entry_points:
        # Strategy 1: Try to match by checking which resume node uses the pause node's outputs
        pause_to_resume = {}
        for pause_node_id in pause_nodes:
            pause_node = next((n for n in session.nodes if n.id == pause_node_id), None)
            if not pause_node:
                continue

            # Find resume nodes that read the outputs of this pause node
            for resume_node_id in resume_entry_points:
                resume_node = next((n for n in session.nodes if n.id == resume_node_id), None)
                if not resume_node:
                    continue

                # Check if resume node reads pause node's outputs
                shared_keys = set(pause_node.output_keys) & set(resume_node.input_keys)
                if shared_keys:
                    pause_to_resume[pause_node_id] = resume_node_id
                    break

        # Strategy 2: Fallback - pair sequentially if no match found
        unmatched_pause = [p for p in pause_nodes if p not in pause_to_resume]
        unmatched_resume = [r for r in resume_entry_points if r not in pause_to_resume.values()]
        for pause_id, resume_id in zip(unmatched_pause, unmatched_resume, strict=False):
            pause_to_resume[pause_id] = resume_id

        # Build entry_points dict
        for pause_id, resume_id in pause_to_resume.items():
            entry_points[f"{pause_id}_resume"] = resume_id

    # Build edges list
    edges_list = [
        {
            "id": edge.id,
            "source": edge.source,
            "target": edge.target,
            "condition": edge.condition.value,
            "condition_expr": edge.condition_expr,
            "priority": edge.priority,
            "input_mapping": edge.input_mapping,
        }
        for edge in session.edges
    ]

    # AUTO-GENERATE EDGES FROM ROUTER ROUTES
    # This prevents the common mistake of defining router routes but forgetting to create edges
    for node in session.nodes:
        if node.node_type == "router" and node.routes:
            for route_name, target_node in node.routes.items():
                # Check if edge already exists
                edge_exists = any(
                    e["source"] == node.id and e["target"] == target_node for e in edges_list
                )
                if not edge_exists:
                    # Auto-generate edge from router route
                    # Use on_success for most routes, on_failure for "fail"/"error"/"escalate"
                    condition = (
                        "on_failure"
                        if route_name in ["fail", "error", "escalate"]
                        else "on_success"
                    )
                    edges_list.append(
                        {
                            "id": f"{node.id}_to_{target_node}",
                            "source": node.id,
                            "target": target_node,
                            "condition": condition,
                            "condition_expr": None,
                            "priority": 0,
                            "input_mapping": {},
                        }
                    )

    # Build GraphSpec
    graph_spec = {
        "id": f"{session.name}-graph",
        "goal_id": session.goal.id,
        "version": "1.0.0",
        "entry_node": entry_node,
        "entry_points": entry_points,
        "pause_nodes": pause_nodes,
        "terminal_nodes": terminal_nodes,
        "nodes": [node.model_dump() for node in session.nodes],
        "edges": edges_list,
        "max_steps": 100,
        "max_retries_per_node": 3,
        "description": session.goal.description,
        "created_at": datetime.now().isoformat(),
    }

    # Collect all tools referenced by nodes
    all_tools = set()
    for node in session.nodes:
        all_tools.update(node.tools)

    # Build export data
    export_data = {
        "agent": {
            "id": session.name,
            "name": session.goal.name,
            "version": "1.0.0",
            "description": session.goal.description,
        },
        "graph": graph_spec,
        "goal": session.goal.model_dump(),
        "required_tools": list(all_tools),
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "node_count": len(session.nodes),
            "edge_count": len(edges_list),
        },
    }

    # Add enrichment if present in goal
    if hasattr(session.goal, "success_criteria"):
        enriched_criteria = []
        for criterion in session.goal.success_criteria:
            crit_dict = criterion.model_dump() if hasattr(criterion, "model_dump") else criterion
            enriched_criteria.append(crit_dict)
        export_data["goal"]["success_criteria"] = enriched_criteria

    # === WRITE FILES TO DISK ===
    # Create exports directory
    exports_dir = Path("exports") / session.name
    exports_dir.mkdir(parents=True, exist_ok=True)

    # Write agent.json
    agent_json_path = exports_dir / "agent.json"
    with atomic_write(agent_json_path) as f:
        json.dump(export_data, f, indent=2, default=str)

    # Generate README.md
    readme_content = _generate_readme(session, export_data, all_tools)
    readme_path = exports_dir / "README.md"
    with atomic_write(readme_path) as f:
        f.write(readme_content)

    # Write mcp_servers.json if MCP servers are configured
    mcp_servers_path = None
    mcp_servers_size = 0
    if session.mcp_servers:
        mcp_config = {"servers": session.mcp_servers}
        mcp_servers_path = exports_dir / "mcp_servers.json"
        with atomic_write(mcp_servers_path) as f:
            json.dump(mcp_config, f, indent=2)

        mcp_servers_size = mcp_servers_path.stat().st_size

    # Get file sizes
    agent_json_size = agent_json_path.stat().st_size
    readme_size = readme_path.stat().st_size

    files_written = {
        "agent_json": {
            "path": str(agent_json_path),
            "size_bytes": agent_json_size,
        },
        "readme": {
            "path": str(readme_path),
            "size_bytes": readme_size,
        },
    }

    if mcp_servers_path:
        files_written["mcp_servers"] = {
            "path": str(mcp_servers_path),
            "size_bytes": mcp_servers_size,
        }

    return json.dumps(
        {
            "success": True,
            "agent": export_data["agent"],
            "files_written": files_written,
            "graph": graph_spec,
            "goal": session.goal.model_dump(),
            "evaluation_rules": _evaluation_rules,
            "required_tools": list(all_tools),
            "node_count": len(session.nodes),
            "edge_count": len(edges_list),
            "mcp_servers_count": len(session.mcp_servers),
            "note": f"Agent exported to {exports_dir}. Files: agent.json, README.md"
            + (", mcp_servers.json" if session.mcp_servers else ""),
        },
        default=str,
        indent=2,
    )


@mcp.tool()
def get_session_status() -> str:
    """Get the current status of the build session."""
    session = get_session()
    return json.dumps(
        {
            "session_id": session.id,
            "name": session.name,
            "has_goal": session.goal is not None,
            "goal_name": session.goal.name if session.goal else None,
            "node_count": len(session.nodes),
            "edge_count": len(session.edges),
            "mcp_servers_count": len(session.mcp_servers),
            "nodes": [n.id for n in session.nodes],
            "edges": [(e.source, e.target) for e in session.edges],
            "mcp_servers": [s["name"] for s in session.mcp_servers],
        }
    )


@mcp.tool()
def add_mcp_server(
    name: Annotated[str, "Unique name for the MCP server"],
    transport: Annotated[str, "Transport type: 'stdio' or 'http'"],
    command: Annotated[str, "Command to run (for stdio transport)"] = "",
    args: Annotated[str, "JSON array of command arguments (for stdio)"] = "[]",
    cwd: Annotated[str, "Working directory (for stdio)"] = "",
    env: Annotated[str, "JSON object of environment variables (for stdio)"] = "{}",
    url: Annotated[str, "Server URL (for http transport)"] = "",
    headers: Annotated[str, "JSON object of HTTP headers (for http)"] = "{}",
    description: Annotated[str, "Description of the MCP server"] = "",
) -> str:
    """
    Register an MCP server as a tool source for this agent.

    The MCP server will be saved in mcp_servers.json when the agent is exported,
    and tools from this server will be available to the agent at runtime.

    Example for stdio:
        add_mcp_server(
            name="tools",
            transport="stdio",
            command="python",
            args='["mcp_server.py", "--stdio"]',
            cwd="../tools"
        )

    Example for http:
        add_mcp_server(
            name="remote-tools",
            transport="http",
            url="http://localhost:4001"
        )
    """
    session = get_session()

    # Validate transport
    if transport not in ["stdio", "http"]:
        return json.dumps(
            {
                "success": False,
                "error": f"Invalid transport '{transport}'. Must be 'stdio' or 'http'",
            }
        )

    # Check for duplicate
    if any(s["name"] == name for s in session.mcp_servers):
        return json.dumps({"success": False, "error": f"MCP server '{name}' already registered"})

    # Parse JSON inputs
    try:
        args_list = json.loads(args)
        env_dict = json.loads(env)
        headers_dict = json.loads(headers)
    except json.JSONDecodeError as e:
        return json.dumps({"success": False, "error": f"Invalid JSON: {e}"})

    # Validate required fields
    errors = []
    if transport == "stdio" and not command:
        errors.append("command is required for stdio transport")
    if transport == "http" and not url:
        errors.append("url is required for http transport")

    if errors:
        return json.dumps({"success": False, "errors": errors})

    # Build server config
    server_config = {
        "name": name,
        "transport": transport,
        "description": description,
    }

    if transport == "stdio":
        server_config["command"] = command
        server_config["args"] = args_list
        if cwd:
            server_config["cwd"] = cwd
        if env_dict:
            server_config["env"] = env_dict
    else:  # http
        server_config["url"] = url
        if headers_dict:
            server_config["headers"] = headers_dict

    # Try to connect and discover tools
    try:
        from framework.runner.mcp_client import MCPClient, MCPServerConfig

        mcp_config = MCPServerConfig(
            name=name,
            transport=transport,
            command=command if transport == "stdio" else None,
            args=args_list if transport == "stdio" else [],
            env=env_dict,
            cwd=cwd if cwd else None,
            url=url if transport == "http" else None,
            headers=headers_dict,
            description=description,
        )

        with MCPClient(mcp_config) as client:
            tools = client.list_tools()
            tool_names = [t.name for t in tools]

            # Add to session
            session.mcp_servers.append(server_config)
            _save_session(session)  # Auto-save

            return json.dumps(
                {
                    "success": True,
                    "server": server_config,
                    "tools_discovered": len(tool_names),
                    "tools": tool_names,
                    "total_mcp_servers": len(session.mcp_servers),
                    "note": (
                        f"MCP server '{name}' registered with {len(tool_names)} tools. "
                        "These tools can now be used in llm_tool_use nodes."
                    ),
                },
                indent=2,
            )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "error": f"Failed to connect to MCP server: {str(e)}",
                "suggestion": "Check that the command/url is correct and the server is accessible",
            }
        )


@mcp.tool()
def list_mcp_servers() -> str:
    """List all registered MCP servers for this agent."""
    session = get_session()

    if not session.mcp_servers:
        return json.dumps(
            {
                "mcp_servers": [],
                "total": 0,
                "note": "No MCP servers registered. Use add_mcp_server to add tool sources.",
            }
        )

    return json.dumps(
        {
            "mcp_servers": session.mcp_servers,
            "total": len(session.mcp_servers),
        },
        indent=2,
    )


@mcp.tool()
def list_mcp_tools(
    server_name: Annotated[str, "Name of the MCP server to list tools from"] = "",
) -> str:
    """
    List tools available from registered MCP servers.

    If server_name is provided, lists tools from that specific server.
    Otherwise, lists all tools from all registered servers.
    """
    session = get_session()

    if not session.mcp_servers:
        return json.dumps({"success": False, "error": "No MCP servers registered"})

    # Filter servers if name provided
    servers_to_query = session.mcp_servers
    if server_name:
        servers_to_query = [s for s in session.mcp_servers if s["name"] == server_name]
        if not servers_to_query:
            return json.dumps({"success": False, "error": f"MCP server '{server_name}' not found"})

    all_tools = {}

    for server_config in servers_to_query:
        try:
            from framework.runner.mcp_client import MCPClient, MCPServerConfig

            mcp_config = MCPServerConfig(
                name=server_config["name"],
                transport=server_config["transport"],
                command=server_config.get("command"),
                args=server_config.get("args", []),
                env=server_config.get("env", {}),
                cwd=server_config.get("cwd"),
                url=server_config.get("url"),
                headers=server_config.get("headers", {}),
                description=server_config.get("description", ""),
            )

            with MCPClient(mcp_config) as client:
                tools = client.list_tools()

                all_tools[server_config["name"]] = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": list(t.input_schema.get("properties", {}).keys()),
                    }
                    for t in tools
                ]

        except Exception as e:
            all_tools[server_config["name"]] = {"error": f"Failed to connect: {str(e)}"}

    total_tools = sum(len(tools) if isinstance(tools, list) else 0 for tools in all_tools.values())

    return json.dumps(
        {
            "success": True,
            "tools_by_server": all_tools,
            "total_tools": total_tools,
            "note": "Use these tool names in the 'tools' parameter when adding llm_tool_use nodes",
        },
        indent=2,
    )


@mcp.tool()
def remove_mcp_server(
    name: Annotated[str, "Name of the MCP server to remove"],
) -> str:
    """Remove a registered MCP server."""
    session = get_session()

    for i, server in enumerate(session.mcp_servers):
        if server["name"] == name:
            session.mcp_servers.pop(i)
            _save_session(session)  # Auto-save
            return json.dumps(
                {"success": True, "removed": name, "remaining_servers": len(session.mcp_servers)}
            )

    return json.dumps({"success": False, "error": f"MCP server '{name}' not found"})


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
        # Show routing decision
        result["routing_options"] = node_spec.routes
        result["simulation"] = "Router would evaluate routes based on input and select target node"

    elif node_spec.node_type in ("llm_generate", "llm_tool_use"):
        # Show what prompt would be sent
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
        "inputs_available": {k: input_data.get(k, "<not provided>") for k in node_spec.input_keys},
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
                # In dry run, assume success path
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
            "recommendation": "Review the execution trace above. Does this flow achieve the goal?",
        },
        indent=2,
    )


# =============================================================================
# FLEXIBLE EXECUTION TOOLS (Worker-Judge Pattern)
# =============================================================================

# Storage for evaluation rules
_evaluation_rules: list[dict] = []


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
    # Compute what keys each step can access (from dependencies' outputs)

    # Build output map (step_id -> expected_outputs)
    step_outputs: dict[str, set[str]] = {}
    for step in steps:
        step_outputs[step.get("id", "")] = set(step.get("expected_outputs", []))

    # Compute available context for each step in topological order
    available_context: dict[str, set[str]] = {}
    computed = set()
    remaining = set(step_ids)

    # Get initial context keys from plan.context
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

            # Can compute if all dependencies are computed
            if all(d in computed for d in deps):
                # Collect outputs from all dependencies (transitive)
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
            # Check $variable references
            if isinstance(input_value, str) and input_value.startswith("$"):
                var_name = input_value[1:]  # Remove $ prefix
                if var_name not in available:
                    missing_vars.append(var_name)

        if missing_vars:
            if not deps:
                # Entry step - inputs must come from initial context
                context_warnings.append(
                    f"Step '{step_id}' requires ${missing_vars} from initial context. "
                    f"Ensure these are provided when running the agent: {missing_vars}"
                )
            else:
                # Find which step could provide each missing var
                suggestions = []
                for var in missing_vars:
                    producers = [s.get("id") for s in steps if var in s.get("expected_outputs", [])]
                    if producers:
                        suggestions.append(f"${var} is produced by {producers} - add as dependency")
                    else:
                        suggestions.append(
                            f"${var} is not produced by any step - add a step that outputs '{var}'"
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

        # Execute first ready step (in real execution, could be parallel)
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


# =============================================================================
# TESTING TOOLS (Goal-Based Evaluation)
# =============================================================================


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

    # Derive agent_path from session if not provided
    if not agent_path and _session:
        agent_path = f"exports/{_session.name}"

    path, err = _validate_agent_path(agent_path)
    if err:
        return err

    agent_module = _get_agent_module_from_path(path)

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
            "agent_path": str(path),
            "agent_module": agent_module,
            "output_file": f"{str(path)}/tests/test_constraints.py",
            "constraints": [c.model_dump() for c in goal.constraints] if goal.constraints else [],
            "constraints_formatted": constraints_formatted,
            "test_guidelines": {
                "max_tests": 5,
                "naming_convention": "test_constraint_<constraint_id>_<scenario>",
                "required_decorator": "@pytest.mark.asyncio",
                "required_fixture": "mock_mode",
                "agent_call_pattern": "await default_agent.run(input_dict, mock_mode=mock_mode)",
                "result_type": "ExecutionResult with .success, .output (dict), .error",
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
                "Use file_header as start, add test functions per test_template. "
                "Generate up to 5 tests covering the most critical constraints."
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

    # Derive agent_path from session if not provided
    if not agent_path and _session:
        agent_path = f"exports/{_session.name}"

    path, err = _validate_agent_path(agent_path)
    if err:
        return err

    agent_module = _get_agent_module_from_path(path)

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
        description=f"Tests for success criteria defined in goal: {goal.name}",
        agent_module=agent_module,
    )

    # Return guidelines + data for Claude to write tests directly
    return json.dumps(
        {
            "goal_id": goal_id,
            "agent_path": str(path),
            "agent_module": agent_module,
            "output_file": f"{str(path)}/tests/test_success_criteria.py",
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
                "naming_convention": "test_success_<criteria_id>_<scenario>",
                "required_decorator": "@pytest.mark.asyncio",
                "required_fixture": "mock_mode",
                "agent_call_pattern": "await default_agent.run(input_dict, mock_mode=mock_mode)",
                "result_type": "ExecutionResult with .success, .output (dict), .error",
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
                "Use file_header as start, add test functions per test_template. "
                "Generate up to 12 tests covering the most critical success criteria."
            ),
        }
    )


@mcp.tool()
def run_tests(
    goal_id: Annotated[str, "ID of the goal to test"],
    agent_path: Annotated[str, "Path to the agent export folder"],
    test_types: Annotated[
        str, 'JSON array of test types: ["constraint", "success", "edge_case", "all"]'
    ] = '["all"]',
    parallel: Annotated[
        int, "Number of parallel workers (-1 for auto/CPU count, 0 to disable)"
    ] = -1,
    fail_fast: Annotated[bool, "Stop on first failure (-x flag)"] = False,
    verbose: Annotated[bool, "Verbose output (-v flag)"] = True,
) -> str:
    """
    Run pytest on agent test files.

    Tests are located at {agent_path}/tests/test_*.py
    By default, tests run in parallel using pytest-xdist with auto-detected worker count.
    Returns pass/fail summary with detailed results parsed from pytest output.
    """
    import re
    import subprocess

    path, err = _validate_agent_path(agent_path)
    if err:
        return err

    tests_dir = path / "tests"

    if not tests_dir.exists():
        return json.dumps(
            {
                "goal_id": goal_id,
                "error": f"Tests directory not found: {tests_dir}",
                "hint": (
                    "Use generate_constraint_tests or generate_success_tests "
                    "to get guidelines, then write tests with Write tool"
                ),
            }
        )

    # Parse test types
    try:
        types_list = json.loads(test_types)
    except json.JSONDecodeError:
        types_list = ["all"]

    # Build pytest command
    cmd = ["pytest"]

    # Add test path(s) based on type filter
    if "all" in types_list:
        cmd.append(str(tests_dir))
    else:
        type_to_file = {
            "constraint": "test_constraints.py",
            "success": "test_success_criteria.py",
            "outcome": "test_success_criteria.py",  # alias
            "edge_case": "test_edge_cases.py",
        }
        for t in types_list:
            if t in type_to_file:
                test_file = tests_dir / type_to_file[t]
                if test_file.exists():
                    cmd.append(str(test_file))

    # Add flags
    if verbose:
        cmd.append("-v")
    if fail_fast:
        cmd.append("-x")

    # Parallel execution (default: auto-detect CPU count)
    if parallel == -1:
        cmd.extend(["-n", "auto"])  # pytest-xdist auto-detects CPU count
    elif parallel > 0:
        cmd.extend(["-n", str(parallel)])

    # Add short traceback and quiet summary
    cmd.append("--tb=short")

    # Set PYTHONPATH to project root so agents can import from core.framework
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    env["PYTHONPATH"] = f"{project_root}:{pythonpath}"

    # Run pytest
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
            env=env,
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {
                "goal_id": goal_id,
                "error": "Test execution timed out after 10 minutes",
                "command": " ".join(cmd),
            }
        )
    except Exception as e:
        return json.dumps(
            {
                "goal_id": goal_id,
                "error": f"Failed to run pytest: {e}",
                "command": " ".join(cmd),
            }
        )

    # Parse pytest output
    output = result.stdout + "\n" + result.stderr

    # Extract summary line (e.g., "5 passed, 2 failed in 1.23s")
    summary_match = re.search(r"=+ ([\d\w,\s]+) in [\d.]+s =+", output)
    summary_text = summary_match.group(1) if summary_match else "unknown"

    # Parse passed/failed counts
    passed = 0
    failed = 0
    skipped = 0
    error = 0

    passed_match = re.search(r"(\d+) passed", summary_text)
    if passed_match:
        passed = int(passed_match.group(1))

    failed_match = re.search(r"(\d+) failed", summary_text)
    if failed_match:
        failed = int(failed_match.group(1))

    skipped_match = re.search(r"(\d+) skipped", summary_text)
    if skipped_match:
        skipped = int(skipped_match.group(1))

    error_match = re.search(r"(\d+) error", summary_text)
    if error_match:
        error = int(error_match.group(1))

    total = passed + failed + skipped + error

    # Extract individual test results
    test_results = []
    # Match lines like: "test_constraints.py::test_constraint_foo PASSED"
    test_pattern = re.compile(r"([\w/]+\.py)::(\w+)\s+(PASSED|FAILED|SKIPPED|ERROR)")
    for match in test_pattern.finditer(output):
        test_results.append(
            {
                "file": match.group(1),
                "test_name": match.group(2),
                "status": match.group(3).lower(),
            }
        )

    # Extract failure details
    failures = []
    # Match FAILURES section
    failure_section = re.search(
        r"=+ FAILURES =+(.+?)(?:=+ (?:short test summary|ERRORS|warnings) =+|$)", output, re.DOTALL
    )
    if failure_section:
        failure_text = failure_section.group(1)
        # Split by test name headers
        failure_blocks = re.split(r"_+ (test_\w+) _+", failure_text)
        for i in range(1, len(failure_blocks), 2):
            if i + 1 < len(failure_blocks):
                test_name = failure_blocks[i]
                details = failure_blocks[i + 1].strip()[:500]  # Limit detail length
                failures.append(
                    {
                        "test_name": test_name,
                        "details": details,
                    }
                )

    return json.dumps(
        {
            "goal_id": goal_id,
            "overall_passed": result.returncode == 0,
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "errors": error,
                "pass_rate": f"{(passed / total * 100):.1f}%" if total > 0 else "0%",
            },
            "command": " ".join(cmd),
            "return_code": result.returncode,
            "test_results": test_results,
            "failures": failures,
            "raw_output": output[-2000:] if len(output) > 2000 else output,  # Last 2000 chars
        }
    )


@mcp.tool()
def debug_test(
    goal_id: Annotated[str, "ID of the goal"],
    test_name: Annotated[str, "Name of the test function (e.g., test_constraint_foo)"],
    agent_path: Annotated[str, "Path to agent export folder (e.g., 'exports/my_agent')"] = "",
) -> str:
    """
    Run a specific test with verbose output for debugging.

    Re-runs the test with pytest -vvs to capture full output.
    Returns detailed failure information and suggestions.
    """
    import re
    import subprocess

    # Derive agent_path from session if not provided
    if not agent_path and _session:
        agent_path = f"exports/{_session.name}"

    path, err = _validate_agent_path(agent_path)
    if err:
        return err

    tests_dir = path / "tests"

    if not tests_dir.exists():
        return json.dumps(
            {
                "goal_id": goal_id,
                "error": f"Tests directory not found: {tests_dir}",
            }
        )

    # Find which file contains the test
    test_file = None
    for py_file in tests_dir.glob("test_*.py"):
        content = py_file.read_text()
        if f"def {test_name}" in content or f"async def {test_name}" in content:
            test_file = py_file
            break

    if not test_file:
        return json.dumps(
            {
                "goal_id": goal_id,
                "error": f"Test '{test_name}' not found in {tests_dir}",
                "hint": "Use list_tests to see available tests",
            }
        )

    # Run specific test with verbose output
    cmd = [
        "pytest",
        f"{test_file}::{test_name}",
        "-vvs",  # Very verbose with stdout
        "--tb=long",  # Full traceback
    ]

    # Set PYTHONPATH to project root (same as run_tests)
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    env["PYTHONPATH"] = f"{project_root}:{pythonpath}"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout for single test
            env=env,
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {
                "goal_id": goal_id,
                "test_name": test_name,
                "error": "Test execution timed out after 2 minutes",
            }
        )
    except Exception as e:
        return json.dumps(
            {
                "goal_id": goal_id,
                "test_name": test_name,
                "error": f"Failed to run pytest: {e}",
            }
        )

    output = result.stdout + "\n" + result.stderr
    passed = result.returncode == 0

    # Categorize error if failed
    error_category = None
    suggestion = None

    if not passed:
        output_lower = output.lower()

        if any(
            p in output_lower for p in ["typeerror", "attributeerror", "keyerror", "valueerror"]
        ):
            error_category = "IMPLEMENTATION_ERROR"
            suggestion = "Fix the bug in agent code - check the traceback for the exact location"
        elif any(p in output_lower for p in ["assertionerror", "assert", "expected"]):
            error_category = "ASSERTION_FAILURE"
            suggestion = (
                "The test assertion failed - fix the agent logic or update test expectation"
            )
        elif any(p in output_lower for p in ["timeout", "timed out"]):
            error_category = "TIMEOUT"
            suggestion = (
                "The test or agent took too long - check for infinite loops or slow operations"
            )
        elif any(p in output_lower for p in ["importerror", "modulenotfounderror"]):
            error_category = "IMPORT_ERROR"
            suggestion = (
                "Missing module or incorrect import path - check your agent package structure"
            )
        elif any(p in output_lower for p in ["connectionerror", "api", "rate limit"]):
            error_category = "API_ERROR"
            suggestion = "External API issue - check API keys and network connectivity"
        else:
            error_category = "UNKNOWN"
            suggestion = "Review the traceback and test output for clues"

    # Extract the assertion/error message
    error_message = None
    error_match = re.search(r"(AssertionError|Error|Exception):\s*(.+?)(?:\n|$)", output)
    if error_match:
        error_message = error_match.group(2).strip()

    return json.dumps(
        {
            "goal_id": goal_id,
            "test_name": test_name,
            "test_file": str(test_file),
            "passed": passed,
            "error_category": error_category,
            "error_message": error_message,
            "suggestion": suggestion,
            "command": " ".join(cmd),
            "output": output[-3000:] if len(output) > 3000 else output,  # Last 3000 chars
        },
        indent=2,
    )


@mcp.tool()
def list_tests(
    goal_id: Annotated[str, "ID of the goal"],
    agent_path: Annotated[str, "Path to agent export folder (e.g., 'exports/my_agent')"] = "",
) -> str:
    """
    List tests for an agent by scanning Python test files.

    Returns test names and their locations from {agent_path}/tests/test_*.py
    """
    import ast

    # Derive agent_path from session if not provided
    if not agent_path and _session:
        agent_path = f"exports/{_session.name}"

    path, err = _validate_agent_path(agent_path)
    if err:
        return err

    tests_dir = path / "tests"

    if not tests_dir.exists():
        return json.dumps(
            {
                "goal_id": goal_id,
                "agent_path": agent_path,
                "total": 0,
                "tests": [],
                "hint": (
                    "No tests directory found. Generate tests with "
                    "generate_constraint_tests or generate_success_tests"
                ),
            }
        )

    # Scan all test files
    tests = []
    for test_file in sorted(tests_dir.glob("test_*.py")):
        try:
            content = test_file.read_text()
            tree = ast.parse(content)

            # Find all async function definitions that start with "test_"
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    if node.name.startswith("test_"):
                        # Determine test type from filename
                        if "constraint" in test_file.name:
                            test_type = "constraint"
                        elif "success" in test_file.name:
                            test_type = "success_criteria"
                        elif "edge" in test_file.name:
                            test_type = "edge_case"
                        else:
                            test_type = "unknown"

                        # Extract docstring
                        docstring = ast.get_docstring(node) or ""

                        tests.append(
                            {
                                "test_name": node.name,
                                "file": test_file.name,
                                "file_path": str(test_file),
                                "line": node.lineno,
                                "test_type": test_type,
                                "is_async": isinstance(node, ast.AsyncFunctionDef),
                                "description": docstring[:200] if docstring else None,
                            }
                        )
        except SyntaxError as e:
            tests.append(
                {
                    "file": test_file.name,
                    "error": f"Syntax error: {e}",
                }
            )
        except Exception as e:
            tests.append(
                {
                    "file": test_file.name,
                    "error": str(e),
                }
            )

    # Group by type
    by_type = {}
    for t in tests:
        ttype = t.get("test_type", "unknown")
        if ttype not in by_type:
            by_type[ttype] = 0
        by_type[ttype] += 1

    return json.dumps(
        {
            "goal_id": goal_id,
            "agent_path": agent_path,
            "tests_dir": str(tests_dir),
            "total": len(tests),
            "by_type": by_type,
            "tests": tests,
            "run_command": f"pytest {tests_dir} -v",
        }
    )


# =============================================================================
# PLAN LOADING AND EXECUTION
# =============================================================================


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


@mcp.tool()
def load_exported_plan(
    plan_json: Annotated[str, "JSON string from export_graph() output"],
) -> str:
    """
    Validate and load an exported plan, returning its structure.

    Use this to verify a plan can be loaded before execution.
    """
    try:
        plan = load_plan_from_json(plan_json)
        return json.dumps(
            {
                "success": True,
                "plan_id": plan.id,
                "goal_id": plan.goal_id,
                "description": plan.description,
                "step_count": len(plan.steps),
                "steps": [
                    {
                        "id": s.id,
                        "description": s.description,
                        "action_type": s.action.action_type.value,
                        "dependencies": s.dependencies,
                    }
                    for s in plan.steps
                ],
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# =============================================================================
# CREDENTIAL STORE TOOLS
# =============================================================================


def _get_credential_store():
    """Get a CredentialStore that checks encrypted files and env vars.

    Uses CompositeStorage: encrypted file storage (primary) with env var fallback.
    This ensures credentials stored via `store_credential` AND env vars are both found.
    """
    from framework.credentials import CredentialStore
    from framework.credentials.storage import CompositeStorage, EncryptedFileStorage, EnvVarStorage

    # Build env var mapping from CREDENTIAL_SPECS for the fallback
    env_mapping: dict[str, str] = {}
    try:
        from aden_tools.credentials import CREDENTIAL_SPECS

        for name, spec in CREDENTIAL_SPECS.items():
            cred_id = spec.credential_id or name
            env_mapping[cred_id] = spec.env_var
    except ImportError:
        pass

    storage = CompositeStorage(
        primary=EncryptedFileStorage(),
        fallbacks=[EnvVarStorage(env_mapping=env_mapping)],
    )
    return CredentialStore(storage=storage)


@mcp.tool()
def check_missing_credentials(
    agent_path: Annotated[str, "Path to the exported agent directory (e.g., 'exports/my-agent')"],
) -> str:
    """
    Detect missing credentials for an agent by inspecting its tools and node types.

    Returns a list of missing credentials with env var names, descriptions, and help URLs.
    Use this before running or testing an agent to identify what needs to be configured.
    """
    try:
        from aden_tools.credentials import CREDENTIAL_SPECS

        from framework.runner import AgentRunner

        runner = AgentRunner.load(agent_path)
        runner.validate()

        store = _get_credential_store()
        info = runner.info()
        node_types = list({node.node_type for node in runner.graph.nodes})

        # Build reverse mappings: tool/node_type -> credential name
        tool_to_cred: dict[str, str] = {}
        node_type_to_cred: dict[str, str] = {}
        for cred_name, spec in CREDENTIAL_SPECS.items():
            for tool_name in spec.tools:
                tool_to_cred[tool_name] = cred_name
            for nt in spec.node_types:
                node_type_to_cred[nt] = cred_name

        # Gather missing credentials (tools + node types), deduplicated
        seen: set[str] = set()
        all_missing = []

        for name_list, mapping in [
            (info.required_tools, tool_to_cred),
            (node_types, node_type_to_cred),
        ]:
            for item_name in name_list:
                cred_name = mapping.get(item_name)
                if cred_name is None or cred_name in seen:
                    continue
                seen.add(cred_name)
                spec = CREDENTIAL_SPECS[cred_name]
                cred_id = spec.credential_id or cred_name
                if spec.required and not store.is_available(cred_id):
                    all_missing.append(
                        {
                            "credential_name": cred_name,
                            "env_var": spec.env_var,
                            "description": spec.description,
                            "help_url": spec.help_url,
                            "tools": spec.tools,
                        }
                    )

        # Also check what's already set
        available = []
        for name, spec in CREDENTIAL_SPECS.items():
            if name in seen:
                continue
            cred_id = spec.credential_id or name
            if store.is_available(cred_id):
                relevant_tools = [t for t in spec.tools if t in info.required_tools]
                relevant_nodes = [n for n in spec.node_types if n in node_types]
                if relevant_tools or relevant_nodes:
                    available.append(
                        {
                            "credential_name": name,
                            "env_var": spec.env_var,
                            "description": spec.description,
                            "status": "available",
                        }
                    )

        return json.dumps(
            {
                "agent": agent_path,
                "missing": all_missing,
                "available": available,
                "total_missing": len(all_missing),
                "ready": len(all_missing) == 0,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def store_credential(
    credential_name: Annotated[
        str, "Logical credential name (e.g., 'hubspot', 'brave_search', 'anthropic')"
    ],
    credential_value: Annotated[str, "The secret value to store (API key, token, etc.)"],
    key_name: Annotated[
        str, "Key name within the credential (e.g., 'api_key', 'access_token')"
    ] = "api_key",
    display_name: Annotated[str, "Human-readable name (e.g., 'HubSpot Access Token')"] = "",
) -> str:
    """
    Store a credential securely in the encrypted credential store at ~/.hive/credentials.

    Uses Fernet encryption (AES-128-CBC + HMAC). Requires HIVE_CREDENTIAL_KEY env var.
    """
    try:
        from pydantic import SecretStr

        from framework.credentials import CredentialKey, CredentialObject

        store = _get_credential_store()

        if not display_name:
            display_name = credential_name.replace("_", " ").title()

        cred = CredentialObject(
            id=credential_name,
            name=display_name,
            keys={
                key_name: CredentialKey(
                    name=key_name,
                    value=SecretStr(credential_value),
                )
            },
        )
        store.save_credential(cred)

        return json.dumps(
            {
                "success": True,
                "credential": credential_name,
                "key": key_name,
                "location": "~/.hive/credentials",
                "encrypted": True,
            }
        )
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
def list_stored_credentials() -> str:
    """
    List all credentials currently stored in the encrypted credential store.

    Returns credential IDs and metadata (never returns secret values).
    """
    try:
        store = _get_credential_store()
        credential_ids = store.list_credentials()

        credentials = []
        for cred_id in credential_ids:
            try:
                cred = store.get_credential(cred_id)
                credentials.append(
                    {
                        "id": cred.id,
                        "name": cred.name,
                        "keys": list(cred.keys.keys()),
                        "created_at": cred.created_at.isoformat() if cred.created_at else None,
                    }
                )
            except Exception:
                credentials.append({"id": cred_id, "error": "Could not load"})

        return json.dumps(
            {
                "count": len(credentials),
                "credentials": credentials,
                "location": "~/.hive/credentials",
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def delete_stored_credential(
    credential_name: Annotated[str, "Logical credential name to delete (e.g., 'hubspot')"],
) -> str:
    """
    Delete a credential from the encrypted credential store.
    """
    try:
        store = _get_credential_store()
        deleted = store.delete_credential(credential_name)
        return json.dumps(
            {
                "success": deleted,
                "credential": credential_name,
                "message": f"Credential '{credential_name}' deleted"
                if deleted
                else f"Credential '{credential_name}' not found",
            }
        )
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
def verify_credentials(
    agent_path: Annotated[str, "Path to the exported agent directory (e.g., 'exports/my-agent')"],
) -> str:
    """
    Verify that all required credentials are configured for an agent.

    Runs the full validation pipeline and reports pass/fail status.
    Use this after storing credentials to confirm the agent is ready to run.
    """
    try:
        from framework.runner import AgentRunner

        runner = AgentRunner.load(agent_path)
        validation = runner.validate()

        return json.dumps(
            {
                "agent": agent_path,
                "ready": not validation.missing_credentials,
                "missing_credentials": validation.missing_credentials,
                "warnings": validation.warnings,
                "errors": validation.errors,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    mcp.run(transport="stdio")
