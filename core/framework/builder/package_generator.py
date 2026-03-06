"""
Package Generator for Agent Building Tools

Generates agent packages from build sessions. Extracted from the MCP server
so it can be used as a standalone CLI or imported as a library.

Usage:
    uv run python -m framework.builder.package_generator <agent_name> <agent_json_path>
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Project root resolution.  This file lives at core/framework/builder/package_generator.py,
# so the project root (where exports/ lives) is four parents up.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Ensure exports/ is on sys.path so AgentRunner can import agent modules.
_exports_dir = _PROJECT_ROOT / "exports"
if _exports_dir.is_dir() and str(_exports_dir) not in sys.path:
    sys.path.insert(0, str(_exports_dir))
del _exports_dir

from pydantic import ValidationError  # noqa: E402

from framework.graph import (  # noqa: E402
    Constraint,
    EdgeCondition,
    EdgeSpec,
    Goal,
    NodeSpec,
    SuccessCriterion,
)

from framework.utils.io import atomic_write  # noqa: E402


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
        self.loop_config: dict = {}  # LoopConfig parameters for EventLoopNodes
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
            "loop_config": self.loop_config,
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

        # Restore loop config
        session.loop_config = data.get("loop_config", {})

        return session


# Global session
_session = None  # type: BuildSession | None


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

    with open(session_file, encoding="utf-8") as f:
        data = json.load(f)

    return BuildSession.from_dict(data)


def _load_active_session() -> BuildSession | None:
    """Load the active session if one exists."""
    if not ACTIVE_SESSION_FILE.exists():
        return None

    try:
        with open(ACTIVE_SESSION_FILE, encoding="utf-8") as f:
            session_id = f.read().strip()

        if session_id:
            return _load_session(session_id)
    except Exception as e:
        logging.warning("Failed to load active session: %s", e)

    return None


def get_session() -> BuildSession:
    global _session

    # Try to load active session if no session in memory
    if _session is None:
        _session = _load_active_session()

    if _session is None:
        raise ValueError("No active session. Call create_session first.")

    return _session


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

        # Start from ALL entry candidates (nodes without incoming edges).
        # This handles both pause/resume agents and async entry point agents
        # where multiple nodes have no incoming edges (e.g., a primary entry
        # node and an event-driven entry node).
        to_visit = list(entry_candidates)

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
    # Build dependency maps — separate forward edges from feedback edges.
    # Feedback edges (priority < 0) create cycles; they must not block the
    # topological sort.  Context they carry arrives on *revisits*, not on
    # the first execution of a node.
    feedback_edge_ids = {e.id for e in session.edges if e.priority < 0}
    forward_dependencies: dict[str, list[str]] = {node.id: [] for node in session.nodes}
    feedback_sources: dict[str, list[str]] = {node.id: [] for node in session.nodes}
    # Combined map kept for error-message generation (all deps)
    dependencies: dict[str, list[str]] = {node.id: [] for node in session.nodes}

    for edge in session.edges:
        if edge.target not in forward_dependencies:
            continue
        dependencies[edge.target].append(edge.source)
        if edge.id in feedback_edge_ids:
            feedback_sources[edge.target].append(edge.source)
        else:
            forward_dependencies[edge.target].append(edge.source)

    # Build output map (node_id -> keys it produces)
    node_outputs: dict[str, set[str]] = {node.id: set(node.output_keys) for node in session.nodes}

    # Compute available context for each node (what keys it can read)
    # Using topological order on the forward-edge DAG
    available_context: dict[str, set[str]] = {}
    computed = set()
    nodes_by_id = {n.id: n for n in session.nodes}

    # Initial context keys that will be provided at runtime
    # These are typically the inputs like lead_id, gtm_table_id, etc.
    # Entry nodes can only read from initial context
    initial_context_keys: set[str] = set()

    # Compute in topological order (forward edges only — feedback edges
    # don't block, since their context arrives on revisits)
    remaining = {n.id for n in session.nodes}
    max_iterations = len(session.nodes) * 2

    for _ in range(max_iterations):
        if not remaining:
            break

        for node_id in list(remaining):
            fwd_deps = forward_dependencies.get(node_id, [])

            # Can compute if all FORWARD dependencies are computed
            if all(d in computed for d in fwd_deps):
                # Collect outputs from all forward dependencies
                available = set(initial_context_keys)
                for dep_id in fwd_deps:
                    available.update(node_outputs.get(dep_id, set()))
                    available.update(available_context.get(dep_id, set()))

                # Also include context from already-computed feedback
                # sources (bonus, not blocking)
                for fb_src in feedback_sources.get(node_id, []):
                    if fb_src in computed:
                        available.update(node_outputs.get(fb_src, set()))
                        available.update(available_context.get(fb_src, set()))

                available_context[node_id] = available
                computed.add(node_id)
                remaining.remove(node_id)
                break

    # Check each node's input requirements
    context_errors = []
    context_warnings = []
    missing_inputs: dict[str, list[str]] = {}
    feedback_only_inputs: dict[str, list[str]] = {}

    for node in session.nodes:
        available = available_context.get(node.id, set())

        for input_key in node.input_keys:
            if input_key not in available:
                # Check if this input is provided by a feedback source
                fb_provides = set()
                for fb_src in feedback_sources.get(node.id, []):
                    fb_provides.update(node_outputs.get(fb_src, set()))
                    fb_provides.update(available_context.get(fb_src, set()))

                if input_key in fb_provides:
                    # Input arrives via feedback edge — warn, don't error
                    if node.id not in feedback_only_inputs:
                        feedback_only_inputs[node.id] = []
                    feedback_only_inputs[node.id].append(input_key)
                else:
                    if node.id not in missing_inputs:
                        missing_inputs[node.id] = []
                    missing_inputs[node.id].append(input_key)

    # Warn about feedback-only inputs (available on revisits, not first run)
    for node_id, fb_keys in feedback_only_inputs.items():
        fb_srcs = feedback_sources.get(node_id, [])
        context_warnings.append(
            f"Node '{node_id}' input(s) {fb_keys} are only provided via "
            f"feedback edge(s) from {fb_srcs}. These will be available on "
            f"revisits but not on the first execution."
        )

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

    # === EventLoopNode-specific validation ===
    from collections import defaultdict

    # Detect fan-out: multiple ON_SUCCESS edges from same source
    outgoing_success: dict[str, list[str]] = defaultdict(list)
    for edge in session.edges:
        cond = edge.condition.value if hasattr(edge.condition, "value") else edge.condition
        if cond == "on_success":
            outgoing_success[edge.source].append(edge.target)

    for source_id, targets in outgoing_success.items():
        if len(targets) > 1:
            # Client-facing fan-out: cannot target multiple client_facing nodes
            cf_targets = [
                t for t in targets if any(n.id == t and n.client_facing for n in session.nodes)
            ]
            if len(cf_targets) > 1:
                errors.append(
                    f"Fan-out from '{source_id}' targets multiple client_facing "
                    f"nodes: {cf_targets}. Only one branch may be client-facing."
                )

            # Output key overlap on parallel event_loop nodes
            el_targets = [
                t
                for t in targets
                if any(n.id == t and n.node_type == "event_loop" for n in session.nodes)
            ]
            if len(el_targets) > 1:
                seen_keys: dict[str, str] = {}
                for nid in el_targets:
                    node_obj = next((n for n in session.nodes if n.id == nid), None)
                    if node_obj:
                        for key in node_obj.output_keys:
                            if key in seen_keys:
                                errors.append(
                                    f"Fan-out from '{source_id}': event_loop "
                                    f"nodes '{seen_keys[key]}' and '{nid}' both "
                                    f"write to output_key '{key}'. Parallel "
                                    "nodes must have disjoint output_keys."
                                )
                            else:
                                seen_keys[key] = nid

    # Feedback loop validation: targets should allow re-visits
    for edge in session.edges:
        if edge.priority < 0:
            target_node = next((n for n in session.nodes if n.id == edge.target), None)
            if target_node and target_node.max_node_visits <= 1:
                warnings.append(
                    f"Feedback edge '{edge.id}' targets '{edge.target}' "
                    f"which has max_node_visits={target_node.max_node_visits}. "
                    "Consider setting max_node_visits > 1."
                )

    # nullable_output_keys must be subset of output_keys
    for node in session.nodes:
        if node.nullable_output_keys:
            invalid = [k for k in node.nullable_output_keys if k not in node.output_keys]
            if invalid:
                errors.append(
                    f"Node '{node.id}': nullable_output_keys {invalid} "
                    f"must be a subset of output_keys {node.output_keys}"
                )

    # Node count warning (prefer 3-6 nodes)
    node_count = len(session.nodes)
    if node_count < 3:
        warnings.append(
            f"Agent has only {node_count} node(s). "
            "Consider adding nodes for better separation of concerns (recommend 3-6)."
        )
    elif node_count > 6:
        warnings.append(
            f"Agent has {node_count} nodes. "
            "Consider consolidating to 3-6 nodes for simpler architecture."
        )

    # Worker nodes should be autonomous; queen owns user interaction.
    el_nodes = [n for n in session.nodes if n.node_type == "event_loop"]
    cf_el_nodes = [n for n in el_nodes if n.client_facing]
    if cf_el_nodes:
        errors.append(
            "event_loop nodes must not be client_facing in worker graphs. "
            f"Set client_facing=False for: {[n.id for n in cf_el_nodes]} and use "
            "escalate for handoff to queen."
        )

    # Collect summary info
    event_loop_nodes = [n.id for n in session.nodes if n.node_type == "event_loop"]
    client_facing_nodes = [n.id for n in session.nodes if n.client_facing]
    feedback_edges = [e.id for e in session.edges if e.priority < 0]

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
            "event_loop_nodes": event_loop_nodes,
            "client_facing_nodes": client_facing_nodes,
            "feedback_edges": feedback_edges,
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
        if node.client_facing:
            node_info.append("   - Client-facing: Yes (blocks for user input)")
        if node.nullable_output_keys:
            node_info.append(f"   - Nullable outputs: `{', '.join(node.nullable_output_keys)}`")
        if node.max_node_visits > 1:
            node_info.append(f"   - Max visits: {node.max_node_visits}")
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
        priority_note = f", priority={edge.priority}" if edge.priority != 0 else ""
        feedback_note = " **[FEEDBACK]**" if edge.priority < 0 else ""
        readme += (
            f"- `{edge.source}` → `{edge.target}` "
            f"(condition: {cond}{priority_note}){feedback_note}\n"
        )

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


def export_graph() -> str:
    """
    Export the validated graph as a GraphSpec for GraphExecutor.

    Exports the complete agent definition including nodes, edges, and goal.
    The GraphExecutor runs the graph with dynamic edge traversal and routing logic.

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

    # Include loop config if configured
    if session.loop_config:
        graph_spec["loop_config"] = session.loop_config

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

    # Auto-add GCU MCP server if any node uses the gcu type
    has_gcu_nodes = any(n.node_type == "gcu" for n in session.nodes)
    if has_gcu_nodes:
        from framework.graph.gcu import GCU_MCP_SERVER_CONFIG, GCU_SERVER_NAME

        if not any(s.get("name") == GCU_SERVER_NAME for s in session.mcp_servers):
            session.mcp_servers.append(dict(GCU_MCP_SERVER_CONFIG))

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


def _snake_to_camel(name: str) -> str:
    """Convert snake_case to CamelCase.  e.g. 'twitter_outreach_agent' -> 'TwitterOutreachAgent'."""
    return "".join(word.capitalize() for word in name.split("_"))


def _node_var_name(node_id: str) -> str:
    """Convert node id to a Python variable name.  e.g. 'check-inbox' -> 'check_inbox_node'."""
    return node_id.replace("-", "_") + "_node"


def _generate_config_py(session: BuildSession) -> str:
    """Generate config.py content."""
    goal_name = session.goal.name if session.goal else session.name
    goal_desc = session.goal.description if session.goal else ""
    return f'''\
"""Runtime configuration."""

import json
from dataclasses import dataclass, field
from pathlib import Path


def _load_preferred_model() -> str:
    """Load preferred model from ~/.hive/configuration.json."""
    config_path = Path.home() / ".hive" / "configuration.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
            llm = config.get("llm", {{}})
            if llm.get("provider") and llm.get("model"):
                return f"{{llm[\'provider\']}}/{{llm[\'model\']}}"
        except Exception:
            pass
    return "anthropic/claude-sonnet-4-20250514"


@dataclass
class RuntimeConfig:
    model: str = field(default_factory=_load_preferred_model)
    temperature: float = 0.7
    max_tokens: int = 40000
    api_key: str | None = None
    api_base: str | None = None


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = {json.dumps(goal_name)}
    version: str = "1.0.0"
    description: str = {json.dumps(goal_desc)}
    intro_message: str = {json.dumps(f"{goal_name} ready.")}


metadata = AgentMetadata()
'''


# GCU default system prompt template
_GCU_DEFAULT_PROMPT = """\
You are a browser automation agent. Your job is to complete the assigned task using browser tools.

## Workflow
1. browser_start (only if no browser is running yet)
2. browser_open(url=TARGET_URL) — note the returned targetId
3. browser_snapshot to read the page
4. [task-specific steps]
5. set_output("result", JSON)

## Best Practices
- Prefer browser_snapshot over browser_get_text("body") — compact accessibility tree
- Always browser_wait after navigation
- Use large scroll amounts (~2000-5000) for lazy-loaded content
- If auth wall detected, report immediately — do not attempt login
- Keep tool calls per turn ≤10
- Tab isolation: use browser_open(background=true) and pass target_id to every call

## Output format
set_output("result", JSON) with your findings.
"""


def _generate_nodes_init_py(session: BuildSession) -> str:
    """Generate nodes/__init__.py content with GCU auto-configuration."""
    lines = ['"""Node definitions."""\n', "from framework.graph import NodeSpec\n"]

    var_names = []
    for node in session.nodes:
        var = _node_var_name(node.id)
        var_names.append(var)

        # GCU auto-configuration: set sensible defaults for GCU nodes
        is_gcu = node.node_type == "gcu"
        client_facing = (
            node.client_facing if node.client_facing else (False if is_gcu else node.client_facing)
        )
        max_node_visits = (
            node.max_node_visits
            if node.max_node_visits != 0
            else (1 if is_gcu else node.max_node_visits)
        )
        output_keys = (
            node.output_keys if node.output_keys else (["result"] if is_gcu else node.output_keys)
        )

        # Build NodeSpec kwargs
        kwargs_parts = [
            f"    id={json.dumps(node.id)},",
            f"    name={json.dumps(node.name)},",
            f"    description={json.dumps(node.description)},",
            f"    node_type={json.dumps(node.node_type)},",
            f"    client_facing={client_facing!r},",
            f"    max_node_visits={max_node_visits},",
            f"    input_keys={json.dumps(node.input_keys)},",
            f"    output_keys={json.dumps(output_keys)},",
        ]
        if node.nullable_output_keys:
            kwargs_parts.append(
                f"    nullable_output_keys={json.dumps(node.nullable_output_keys)},"
            )
        if node.success_criteria:
            kwargs_parts.append(f"    success_criteria={json.dumps(node.success_criteria)},")
        if node.routes:
            kwargs_parts.append(f"    routes={json.dumps(node.routes)},")
        if node.sub_agents:
            kwargs_parts.append(f"    sub_agents={json.dumps(node.sub_agents)},")

        # System prompt — use GCU default for GCU nodes if not provided
        sp = node.system_prompt or ""
        if is_gcu and not sp.strip():
            sp = _GCU_DEFAULT_PROMPT
        kwargs_parts.append(f"    system_prompt={json.dumps(sp)},")

        # Tools — GCU nodes auto-include browser tools at runtime
        kwargs_parts.append(f"    tools={json.dumps(node.tools)},")

        lines.append(f"\n{var} = NodeSpec(\n")
        lines.append("\n".join(kwargs_parts))
        lines.append("\n)\n")

    lines.append(f"\n__all__ = {json.dumps(var_names)}\n")
    return "".join(lines)


def _generate_agent_py(
    session: BuildSession,
    entry_node: str,
    entry_points: dict,
    terminal_nodes: list,
    pause_nodes: list,
    has_async: bool,
) -> str:
    """Generate agent.py content."""
    class_name = _snake_to_camel(session.name)
    agent_name = session.name
    goal = session.goal

    # Build node variable imports
    node_vars = [_node_var_name(n.id) for n in session.nodes]
    node_imports = ", ".join(node_vars)

    # Imports block
    imports = [
        '"""Agent graph construction."""\n',
        "from pathlib import Path\n",
        "from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint",
    ]
    if has_async:
        imports.append("from framework.graph.edge import GraphSpec, AsyncEntryPointSpec")
        imports.append(
            "from framework.runtime.agent_runtime import (\n"
            "    AgentRuntime, AgentRuntimeConfig, create_agent_runtime,\n"
            ")"
        )
    else:
        imports.append("from framework.graph.edge import GraphSpec")
        imports.append(
            "from framework.runtime.agent_runtime import (\n"
            "    AgentRuntime, create_agent_runtime,\n"
            ")"
        )
    imports.append("from framework.graph.executor import ExecutionResult")
    imports.append("from framework.graph.checkpoint_config import CheckpointConfig")
    imports.append("from framework.llm import LiteLLMProvider")
    imports.append("from framework.runner.tool_registry import ToolRegistry")
    imports.append("from framework.runtime.execution_stream import EntryPointSpec")
    imports.append("\nfrom .config import default_config, metadata")
    imports.append(f"from .nodes import {node_imports}")

    out = "\n".join(imports) + "\n\n"

    # Goal definition
    out += "# Goal definition\n"
    out += "goal = Goal(\n"
    out += f"    id={json.dumps(goal.id)},\n"
    out += f"    name={json.dumps(goal.name)},\n"
    out += f"    description={json.dumps(goal.description)},\n"

    if goal.success_criteria:
        out += "    success_criteria=[\n"
        for sc in goal.success_criteria:
            sc_dict = sc.model_dump() if hasattr(sc, "model_dump") else sc
            out += "        SuccessCriterion(\n"
            out += f"            id={json.dumps(sc_dict['id'])},\n"
            out += f"            description={json.dumps(sc_dict['description'])},\n"
            out += f"            metric={json.dumps(sc_dict.get('metric', ''))},\n"
            out += f"            target={json.dumps(sc_dict.get('target', ''))},\n"
            out += f"            weight={sc_dict.get('weight', 1.0)},\n"
            out += "        ),\n"
        out += "    ],\n"

    if goal.constraints:
        out += "    constraints=[\n"
        for c in goal.constraints:
            c_dict = c.model_dump() if hasattr(c, "model_dump") else c
            out += "        Constraint(\n"
            out += f"            id={json.dumps(c_dict['id'])},\n"
            out += f"            description={json.dumps(c_dict['description'])},\n"
            ct = json.dumps(c_dict.get("constraint_type", "hard"))
            out += f"            constraint_type={ct},\n"
            out += f"            category={json.dumps(c_dict.get('category', 'quality'))},\n"
            out += "        ),\n"
        out += "    ],\n"

    out += ")\n\n"

    # Nodes list
    out += f"# Node list\nnodes = [{node_imports}]\n\n"

    # Edges
    out += "# Edge definitions\nedges = [\n"
    for edge in session.edges:
        out += "    EdgeSpec(\n"
        out += f"        id={json.dumps(edge.id)},\n"
        out += f"        source={json.dumps(edge.source)},\n"
        out += f"        target={json.dumps(edge.target)},\n"
        out += f"        condition=EdgeCondition.{edge.condition.name},\n"
        if edge.condition_expr:
            out += f"        condition_expr={json.dumps(edge.condition_expr)},\n"
        out += f"        priority={edge.priority},\n"
        out += "    ),\n"
    out += "]\n\n"

    # Graph config
    out += "# Graph configuration\n"
    out += f"entry_node = {json.dumps(entry_node)}\n"
    out += f"entry_points = {json.dumps(entry_points)}\n"
    out += f"pause_nodes = {json.dumps(pause_nodes)}\n"
    out += f"terminal_nodes = {json.dumps(terminal_nodes)}\n\n"

    # Async entry points placeholder (if has_async, emit a TODO skeleton)
    if has_async:
        out += "# Async entry points — customize triggers as needed\n"
        out += "async_entry_points = []\n\n"
        out += "# Runtime config for webhooks (optional)\n"
        out += "runtime_config = AgentRuntimeConfig(\n"
        out += '    webhook_host="127.0.0.1",\n'
        out += "    webhook_port=8080,\n"
        out += "    webhook_routes=[],\n"
        out += ")\n\n"

    # Module-level vars
    out += "# Module-level vars read by AgentRunner.load()\n"
    out += 'conversation_mode = "continuous"\n'

    identity = f"You are {goal.name}. {goal.description}"
    if len(identity) > 200:
        identity = identity[:197] + "..."
    out += f"identity_prompt = {json.dumps(identity)}\n"

    loop_cfg = session.loop_config or {
        "max_iterations": 100,
        "max_tool_calls_per_turn": 30,
        "max_history_tokens": 32000,
    }
    out += f"loop_config = {json.dumps(loop_cfg)}\n\n"

    # Agent class
    graph_id = f"{agent_name}-graph"
    out += f"\nclass {class_name}:\n"
    out += "    def __init__(self, config=None):\n"
    out += "        self.config = config or default_config\n"
    out += "        self.goal = goal\n"
    out += "        self.nodes = nodes\n"
    out += "        self.edges = edges\n"
    out += "        self.entry_node = entry_node\n"
    out += "        self.entry_points = entry_points\n"
    out += "        self.pause_nodes = pause_nodes\n"
    out += "        self.terminal_nodes = terminal_nodes\n"
    out += "        self._graph = None\n"
    out += "        self._agent_runtime = None\n"
    out += "        self._tool_registry = None\n"
    out += "        self._storage_path = None\n\n"

    # _build_graph
    out += "    def _build_graph(self):\n"
    out += "        return GraphSpec(\n"
    out += f"            id={json.dumps(graph_id)},\n"
    out += "            goal_id=self.goal.id,\n"
    out += '            version="1.0.0",\n'
    out += "            entry_node=self.entry_node,\n"
    out += "            entry_points=self.entry_points,\n"
    out += "            terminal_nodes=self.terminal_nodes,\n"
    out += "            pause_nodes=self.pause_nodes,\n"
    out += "            nodes=self.nodes,\n"
    out += "            edges=self.edges,\n"
    if has_async:
        out += "            async_entry_points=async_entry_points,\n"
    out += "            default_model=self.config.model,\n"
    out += "            max_tokens=self.config.max_tokens,\n"
    out += "            loop_config=loop_config,\n"
    out += "            conversation_mode=conversation_mode,\n"
    out += "            identity_prompt=identity_prompt,\n"
    out += "        )\n\n"

    # _setup
    storage = f".hive/agents/{agent_name}"
    out += "    def _setup(self):\n"
    out += f"        self._storage_path = Path.home() / {json.dumps(storage)}\n"
    out += "        self._storage_path.mkdir(parents=True, exist_ok=True)\n"
    out += "        self._tool_registry = ToolRegistry()\n"
    out += '        mcp_config = Path(__file__).parent / "mcp_servers.json"\n'
    out += "        if mcp_config.exists():\n"
    out += "            self._tool_registry.load_mcp_config(mcp_config)\n"
    out += "        llm = LiteLLMProvider(\n"
    out += "            model=self.config.model,\n"
    out += "            api_key=self.config.api_key,\n"
    out += "            api_base=self.config.api_base,\n"
    out += "        )\n"
    out += "        tools = list(self._tool_registry.get_tools().values())\n"
    out += "        tool_executor = self._tool_registry.get_executor()\n"
    out += "        self._graph = self._build_graph()\n"
    out += "        self._agent_runtime = create_agent_runtime(\n"
    out += "            graph=self._graph,\n"
    out += "            goal=self.goal,\n"
    out += "            storage_path=self._storage_path,\n"
    out += "            entry_points=[\n"
    out += "                EntryPointSpec(\n"
    out += '                    id="default",\n'
    out += '                    name="Default",\n'
    out += "                    entry_node=self.entry_node,\n"
    out += '                    trigger_type="manual",\n'
    out += '                    isolation_level="shared",\n'
    out += "                ),\n"
    out += "            ],\n"
    if has_async:
        out += "            runtime_config=runtime_config,\n"
    out += "            llm=llm,\n"
    out += "            tools=tools,\n"
    out += "            tool_executor=tool_executor,\n"
    out += "            checkpoint_config=CheckpointConfig(\n"
    out += "                enabled=True,\n"
    out += "                checkpoint_on_node_complete=True,\n"
    out += "                checkpoint_max_age_days=7,\n"
    out += "                async_checkpoint=True,\n"
    out += "            ),\n"
    out += "        )\n\n"

    # start / stop / trigger_and_wait / run
    out += "    async def start(self):\n"
    out += "        if self._agent_runtime is None:\n"
    out += "            self._setup()\n"
    out += "        if not self._agent_runtime.is_running:\n"
    out += "            await self._agent_runtime.start()\n\n"

    out += "    async def stop(self):\n"
    out += "        if self._agent_runtime and self._agent_runtime.is_running:\n"
    out += "            await self._agent_runtime.stop()\n"
    out += "        self._agent_runtime = None\n\n"

    out += "    async def trigger_and_wait(\n"
    out += "        self,\n"
    out += '        entry_point="default",\n'
    out += "        input_data=None,\n"
    out += "        timeout=None,\n"
    out += "        session_state=None,\n"
    out += "    ):\n"
    out += "        if self._agent_runtime is None:\n"
    out += '            raise RuntimeError("Agent not started. Call start() first.")\n'
    out += "        return await self._agent_runtime.trigger_and_wait(\n"
    out += "            entry_point_id=entry_point,\n"
    out += "            input_data=input_data or {},\n"
    out += "            session_state=session_state,\n"
    out += "        )\n\n"

    out += "    async def run(self, context, session_state=None):\n"
    out += "        await self.start()\n"
    out += "        try:\n"
    out += "            result = await self.trigger_and_wait(\n"
    out += '                "default", context, session_state=session_state\n'
    out += "            )\n"
    out += (
        '            return result or ExecutionResult(success=False, error="Execution timeout")\n'
    )
    out += "        finally:\n"
    out += "            await self.stop()\n\n"

    # info
    out += "    def info(self):\n"
    out += "        return {\n"
    out += '            "name": metadata.name,\n'
    out += '            "version": metadata.version,\n'
    out += '            "description": metadata.description,\n'
    out += '            "goal": {\n'
    out += '                "name": self.goal.name,\n'
    out += '                "description": self.goal.description,\n'
    out += "            },\n"
    out += '            "nodes": [n.id for n in self.nodes],\n'
    out += '            "edges": [e.id for e in self.edges],\n'
    out += '            "entry_node": self.entry_node,\n'
    out += '            "entry_points": self.entry_points,\n'
    out += '            "terminal_nodes": self.terminal_nodes,\n'
    out += '            "client_facing_nodes": [n.id for n in self.nodes if n.client_facing],\n'
    out += "        }\n\n"

    # validate
    out += "    def validate(self):\n"
    out += '        """Validate graph wiring and entry-point contract."""\n'
    out += "        errors, warnings = [], []\n"
    out += "        node_ids = {n.id for n in self.nodes}\n"
    out += "        for e in self.edges:\n"
    out += "            if e.source not in node_ids:\n"
    out += "                errors.append(f\"Edge {e.id}: source '{e.source}' not found\")\n"
    out += "            if e.target not in node_ids:\n"
    out += "                errors.append(f\"Edge {e.id}: target '{e.target}' not found\")\n"
    out += "        if self.entry_node not in node_ids:\n"
    out += "            errors.append(f\"Entry node '{self.entry_node}' not found\")\n"
    out += "        for t in self.terminal_nodes:\n"
    out += "            if t not in node_ids:\n"
    out += "                errors.append(f\"Terminal node '{t}' not found\")\n"
    out += "        if not isinstance(self.entry_points, dict):\n"
    out += "            errors.append(\n"
    out += '                "Invalid entry_points: expected dict[str, str] like "\n'
    out += "                \"{'start': '<entry-node-id>'}. \"\n"
    out += '                f"Got {type(self.entry_points).__name__}. "\n'
    out += "                \"Fix agent.py: set entry_points = {'start': '<entry-node-id>'}.\"\n"
    out += "            )\n"
    out += "        else:\n"
    out += "            if 'start' not in self.entry_points:\n"
    out += "                errors.append(\n"
    out += "                    \"entry_points must include 'start' mapped to entry_node. \"\n"
    out += "                    \"Example: {'start': '<entry-node-id>'}.\"\n"
    out += "                )\n"
    out += "            else:\n"
    out += "                start_node = self.entry_points.get('start')\n"
    out += "                if start_node != self.entry_node:\n"
    out += "                    errors.append(\n"
    out += "                        f\"entry_points['start'] points to '{start_node}' \"\n"
    out += "                        f\"but entry_node is '{self.entry_node}'. \"\n"
    out += '                        "Keep these aligned."\n'
    out += "                    )\n"
    out += "            for ep_id, nid in self.entry_points.items():\n"
    out += "                if not isinstance(ep_id, str):\n"
    out += "                    errors.append(\n"
    out += '                        f"Invalid entry_points key {ep_id!r} "\n'
    out += (
        '                        f"({type(ep_id).__name__}). Entry point names must be strings."\n'
    )
    out += "                    )\n"
    out += "                    continue\n"
    out += "                if not isinstance(nid, str):\n"
    out += "                    errors.append(\n"
    out += "                        f\"Invalid entry_points['{ep_id}']={nid!r} \"\n"
    out += '                        f"({type(nid).__name__}). Node ids must be strings."\n'
    out += "                    )\n"
    out += "                    continue\n"
    out += "                if nid not in node_ids:\n"
    out += "                    errors.append(\n"
    out += "                        f\"Entry point '{ep_id}' references unknown node '{nid}'. \"\n"
    out += '                        f"Known nodes: {sorted(node_ids)}"\n'
    out += "                    )\n"
    out += (
        '        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}\n\n\n'
    )

    out += f"default_agent = {class_name}()\n"
    return out


def _generate_init_py(session: BuildSession, has_async: bool) -> str:
    """Generate __init__.py content."""
    class_name = _snake_to_camel(session.name)
    goal_name = session.goal.name if session.goal else session.name

    agent_imports = [
        class_name,
        "default_agent",
        "goal",
        "nodes",
        "edges",
        "entry_node",
        "entry_points",
        "pause_nodes",
        "terminal_nodes",
        "conversation_mode",
        "identity_prompt",
        "loop_config",
    ]
    if has_async:
        agent_imports.extend(["async_entry_points", "runtime_config"])

    agent_import_str = ",\n    ".join(agent_imports)

    config_imports = ["default_config", "metadata"]
    config_import_str = ", ".join(config_imports)

    all_names = agent_imports + config_imports
    all_str = ",\n    ".join(f'"{n}"' for n in all_names)

    return f'''\
"""{goal_name}."""

from .agent import (
    {agent_import_str},
)
from .config import {config_import_str}

__all__ = [
    {all_str},
]
'''


def _generate_main_py(session: BuildSession, has_async: bool) -> str:
    """Generate __main__.py content."""
    class_name = _snake_to_camel(session.name)
    agent_name = session.name
    goal_name = session.goal.name if session.goal else session.name
    storage_path = f".hive/agents/{agent_name}"

    out = f'''\
"""CLI entry point for {goal_name}."""

import asyncio
import json
import logging
import sys

import click

from .agent import default_agent, {class_name}


def setup_logging(verbose=False, debug=False):
    if debug:
        level, fmt = logging.DEBUG, "%(asctime)s %(name)s: %(message)s"
    elif verbose:
        level, fmt = logging.INFO, "%(message)s"
    else:
        level, fmt = logging.WARNING, "%(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """{goal_name}."""
    pass


@cli.command()
@click.option("--verbose", "-v", is_flag=True)
def run(verbose):
    """Execute the agent."""
    setup_logging(verbose=verbose)
    result = asyncio.run(default_agent.run({{}}))
    click.echo(
        json.dumps(
            {{"success": result.success, "output": result.output}}, indent=2, default=str
        )
    )
    sys.exit(0 if result.success else 1)


@cli.command()
def tui():
    """Launch TUI dashboard."""
    from pathlib import Path

    from framework.runtime.agent_runtime import create_agent_runtime
    from framework.runtime.execution_stream import EntryPointSpec
    from framework.tui.app import AdenTUI

    async def run_tui():
        agent = {class_name}()
        storage = Path.home() / {json.dumps(storage_path)}
        storage.mkdir(parents=True, exist_ok=True)
        agent._setup()
        runtime = agent._agent_runtime
        app = AdenTUI(runtime)
        await app.run_async()
        await runtime.stop()

    asyncio.run(run_tui())


@cli.command()
def info():
    """Show agent info."""
    data = default_agent.info()
    click.echo(f"Agent: {{data[\'name\']}}\\nVersion: {{data[\'version\']}}")
    click.echo(f"Description: {{data[\'description\']}}")
    click.echo(f"Nodes: {{', '.join(data[\'nodes\'])}}")
    click.echo(
        f"Client-facing: {{', '.join(data[\'client_facing_nodes\'])}}"
    )


@cli.command()
def validate():
    """Validate agent structure."""
    v = default_agent.validate()
    if v["valid"]:
        click.echo("Agent is valid")
    else:
        click.echo("Errors:")
        for e in v["errors"]:
            click.echo(f"  {{e}}")
    sys.exit(0 if v["valid"] else 1)


if __name__ == "__main__":
    cli()
'''
    return out


def _generate_conftest_py() -> str:
    """Generate tests/conftest.py content — pure boilerplate."""
    return '''\
"""Test fixtures."""

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[3]
for _p in ["exports", "core"]:
    _path = str(_repo_root / _p)
    if _path not in sys.path:
        sys.path.insert(0, _path)

AGENT_PATH = str(Path(__file__).resolve().parents[1])


@pytest.fixture(scope="session")
def agent_module():
    """Import the agent package for structural validation."""
    import importlib

    return importlib.import_module(Path(AGENT_PATH).name)


@pytest.fixture(scope="session")
def runner_loaded():
    """Load the agent through AgentRunner (structural only, no LLM needed)."""
    from framework.runner.runner import AgentRunner

    return AgentRunner.load(AGENT_PATH)
'''


def _generate_mcp_servers_json(session: BuildSession) -> str | None:
    """Generate mcp_servers.json in flat dict format.  Returns None if no servers."""
    if not session.mcp_servers:
        # Default: every agent needs hive-tools
        return json.dumps({
            "hive-tools": {
                "transport": "stdio",
                "command": "uv",
                "args": ["run", "python", "mcp_server.py", "--stdio"],
                "cwd": "../../tools",
                "description": "Hive tools MCP server"
            }
        }, indent=2)
    flat: dict[str, dict] = {}
    for server in session.mcp_servers:
        name = server.get("name", "unnamed")
        entry: dict = {}
        for key in ("transport", "command", "args", "cwd", "env", "url", "headers", "description"):
            if key in server and server[key]:
                entry[key] = server[key]
        # Default cwd for stdio servers
        if entry.get("transport") == "stdio" and "cwd" not in entry:
            entry["cwd"] = "../../tools"
        flat[name] = entry
    return json.dumps(flat, indent=2)


def initialize_agent_package(
    agent_name: str,
) -> str:
    """
    Generate the full Python agent package from the current build session.

    Creates all files needed for a runnable agent in exports/{agent_name}/:
    config.py, nodes/__init__.py, agent.py, __init__.py, __main__.py,
    mcp_servers.json, tests/conftest.py, agent.json, README.md.

    Call this INSTEAD of manually writing package files. Requires a valid
    graph (goal, nodes, edges). Uses the same validation as export_graph.

    Args:
        agent_name: Name for the agent. Must be valid snake_case for Python package.
                    Examples: 'my_agent', 'research_bot', 'data_processor'
    """
    import re
    from pathlib import Path

    session = get_session()

    # Validate agent name (must be valid snake_case for Python package)
    if not re.match(r"^[a-z][a-z0-9_]*$", agent_name):
        return json.dumps(
            {
                "success": False,
                "errors": [
                    f"Invalid agent_name '{agent_name}'. Must be snake_case: "
                    "lowercase letters, numbers, underscores. "
                    "Must start with a letter. Examples: 'my_agent', 'research_bot',"
                    " 'data_processor'"
                ],
            }
        )

    # Update session name
    session.name = agent_name
    _save_session(session)

    # Validate first
    validation = json.loads(validate_graph())
    if not validation["valid"]:
        return json.dumps({"success": False, "errors": validation["errors"]})

    entry_node = validation["entry_node"]
    terminal_nodes = validation["terminal_nodes"]
    pause_nodes = validation.get("pause_nodes", [])
    resume_entry_points = validation.get("resume_entry_points", [])

    # Build entry_points dict (same logic as export_graph)
    entry_points: dict[str, str] = {}
    if entry_node:
        entry_points["start"] = entry_node

    if pause_nodes and resume_entry_points:
        pause_to_resume: dict[str, str] = {}
        for pause_node_id in pause_nodes:
            pause_node = next((n for n in session.nodes if n.id == pause_node_id), None)
            if not pause_node:
                continue
            for resume_node_id in resume_entry_points:
                resume_node = next((n for n in session.nodes if n.id == resume_node_id), None)
                if not resume_node:
                    continue
                shared_keys = set(pause_node.output_keys) & set(resume_node.input_keys)
                if shared_keys:
                    pause_to_resume[pause_node_id] = resume_node_id
                    break
        unmatched_pause = [p for p in pause_nodes if p not in pause_to_resume]
        unmatched_resume = [r for r in resume_entry_points if r not in pause_to_resume.values()]
        for pause_id, resume_id in zip(unmatched_pause, unmatched_resume, strict=False):
            pause_to_resume[pause_id] = resume_id
        for pause_id, resume_id in pause_to_resume.items():
            entry_points[f"{pause_id}_resume"] = resume_id

    # Detect whether this agent needs async entry points
    has_async = False  # Placeholder; the coder can customize after generation

    # Create directory structure
    exports_dir = Path("exports") / session.name
    nodes_dir = exports_dir / "nodes"
    tests_dir = exports_dir / "tests"
    nodes_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    files_written: dict[str, dict] = {}

    def _write(rel_path: str, content: str) -> None:
        full = exports_dir / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        with atomic_write(full) as f:
            f.write(content)
        files_written[rel_path] = {
            "path": str(full),
            "size_bytes": full.stat().st_size,
        }

    # 1. config.py
    _write("config.py", _generate_config_py(session))

    # 2. nodes/__init__.py
    _write("nodes/__init__.py", _generate_nodes_init_py(session))

    # 3. agent.py
    _write(
        "agent.py",
        _generate_agent_py(
            session, entry_node, entry_points, terminal_nodes, pause_nodes, has_async
        ),
    )

    # 4. __init__.py
    _write("__init__.py", _generate_init_py(session, has_async))

    # 5. __main__.py
    _write("__main__.py", _generate_main_py(session, has_async))

    # 6. mcp_servers.json
    mcp_content = _generate_mcp_servers_json(session)
    if mcp_content is not None:
        _write("mcp_servers.json", mcp_content)

    # 7. tests/conftest.py
    _write("tests/conftest.py", _generate_conftest_py())

    # 8. agent.json + README.md — reuse export_graph logic
    export_result = json.loads(export_graph())
    if export_result.get("success"):
        for key in ("agent_json", "readme", "mcp_servers"):
            if key in export_result.get("files_written", {}):
                info = export_result["files_written"][key]
                # Map to relative path
                rel = (
                    str(Path(info["path"]).relative_to(exports_dir))
                    if exports_dir.as_posix() in info["path"]
                    else info["path"]
                )
                files_written[rel] = info

    # 9. Generate next validation step
    agent_name = session.name

    # 10. Generate node design warnings
    design_warnings = []
    for node in session.nodes:
        # Warn about nodes with no tools
        if not node.tools and node.node_type == "event_loop":
            design_warnings.append(
                {
                    "node_id": node.id,
                    "type": "no_tools",
                    "message": (
                        f"Node '{node.id}' has no tools. "
                        "Consider merging into another node or adding tools."
                    ),
                    "severity": "warning",
                }
            )
        # Warn about client-facing nodes that aren't entry nodes
        if node.client_facing and node.id != entry_node:
            design_warnings.append(
                {
                    "node_id": node.id,
                    "type": "client_facing_not_entry",
                    "message": (
                        f"Node '{node.id}' is client_facing but not the entry node. "
                        "Worker agents should not have client-facing nodes "
                        "(queen handles user interaction)."
                    ),
                    "severity": "warning",
                }
            )
        # GCU nodes should not be client_facing
        if node.node_type == "gcu" and node.client_facing:
            design_warnings.append(
                {
                    "node_id": node.id,
                    "type": "gcu_client_facing",
                    "message": (
                        f"GCU node '{node.id}' is client_facing. "
                        "GCU nodes should be autonomous subagents (client_facing=False)."
                    ),
                    "severity": "warning",
                }
            )
        # GCU nodes should have max_node_visits=1
        if node.node_type == "gcu" and node.max_node_visits != 1:
            design_warnings.append(
                {
                    "node_id": node.id,
                    "type": "gcu_max_visits",
                    "message": (
                        f"GCU node '{node.id}' should have max_node_visits=1 "
                        "(single execution per delegation)."
                    ),
                    "severity": "info",
                }
            )

    # Warn about node count (prefer 3-6 nodes)
    node_count = len(session.nodes)
    if node_count < 3:
        design_warnings.append(
            {
                "node_id": None,
                "type": "too_few_nodes",
                "message": (
                    f"Agent has only {node_count} node(s). "
                    "Consider adding nodes for better separation of concerns (recommend 3-6)."
                ),
                "severity": "warning",
            }
        )
    elif node_count > 6:
        design_warnings.append(
            {
                "node_id": None,
                "type": "too_many_nodes",
                "message": (
                    f"Agent has {node_count} nodes. "
                    "Consider consolidating to 3-6 nodes for simpler architecture."
                ),
                "severity": "warning",
            }
        )

    return json.dumps(
        {
            "success": True,
            "agent_name": session.name,
            "class_name": _snake_to_camel(session.name),
            "files_written": files_written,
            "file_count": len(files_written),
            "node_count": len(session.nodes),
            "edge_count": len(session.edges),
            "has_async": has_async,
            "entry_node": entry_node,
            "entry_points": entry_points,
            "next_step": f'validate_agent_package("{agent_name}")',
            "design_warnings": design_warnings,
            "summary": (
                f"Agent package '{session.name}' initialized at exports/{session.name}/. "
                f"Generated {len(files_written)} files. "
                f"Review and customize system prompts in nodes/__init__.py, "
                f"then run validate_agent_package(\"{session.name}\")."
            ),
        },
        default=str,
        indent=2,
    )


def import_from_export(
    agent_json_path: str,
) -> str:
    """
    Import an agent definition from an exported agent.json file into the current build session.

    Reads the agent.json, parses goal/nodes/edges, and populates the current session.
    This is the reverse of export_graph().

    Args:
        agent_json_path: Path to the agent.json file to import

    Returns:
        JSON summary of what was imported (goal name, node count, edge count)
    """
    session = get_session()

    path = Path(agent_json_path)
    if not path.exists():
        return json.dumps({"success": False, "error": f"File not found: {agent_json_path}"})

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return json.dumps({"success": False, "error": f"Invalid JSON: {e}"})

    try:
        # Parse goal (same pattern as BuildSession.from_dict lines 88-99)
        goal_data = data.get("goal")
        if goal_data:
            session.goal = Goal(
                id=goal_data["id"],
                name=goal_data["name"],
                description=goal_data["description"],
                success_criteria=[
                    SuccessCriterion(**sc) for sc in goal_data.get("success_criteria", [])
                ],
                constraints=[Constraint(**c) for c in goal_data.get("constraints", [])],
            )

        # Parse nodes (same pattern as BuildSession.from_dict line 102)
        graph_data = data.get("graph", {})
        nodes_data = graph_data.get("nodes", [])
        session.nodes = [NodeSpec(**n) for n in nodes_data]

        # Parse edges (same pattern as BuildSession.from_dict lines 105-118)
        edges_data = graph_data.get("edges", [])
        session.edges = []
        for e in edges_data:
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
    except (KeyError, TypeError, ValueError, ValidationError) as e:
        return json.dumps({"success": False, "error": f"Malformed agent.json: {e}"})

    # Persist updated session
    _save_session(session)

    return json.dumps(
        {
            "success": True,
            "goal": session.goal.name if session.goal else None,
            "nodes_count": len(session.nodes),
            "edges_count": len(session.edges),
            "node_ids": [n.id for n in session.nodes],
            "edge_ids": [e.id for e in session.edges],
        }
    )


# =============================================================================
# TESTING TOOLS (Goal-Based Evaluation)
# =============================================================================


# Test template for Claude to use when writing tests
CONSTRAINT_TEST_TEMPLATE = '''@pytest.mark.asyncio
async def test_constraint_{constraint_id}_{scenario}(runner, auto_responder, mock_mode):
    """Test: {description}"""
    await auto_responder.start()
    try:
        result = await runner.run({{"key": "value"}})
    finally:
        await auto_responder.stop()

    assert result.success, f"Agent failed: {{result.error}}"
    output_data = result.output or {{}}

    # Add constraint-specific assertions here
    assert condition, "Error message explaining what failed"
'''

SUCCESS_TEST_TEMPLATE = '''@pytest.mark.asyncio
async def test_success_{criteria_id}_{scenario}(runner, auto_responder, mock_mode):
    """Test: {description}"""
    await auto_responder.start()
    try:
        result = await runner.run({{"key": "value"}})
    finally:
        await auto_responder.stop()

    assert result.success, f"Agent failed: {{result.error}}"
    output_data = result.output or {{}}

    # Add success criteria-specific assertions here
    assert condition, "Error message explaining what failed"
'''


# =============================================================================
# CREDENTIAL STORE TOOLS
# =============================================================================


# =============================================================================
# SESSION & CHECKPOINT TOOLS (read-only, no build session required)
# =============================================================================

_MAX_DIFF_VALUE_LEN = 500


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("agent_name")
    parser.add_argument("agent_json_path")
    args = parser.parse_args()

    # Create session and import from export
    _session = BuildSession(args.agent_name)
    result = import_from_export(args.agent_json_path)
    import_data = json.loads(result)
    if not import_data.get("success"):
        print(result)
        sys.exit(1)

    # Generate package
    result = initialize_agent_package(args.agent_name)
    print(result)
