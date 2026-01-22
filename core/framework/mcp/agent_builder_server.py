"""
MCP Server for Agent Building Tools

Exposes tools for building goal-driven agents via the Model Context Protocol.

Usage:
    python -m framework.mcp.agent_builder_server
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

from mcp.server import FastMCP

from framework.graph import Goal, SuccessCriterion, Constraint, NodeSpec, EdgeSpec, EdgeCondition
from framework.graph.edge import GraphSpec

# Testing framework imports
from framework.testing.test_case import Test, ApprovalStatus, TestType
from framework.testing.test_storage import TestStorage
from framework.testing.constraint_gen import ConstraintTestGenerator
from framework.testing.success_gen import SuccessCriteriaTestGenerator
from framework.testing.approval_types import ApprovalRequest, ApprovalAction
from framework.testing.debug_tool import DebugTool
from framework.testing.parallel import AgentFactory


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
                constraints=[
                    Constraint(**c) for c in goal_data.get("constraints", [])
                ],
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
    with open(session_file, "w") as f:
        json.dump(session.to_dict(), f, indent=2, default=str)

    # Update active session pointer
    with open(ACTIVE_SESSION_FILE, "w") as f:
        f.write(session.id)


def _load_session(session_id: str) -> BuildSession:
    """Load session from disk."""
    session_file = SESSIONS_DIR / f"{session_id}.json"
    if not session_file.exists():
        raise ValueError(f"Session '{session_id}' not found")

    with open(session_file, "r") as f:
        data = json.load(f)

    return BuildSession.from_dict(data)


def _load_active_session() -> BuildSession | None:
    """Load the active session if one exists."""
    if not ACTIVE_SESSION_FILE.exists():
        return None

    try:
        with open(ACTIVE_SESSION_FILE, "r") as f:
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
    return json.dumps({
        "session_id": _session.id,
        "name": name,
        "status": "created",
        "persisted": True,
    })


@mcp.tool()
def list_sessions() -> str:
    """List all saved agent building sessions."""
    _ensure_sessions_dir()

    sessions = []
    if SESSIONS_DIR.exists():
        for session_file in SESSIONS_DIR.glob("*.json"):
            try:
                with open(session_file, "r") as f:
                    data = json.load(f)
                    sessions.append({
                        "session_id": data["session_id"],
                        "name": data["name"],
                        "created_at": data.get("created_at"),
                        "last_modified": data.get("last_modified"),
                        "node_count": len(data.get("nodes", [])),
                        "edge_count": len(data.get("edges", [])),
                        "has_goal": data.get("goal") is not None,
                    })
            except Exception:
                pass  # Skip corrupted files

    # Check which session is currently active
    active_id = None
    if ACTIVE_SESSION_FILE.exists():
        try:
            with open(ACTIVE_SESSION_FILE, "r") as f:
                active_id = f.read().strip()
        except Exception:
            pass

    return json.dumps({
        "sessions": sorted(sessions, key=lambda s: s["last_modified"], reverse=True),
        "total": len(sessions),
        "active_session_id": active_id,
    }, indent=2)


@mcp.tool()
def load_session_by_id(session_id: Annotated[str, "ID of the session to load"]) -> str:
    """Load a previously saved agent building session by its ID."""
    global _session

    try:
        _session = _load_session(session_id)

        # Update active session pointer
        with open(ACTIVE_SESSION_FILE, "w") as f:
            f.write(session_id)

        return json.dumps({
            "success": True,
            "session_id": _session.id,
            "name": _session.name,
            "node_count": len(_session.nodes),
            "edge_count": len(_session.edges),
            "has_goal": _session.goal is not None,
            "created_at": _session.created_at,
            "last_modified": _session.last_modified,
            "message": f"Session '{_session.name}' loaded successfully"
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@mcp.tool()
def delete_session(session_id: Annotated[str, "ID of the session to delete"]) -> str:
    """Delete a saved agent building session."""
    global _session

    session_file = SESSIONS_DIR / f"{session_id}.json"
    if not session_file.exists():
        return json.dumps({
            "success": False,
            "error": f"Session '{session_id}' not found"
        })

    try:
        # Remove session file
        session_file.unlink()

        # Clear active session if it was the deleted one
        if _session and _session.id == session_id:
            _session = None

        if ACTIVE_SESSION_FILE.exists():
            with open(ACTIVE_SESSION_FILE, "r") as f:
                active_id = f.read().strip()
                if active_id == session_id:
                    ACTIVE_SESSION_FILE.unlink()

        return json.dumps({
            "success": True,
            "deleted_session_id": session_id,
            "message": f"Session '{session_id}' deleted successfully"
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@mcp.tool()
def set_goal(
    goal_id: Annotated[str, "Unique identifier for the goal"],
    name: Annotated[str, "Human-readable name"],
    description: Annotated[str, "What the agent should accomplish"],
    success_criteria: Annotated[str, "JSON array of success criteria objects with id, description, metric, target, weight"],
    constraints: Annotated[str, "JSON array of constraint objects with id, description, constraint_type, category"] = "[]",
) -> str:
    """Define the goal for the agent. Goals are the source of truth - they define what success looks like."""
    session = get_session()

    # Parse JSON inputs
    criteria_list = json.loads(success_criteria)
    constraint_list = json.loads(constraints)

    # Convert to proper objects
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

    # Validate
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

    _save_session(session)  # Auto-save

    return json.dumps({
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
                    "description": "Goal looks good, proceed to adding nodes"
                },
                {
                    "label": "✗ Reject & Modify",
                    "description": "Need to adjust goal criteria or constraints"
                },
                {
                    "label": "⏸ Pause & Review",
                    "description": "I need more time to review this goal"
                }
            ]
        }
    }, default=str)


def _validate_tool_credentials(tools_list: list[str]) -> dict | None:
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
                cred_errors.append({
                    "credential": cred_name,
                    "env_var": spec.env_var,
                    "tools_affected": affected_tools,
                    "help_url": spec.help_url,
                    "description": spec.description,
                })

            return {
                "valid": False,
                "errors": [f"Missing credentials for tools: {[e['env_var'] for e in cred_errors]}"],
                "missing_credentials": cred_errors,
                "action_required": "Add the credentials to your .env file and retry",
                "example": f"Add to .env:\n{cred_errors[0]['env_var']}=your_key_here",
                "message": "Cannot add node: missing API credentials. Add them to .env and retry this command.",
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
    routes: Annotated[str, "JSON object mapping conditions to target node IDs for router nodes"] = "{}",
) -> str:
    """Add a node to the agent graph. Nodes are units of work that process inputs and produce outputs."""
    session = get_session()

    # Parse JSON inputs
    input_keys_list = json.loads(input_keys)
    output_keys_list = json.loads(output_keys)
    tools_list = json.loads(tools)
    routes_dict = json.loads(routes)

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

    return json.dumps({
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
                    "description": f"Node '{name}' looks good, continue building"
                },
                {
                    "label": "✗ Reject & Modify",
                    "description": "Need to change node configuration"
                },
                {
                    "label": "⏸ Pause & Review",
                    "description": "I need more time to review this node"
                }
            ]
        }
    }, default=str)


@mcp.tool()
def add_edge(
    edge_id: Annotated[str, "Unique identifier for the edge"],
    source: Annotated[str, "Source node ID"],
    target: Annotated[str, "Target node ID"],
    condition: Annotated[str, "When to traverse: always, on_success, on_failure, conditional"] = "on_success",
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

    return json.dumps({
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
                    "description": f"Edge connection looks good"
                },
                {
                    "label": "✗ Reject & Modify",
                    "description": "Need to change edge condition or targets"
                },
                {
                    "label": "⏸ Pause & Review",
                    "description": "I need more time to review this edge"
                }
            ]
        }
    }, default=str)


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

    # Validate credentials for new tools BEFORE updating
    if tools:
        tools_list = json.loads(tools)
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
    if input_keys:
        node.input_keys = json.loads(input_keys)
    if output_keys:
        node.output_keys = json.loads(output_keys)
    if system_prompt:
        node.system_prompt = system_prompt
    if tools:
        node.tools = json.loads(tools)
    if routes:
        node.routes = json.loads(routes)

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

    return json.dumps({
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
                    "description": f"Updated node '{node.name}' looks good"
                },
                {
                    "label": "✗ Reject & Modify",
                    "description": "Need to change node configuration"
                },
                {
                    "label": "⏸ Pause & Review",
                    "description": "I need more time to review this update"
                }
            ]
        }
    }, default=str)


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
    session.edges = [
        e for e in session.edges
        if not (e.source == node_id or e.target == node_id)
    ]

    _save_session(session)  # Auto-save

    return json.dumps({
        "valid": True,
        "deleted_node": removed_node.model_dump(),
        "removed_edges": removed_edges,
        "total_nodes": len(session.nodes),
        "total_edges": len(session.edges),
        "message": f"Node '{node_id}' and {len(removed_edges)} connected edge(s) removed"
    }, default=str)


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

    return json.dumps({
        "valid": True,
        "deleted_edge": removed_edge.model_dump(),
        "total_edges": len(session.edges),
        "message": f"Edge '{edge_id}' removed: {removed_edge.source} → {removed_edge.target}"
    }, default=str)


@mcp.tool()
def validate_graph() -> str:
    """Validate the complete graph. Checks for unreachable nodes, missing connections, and context flow."""
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
    resume_entry_points = [n.id for n in session.nodes if "RESUME" in n.description.upper() and "ENTRY" in n.description.upper()]

    is_pause_resume_agent = len(pause_nodes) > 0 or len(resume_entry_points) > 0

    if is_pause_resume_agent:
        warnings.append(f"Pause/resume architecture detected. Pause nodes: {pause_nodes}, Resume entry points: {resume_entry_points}")

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
                    warnings.append(f"Nodes unreachable from primary entry (may be resume-only nodes): {unreachable_non_resume}")
            else:
                errors.append(f"Unreachable nodes: {unreachable}")

    # === CONTEXT FLOW VALIDATION ===
    # Build dependency map (node_id -> list of nodes it depends on)
    dependencies: dict[str, list[str]] = {node.id: [] for node in session.nodes}
    for edge in session.edges:
        if edge.target in dependencies:
            dependencies[edge.target].append(edge.source)

    # Build output map (node_id -> keys it produces)
    node_outputs: dict[str, set[str]] = {
        node.id: set(node.output_keys) for node in session.nodes
    }

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
    remaining = set(n.id for n in session.nodes)
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
                    f"Resume entry node '{node_id}' requires inputs {missing} from resumed invocation context. "
                    f"These will be provided by the runtime when resuming (e.g., user's answers)."
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
                        f"Resume entry node '{node_id}' expects external inputs {unproduced_external} from resumed invocation. "
                        f"These will be injected by the runtime when the user responds."
                    )

                if other_missing:
                    # Still need to check other keys
                    suggestions = []
                    for key in other_missing:
                        producers = [n.id for n in session.nodes if key in n.output_keys]
                        if producers:
                            suggestions.append(f"'{key}' is produced by {producers} - ensure edge exists")
                        else:
                            suggestions.append(f"'{key}' is not produced - add node or include in external inputs")

                    context_errors.append(
                        f"Resume node '{node_id}' requires {other_missing} but dependencies {deps} don't provide them. "
                        f"Suggestions: {'; '.join(suggestions)}"
                    )
            else:
                # Non-resume node or no external input keys - standard validation
                suggestions = []
                for key in missing:
                    producers = [n.id for n in session.nodes if key in n.output_keys]
                    if producers:
                        suggestions.append(f"'{key}' is produced by {producers} - add dependency edge")
                    else:
                        suggestions.append(f"'{key}' is not produced by any node - add a node that outputs it")

                context_errors.append(
                    f"Node '{node_id}' requires {missing} but dependencies {deps} don't provide them. "
                    f"Suggestions: {'; '.join(suggestions)}"
                )

    errors.extend(context_errors)
    warnings.extend(context_warnings)

    return json.dumps({
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
        "context_flow": {
            node_id: list(keys) for node_id, keys in available_context.items()
        } if available_context else None,
    })


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
        crit_dict = criterion.model_dump() if hasattr(criterion, 'model_dump') else criterion.__dict__
        criteria_section.append(
            f"**{crit_dict.get('description', 'N/A')}** (weight {crit_dict.get('weight', 1.0)})\n"
            f"- Metric: {crit_dict.get('metric', 'N/A')}\n"
            f"- Target: {crit_dict.get('target', 'N/A')}"
        )

    # Build constraints section
    constraints_section = []
    for constraint in goal.constraints:
        const_dict = constraint.model_dump() if hasattr(constraint, 'model_dump') else constraint.__dict__
        constraints_section.append(
            f"**{const_dict.get('description', 'N/A')}** ({const_dict.get('constraint_type', 'hard')})\n"
            f"- Category: {const_dict.get('category', 'N/A')}"
        )

    readme = f"""# {goal.name}

**Version**: 1.0.0
**Type**: Multi-node agent
**Created**: {datetime.now().strftime('%Y-%m-%d')}

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
        readme += f"- `{edge.source}` → `{edge.target}` (condition: {edge.condition.value if hasattr(edge.condition, 'value') else edge.condition})\n"

    readme += f"""

## Goal Criteria

### Success Criteria

{chr(10).join(criteria_section)}

### Constraints

{chr(10).join(constraints_section) if constraints_section else "None defined"}

## Required Tools

{chr(10).join(f"- `{tool}`" for tool in sorted(all_tools)) if all_tools else "No tools required"}

{"## MCP Tool Sources" if session.mcp_servers else ""}

{chr(10).join(f'''### {s["name"]} ({s["transport"]})
{s.get("description", "")}

**Configuration:**
''' + (f'''- Command: `{s.get("command")}`
- Args: `{s.get("args")}`
- Working Directory: `{s.get("cwd")}`''' if s["transport"] == "stdio" else f'''- URL: `{s.get("url")}`''') for s in session.mcp_servers) if session.mcp_servers else ""}

{"Tools from these MCP servers are automatically loaded when the agent runs." if session.mcp_servers else ""}

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

Terminal nodes: {', '.join(f'`{t}`' for t in export_data["graph"]["terminal_nodes"])}

## Version History

- **1.0.0** ({datetime.now().strftime('%Y-%m-%d')}): Initial release
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
    import os
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
        for pause_id, resume_id in zip(unmatched_pause, unmatched_resume):
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
                    e["source"] == node.id and e["target"] == target_node
                    for e in edges_list
                )
                if not edge_exists:
                    # Auto-generate edge from router route
                    # Use on_success for most routes, on_failure for "fail"/"error"/"escalate"
                    condition = "on_failure" if route_name in ["fail", "error", "escalate"] else "on_success"
                    edges_list.append({
                        "id": f"{node.id}_to_{target_node}",
                        "source": node.id,
                        "target": target_node,
                        "condition": condition,
                        "condition_expr": None,
                        "priority": 0,
                        "input_mapping": {},
                    })

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
    if hasattr(session.goal, 'success_criteria'):
        enriched_criteria = []
        for criterion in session.goal.success_criteria:
            crit_dict = criterion.model_dump() if hasattr(criterion, 'model_dump') else criterion
            enriched_criteria.append(crit_dict)
        export_data["goal"]["success_criteria"] = enriched_criteria

    # === WRITE FILES TO DISK ===
    # Create exports directory
    exports_dir = Path("exports") / session.name
    exports_dir.mkdir(parents=True, exist_ok=True)

    # Write agent.json
    agent_json_path = exports_dir / "agent.json"
    with open(agent_json_path, "w") as f:
        json.dump(export_data, f, indent=2, default=str)

    # Generate README.md
    readme_content = _generate_readme(session, export_data, all_tools)
    readme_path = exports_dir / "README.md"
    with open(readme_path, "w") as f:
        f.write(readme_content)

    # Write mcp_servers.json if MCP servers are configured
    mcp_servers_path = None
    mcp_servers_size = 0
    if session.mcp_servers:
        mcp_config = {
            "servers": session.mcp_servers
        }
        mcp_servers_path = exports_dir / "mcp_servers.json"
        with open(mcp_servers_path, "w") as f:
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

    return json.dumps({
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
        "note": f"Agent exported to {exports_dir}. Files: agent.json, README.md" + (", mcp_servers.json" if session.mcp_servers else ""),
    }, default=str, indent=2)


@mcp.tool()
def get_session_status() -> str:
    """Get the current status of the build session."""
    session = get_session()
    return json.dumps({
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
    })


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
        return json.dumps({
            "success": False,
            "error": f"Invalid transport '{transport}'. Must be 'stdio' or 'http'"
        })

    # Check for duplicate
    if any(s["name"] == name for s in session.mcp_servers):
        return json.dumps({
            "success": False,
            "error": f"MCP server '{name}' already registered"
        })

    # Parse JSON inputs
    try:
        args_list = json.loads(args)
        env_dict = json.loads(env)
        headers_dict = json.loads(headers)
    except json.JSONDecodeError as e:
        return json.dumps({
            "success": False,
            "error": f"Invalid JSON: {e}"
        })

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

            return json.dumps({
                "success": True,
                "server": server_config,
                "tools_discovered": len(tool_names),
                "tools": tool_names,
                "total_mcp_servers": len(session.mcp_servers),
                "note": f"MCP server '{name}' registered with {len(tool_names)} tools. These tools can now be used in llm_tool_use nodes.",
            }, indent=2)

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to connect to MCP server: {str(e)}",
            "suggestion": "Check that the command/url is correct and the server is accessible"
        })


@mcp.tool()
def list_mcp_servers() -> str:
    """List all registered MCP servers for this agent."""
    session = get_session()

    if not session.mcp_servers:
        return json.dumps({
            "mcp_servers": [],
            "total": 0,
            "note": "No MCP servers registered. Use add_mcp_server to add tool sources."
        })

    return json.dumps({
        "mcp_servers": session.mcp_servers,
        "total": len(session.mcp_servers),
    }, indent=2)


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
        return json.dumps({
            "success": False,
            "error": "No MCP servers registered"
        })

    # Filter servers if name provided
    servers_to_query = session.mcp_servers
    if server_name:
        servers_to_query = [s for s in session.mcp_servers if s["name"] == server_name]
        if not servers_to_query:
            return json.dumps({
                "success": False,
                "error": f"MCP server '{server_name}' not found"
            })

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
            all_tools[server_config["name"]] = {
                "error": f"Failed to connect: {str(e)}"
            }

    total_tools = sum(len(tools) if isinstance(tools, list) else 0 for tools in all_tools.values())

    return json.dumps({
        "success": True,
        "tools_by_server": all_tools,
        "total_tools": total_tools,
        "note": "Use these tool names in the 'tools' parameter when adding llm_tool_use nodes",
    }, indent=2)


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
            return json.dumps({
                "success": True,
                "removed": name,
                "remaining_servers": len(session.mcp_servers)
            })

    return json.dumps({
        "success": False,
        "error": f"MCP server '{name}' not found"
    })


@mcp.tool()
def test_node(
    node_id: Annotated[str, "ID of the node to test"],
    test_input: Annotated[str, "JSON object with test input data for the node"],
    mock_llm_response: Annotated[str, "Mock LLM response to simulate (for testing without API calls)"] = "",
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
            result["simulation"] = f"LLM would receive prompt and produce response"
        else:
            result["simulation"] = "LLM would be called with the system prompt and input data"

    elif node_spec.node_type == "function":
        result["simulation"] = "Function node would execute deterministic logic"

    # Show memory state after (simulated)
    result["expected_memory_state"] = {
        "inputs_available": {k: input_data.get(k, "<not provided>") for k in node_spec.input_keys},
        "outputs_to_write": node_spec.output_keys,
    }

    return json.dumps({
        "success": True,
        "test_result": result,
        "recommendation": "Review the simulation above. Does this node behavior match your intent?",
    }, indent=2)


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
        return json.dumps({
            "success": False,
            "error": "Graph is not valid",
            "validation_errors": validation["errors"],
        })

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
            execution_trace.append({
                "step": steps,
                "error": f"Node '{current_node_id}' not found",
            })
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
            step_info["prompt_preview"] = current_node.system_prompt[:200] + "..." if current_node.system_prompt and len(current_node.system_prompt) > 200 else current_node.system_prompt
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

    return json.dumps({
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
    }, indent=2)


# =============================================================================
# FLEXIBLE EXECUTION TOOLS (Worker-Judge Pattern)
# =============================================================================

# Storage for evaluation rules
_evaluation_rules: list[dict] = []


@mcp.tool()
def add_evaluation_rule(
    rule_id: Annotated[str, "Unique identifier for the rule"],
    description: Annotated[str, "Human-readable description of what this rule checks"],
    condition: Annotated[str, "Python expression evaluated with result, step, goal context. E.g., 'result.get(\"success\") == True'"],
    action: Annotated[str, "Action when rule matches: accept, retry, replan, escalate"],
    feedback_template: Annotated[str, "Template for feedback message, can use {result}, {step}"] = "",
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
        return json.dumps({
            "success": False,
            "error": f"Invalid action '{action}'. Must be one of: {valid_actions}",
        })

    # Check for duplicate
    if any(r["id"] == rule_id for r in _evaluation_rules):
        return json.dumps({
            "success": False,
            "error": f"Rule '{rule_id}' already exists",
        })

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

    return json.dumps({
        "success": True,
        "rule": rule,
        "total_rules": len(_evaluation_rules),
    })


@mcp.tool()
def list_evaluation_rules() -> str:
    """List all configured evaluation rules for the HybridJudge."""
    return json.dumps({
        "rules": _evaluation_rules,
        "total": len(_evaluation_rules),
    })


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
    steps: Annotated[str, "JSON array of plan steps with id, description, action, inputs, expected_outputs, dependencies"],
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
    - dependencies: List of step IDs that must complete first

    Example step:
    {
        "id": "step_1",
        "description": "Fetch user data",
        "action": {"action_type": "tool_use", "tool_name": "get_user", "tool_args": {"user_id": "$user_id"}},
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

    return json.dumps({
        "success": True,
        "plan": plan,
        "step_count": len(steps_list),
        "note": "Plan created. Use execute_plan to run it with the Worker-Judge loop.",
    }, indent=2)


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
                        suggestions.append(f"${var} is not produced by any step - add a step that outputs '{var}'")

                context_errors.append(
                    f"Step '{step_id}' references ${missing_vars} but dependencies {deps} don't provide them. "
                    f"Suggestions: {'; '.join(suggestions)}"
                )

    errors.extend(context_errors)
    warnings.extend(context_warnings)

    return json.dumps({
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "step_count": len(steps),
        "context_flow": {
            step_id: list(keys) for step_id, keys in available_context.items()
        } if available_context else None,
    })


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
        return json.dumps({
            "success": False,
            "error": "Plan is not valid",
            "validation_errors": validation["errors"],
        })

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

        execution_order.append({
            "iteration": iteration,
            "step_id": step_id,
            "description": step.get("description"),
            "action_type": step.get("action", {}).get("action_type"),
            "dependencies_met": list(step.get("dependencies", [])),
            "parallel_candidates": [s.get("id") for s in ready[1:]],
        })

        completed.add(step_id)

    remaining = [s.get("id") for s in steps if s.get("id") not in completed]

    return json.dumps({
        "success": True,
        "execution_order": execution_order,
        "steps_simulated": len(execution_order),
        "remaining_steps": remaining,
        "plan_complete": len(remaining) == 0,
        "note": "This is a simulation. Actual execution may differ based on step results and judge decisions.",
    }, indent=2)


# =============================================================================
# TESTING TOOLS (Goal-Based Evaluation)
# =============================================================================

# Session storage for pending tests (not yet persisted)
_pending_tests: dict[str, list[Test]] = {}

# Default storage path for tests
DEFAULT_TEST_STORAGE_PATH = Path("data/tests")


@mcp.tool()
def generate_constraint_tests(
    goal_id: Annotated[str, "ID of the goal to generate tests for"],
    goal_json: Annotated[str, """JSON string of the Goal object. Constraint fields:
- id: string (required)
- description: string (required)
- constraint_type: "hard" or "soft" (required)
- category: string (optional, default: "general")
- check: string (optional, how to validate: "llm_judge", expression, or function name)"""],
) -> str:
    """
    Generate constraint tests for a goal.

    Returns proposals for user approval. Tests are NOT persisted until approved.
    """
    try:
        goal = Goal.model_validate_json(goal_json)
    except Exception as e:
        return json.dumps({"error": f"Invalid goal JSON: {e}"})

    # Get LLM provider
    try:
        from framework.llm import AnthropicProvider
        llm = AnthropicProvider()
    except Exception as e:
        return json.dumps({"error": f"Failed to initialize LLM: {e}"})

    # Generate tests
    generator = ConstraintTestGenerator(llm)
    tests = generator.generate(goal)

    # Store as pending (not persisted yet)
    _pending_tests[goal_id] = tests

    return json.dumps({
        "goal_id": goal_id,
        "generated_count": len(tests),
        "tests": [
            {
                "id": t.id,
                "test_name": t.test_name,
                "parent_criteria_id": t.parent_criteria_id,
                "description": t.description,
                "confidence": t.llm_confidence,
                "test_code_preview": t.test_code[:500] + "..." if len(t.test_code) > 500 else t.test_code,
            }
            for t in tests
        ],
        "next_step": "Call approve_tests to approve, modify, or reject each test",
    })


@mcp.tool()
def generate_success_tests(
    goal_id: Annotated[str, "ID of the goal to generate tests for"],
    goal_json: Annotated[str, "JSON string of the Goal object"],
    node_names: Annotated[str, "Comma-separated list of agent node names"] = "",
    tool_names: Annotated[str, "Comma-separated list of available tool names"] = "",
) -> str:
    """
    Generate success criteria tests for a goal.

    Should be called during Eval stage after agent exists.
    Returns proposals for user approval.
    """
    try:
        goal = Goal.model_validate_json(goal_json)
    except Exception as e:
        return json.dumps({"error": f"Invalid goal JSON: {e}"})

    # Get LLM provider
    try:
        from framework.llm import AnthropicProvider
        llm = AnthropicProvider()
    except Exception as e:
        return json.dumps({"error": f"Failed to initialize LLM: {e}"})

    # Parse node/tool names
    nodes = [n.strip() for n in node_names.split(",") if n.strip()]
    tools = [t.strip() for t in tool_names.split(",") if t.strip()]

    # Generate tests
    generator = SuccessCriteriaTestGenerator(llm)
    tests = generator.generate(goal, node_names=nodes, tool_names=tools)

    # Add to pending (may have constraint tests already)
    if goal_id in _pending_tests:
        _pending_tests[goal_id].extend(tests)
    else:
        _pending_tests[goal_id] = tests

    return json.dumps({
        "goal_id": goal_id,
        "generated_count": len(tests),
        "tests": [
            {
                "id": t.id,
                "test_name": t.test_name,
                "parent_criteria_id": t.parent_criteria_id,
                "description": t.description,
                "confidence": t.llm_confidence,
                "test_code_preview": t.test_code[:500] + "..." if len(t.test_code) > 500 else t.test_code,
            }
            for t in tests
        ],
        "next_step": "Call approve_tests to approve, modify, or reject each test",
    })


@mcp.tool()
def approve_tests(
    goal_id: Annotated[str, "ID of the goal"],
    approvals: Annotated[str, "JSON array of approval decisions"],
) -> str:
    """
    Approve, reject, or modify generated tests.

    Approvals format:
    [
        {"test_id": "...", "action": "approve"},
        {"test_id": "...", "action": "modify", "modified_code": "..."},
        {"test_id": "...", "action": "reject", "reason": "..."},
        {"test_id": "...", "action": "skip"}
    ]

    Actions: approve, modify (requires modified_code), reject (requires reason), skip
    """
    if goal_id not in _pending_tests:
        return json.dumps({"error": f"No pending tests for goal {goal_id}"})

    try:
        approvals_list = json.loads(approvals)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid approvals JSON: {e}"})

    # Create storage
    storage = TestStorage(DEFAULT_TEST_STORAGE_PATH / goal_id)

    # Build approval requests
    requests = []
    for a in approvals_list:
        try:
            action = ApprovalAction(a.get("action", "skip"))
            requests.append(ApprovalRequest(
                test_id=a["test_id"],
                action=action,
                modified_code=a.get("modified_code"),
                reason=a.get("reason"),
                approved_by="mcp_user",
            ))
        except (KeyError, ValueError) as e:
            return json.dumps({"error": f"Invalid approval entry: {e}"})

    # Find and save approved tests
    pending = {t.id: t for t in _pending_tests[goal_id]}

    results = []
    for req in requests:
        test = pending.get(req.test_id)
        if not test:
            results.append({"test_id": req.test_id, "error": "Not found in pending"})
            continue

        if req.action == ApprovalAction.APPROVE:
            test.approve(req.approved_by)
            storage.save_test(test)
            results.append({"test_id": req.test_id, "status": "approved"})

        elif req.action == ApprovalAction.MODIFY:
            if req.modified_code:
                test.modify(req.modified_code, req.approved_by)
                storage.save_test(test)
                results.append({"test_id": req.test_id, "status": "modified"})
            else:
                results.append({"test_id": req.test_id, "error": "modified_code required"})

        elif req.action == ApprovalAction.REJECT:
            test.reject(req.reason or "No reason provided")
            storage.save_test(test)
            results.append({"test_id": req.test_id, "status": "rejected"})

        elif req.action == ApprovalAction.SKIP:
            results.append({"test_id": req.test_id, "status": "skipped"})

    # Clear pending for processed tests
    processed_ids = {r["test_id"] for r in results if "error" not in r}
    _pending_tests[goal_id] = [t for t in _pending_tests[goal_id] if t.id not in processed_ids]

    # Clean up if empty
    if not _pending_tests[goal_id]:
        del _pending_tests[goal_id]

    return json.dumps({"goal_id": goal_id, "results": results})


@mcp.tool()
def run_tests(
    goal_id: Annotated[str, "ID of the goal to test"],
    agent_path: Annotated[str, "Path to the agent export folder"],
    test_types: Annotated[str, 'JSON array of test types: ["constraint", "outcome", "edge_case", "all"]'] = '["all"]',
    parallel: Annotated[int, "Number of parallel workers (0 for sequential)"] = 0,
    fail_fast: Annotated[bool, "Stop on first failure"] = False,
) -> str:
    """
    Run evaluation tests for a goal.

    Returns pass/fail summary with detailed results for each test.
    """
    from framework.testing.parallel import ParallelTestRunner, ParallelConfig

    # Parse test types
    try:
        types_list = json.loads(test_types)
    except json.JSONDecodeError:
        types_list = ["all"]

    # Load storage
    storage = TestStorage(DEFAULT_TEST_STORAGE_PATH / goal_id)

    # Get approved tests
    tests = storage.get_approved_tests(goal_id)

    # Filter by type if not "all"
    if "all" not in types_list:
        type_map = {
            "constraint": TestType.CONSTRAINT,
            "outcome": TestType.SUCCESS_CRITERIA,
            "edge_case": TestType.EDGE_CASE,
        }
        filter_types = {type_map.get(t) for t in types_list if t in type_map}
        tests = [t for t in tests if t.test_type in filter_types]

    if not tests:
        return json.dumps({
            "goal_id": goal_id,
            "error": "No approved tests found",
            "hint": "Generate and approve tests first using generate_constraint_tests and approve_tests",
        })

    # Configure runner
    config = ParallelConfig(
        num_workers=parallel if parallel > 0 else 1,
        fail_fast=fail_fast,
    )

    # Run tests - use AgentFactory for picklable parallel execution
    runner = ParallelTestRunner(config, storage)
    result = runner.run_all(
        goal_id=goal_id,
        agent_factory=AgentFactory(agent_path),
        tests=tests,
    )

    return json.dumps({
        "goal_id": goal_id,
        "overall_passed": result.all_passed,
        "summary": {
            "total": result.total,
            "passed": result.passed,
            "failed": result.failed,
            "pass_rate": f"{result.pass_rate:.1%}",
        },
        "duration_ms": result.duration_ms,
        "results": [r.summary_dict() for r in result.results],
    })


@mcp.tool()
def debug_test(
    goal_id: Annotated[str, "ID of the goal"],
    test_id: Annotated[str, "ID of the failed test"],
    run_id: Annotated[str, "Optional Runtime run ID for detailed logs"] = "",
) -> str:
    """
    Get detailed debug info for a failed test.

    Includes error categorization, logs, and fix suggestions.
    """
    storage = TestStorage(DEFAULT_TEST_STORAGE_PATH / goal_id)

    # Optionally load runtime storage
    runtime_storage = None
    try:
        from framework.storage.backend import FileStorage
        runtime_storage = FileStorage(f"data/runtime/{goal_id}")
    except Exception:
        pass

    debug_tool = DebugTool(storage, runtime_storage)
    info = debug_tool.analyze(goal_id, test_id, run_id or None)

    return json.dumps(info.to_dict(), indent=2, default=str)


@mcp.tool()
def list_tests(
    goal_id: Annotated[str, "ID of the goal"],
    status: Annotated[str, "Filter by approval status: pending, approved, modified, rejected, all"] = "all",
) -> str:
    """
    List tests for a goal.

    Returns test metadata without full code (use debug_test for details).
    """
    storage = TestStorage(DEFAULT_TEST_STORAGE_PATH / goal_id)
    tests = storage.get_tests_by_goal(goal_id)

    # Filter by status
    if status != "all":
        try:
            filter_status = ApprovalStatus(status)
            tests = [t for t in tests if t.approval_status == filter_status]
        except ValueError:
            pass

    return json.dumps({
        "goal_id": goal_id,
        "total": len(tests),
        "tests": [
            {
                "id": t.id,
                "test_name": t.test_name,
                "test_type": t.test_type.value,
                "parent_criteria_id": t.parent_criteria_id,
                "approval_status": t.approval_status.value,
                "last_result": t.last_result,
                "confidence": t.llm_confidence,
            }
            for t in tests
        ],
    })


@mcp.tool()
def get_pending_tests(
    goal_id: Annotated[str, "ID of the goal"],
) -> str:
    """
    Get pending tests awaiting approval.

    Returns tests that have been generated but not yet approved.
    """
    if goal_id not in _pending_tests:
        return json.dumps({
            "goal_id": goal_id,
            "pending_count": 0,
            "tests": [],
        })

    tests = _pending_tests[goal_id]
    return json.dumps({
        "goal_id": goal_id,
        "pending_count": len(tests),
        "tests": [
            {
                "id": t.id,
                "test_name": t.test_name,
                "test_type": t.test_type.value,
                "parent_criteria_id": t.parent_criteria_id,
                "description": t.description,
                "confidence": t.llm_confidence,
                "test_code": t.test_code,
                "input": t.input,
                "expected_output": t.expected_output,
            }
            for t in tests
        ],
    })


# =============================================================================
# PLAN LOADING AND EXECUTION
# =============================================================================

def load_plan_from_json(plan_json: str | dict) -> "Plan":
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
        return json.dumps({
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
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    mcp.run()
