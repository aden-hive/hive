"""
Mermaid Diagram Exporter - Export agent graphs to Mermaid.js syntax.

Converts a GraphSpec into a Mermaid flowchart diagram string that renders
natively in GitHub, markdown viewers, and documentation tools.

Usage:
    from framework.graph.mermaid import to_mermaid

    diagram = to_mermaid(graph_spec)
    print(diagram)

    # Or via GraphSpec convenience method:
    diagram = graph_spec.to_mermaid()
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from framework.graph.edge import EdgeCondition

if TYPE_CHECKING:
    from framework.graph.edge import EdgeSpec, GraphSpec

# Mermaid node shapes by node_type: (left_delimiter, right_delimiter)
_NODE_SHAPES: dict[str, tuple[str, str]] = {
    "event_loop": ("(", ")"),
    "llm_tool_use": ("(", ")"),
    "llm_generate": ("(", ")"),
    "function": ("[[", "]]"),
    "router": ("{", "}"),
    "human_input": ("([", "])"),
}

_DEFAULT_SHAPE = ("(", ")")


def _sanitize_id(node_id: str) -> str:
    """Sanitize a node ID for Mermaid compatibility.

    Mermaid node IDs must contain only alphanumeric characters and underscores.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", node_id)
    if sanitized and sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    return sanitized


def _escape_label(text: str) -> str:
    """Escape characters that conflict with Mermaid syntax."""
    return text.replace('"', "'").replace("|", "/")


def _node_display_name(node: Any) -> str:
    """Get a human-readable display name for a node."""
    return node.name if node.name else node.id


def _edge_label(edge: EdgeSpec) -> str:
    """Generate a Mermaid edge label based on the edge condition type."""
    if edge.condition == EdgeCondition.ALWAYS:
        return ""
    if edge.condition == EdgeCondition.ON_SUCCESS:
        return "Success"
    if edge.condition == EdgeCondition.ON_FAILURE:
        return "Failure"
    if edge.condition == EdgeCondition.CONDITIONAL:
        return _escape_label(edge.condition_expr) if edge.condition_expr else "Conditional"
    if edge.condition == EdgeCondition.LLM_DECIDE:
        return _escape_label(edge.description) if edge.description else "LLM Decision"
    return ""


def _topo_order(graph: GraphSpec) -> list[str]:
    """BFS traversal from entry_node, appending unreachable nodes at the end."""
    visited: list[str] = []
    seen: set[str] = set()
    queue = [graph.entry_node]
    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        visited.append(nid)
        for edge in graph.get_outgoing_edges(nid):
            if edge.target not in seen:
                queue.append(edge.target)
    for node in graph.nodes:
        if node.id not in seen:
            visited.append(node.id)
    return visited


def to_mermaid(graph: GraphSpec) -> str:
    """Export a GraphSpec to a Mermaid flowchart diagram string.

    Args:
        graph: The GraphSpec to convert.

    Returns:
        A string containing valid Mermaid flowchart syntax suitable for
        rendering in GitHub, markdown viewers, or Mermaid-compatible tools.

    Example output::

        graph TD
            _start_((Start)) --> research
            research("Research Agent")
            writer("Writer Agent")
            research -->|"Success"| writer
    """
    lines: list[str] = ["graph TD"]

    node_map: dict[str, Any] = {node.id: node for node in graph.nodes}
    terminal_set = set(graph.terminal_nodes or [])
    ordered = _topo_order(graph)

    # Define nodes with shapes
    for node_id in ordered:
        node = node_map.get(node_id)
        if not node:
            continue
        safe_id = _sanitize_id(node_id)
        name = _escape_label(_node_display_name(node))
        node_type = getattr(node, "node_type", "event_loop")
        left, right = _NODE_SHAPES.get(node_type, _DEFAULT_SHAPE)
        lines.append(f'    {safe_id}{left}"{name}"{right}')

    # Start marker pointing to entry node
    entry_safe = _sanitize_id(graph.entry_node)
    lines.append(f"    _start_((Start)) --> {entry_safe}")

    # Edges
    for node_id in ordered:
        for edge in graph.get_outgoing_edges(node_id):
            src = _sanitize_id(edge.source)
            tgt = _sanitize_id(edge.target)
            label = _edge_label(edge)
            if label:
                lines.append(f'    {src} -->|"{label}"| {tgt}')
            else:
                lines.append(f"    {src} --> {tgt}")

    # Style terminal nodes
    terminal_ids = [_sanitize_id(nid) for nid in terminal_set if nid in node_map]
    if terminal_ids:
        lines.append("    classDef terminal stroke-width:4px")
        lines.append(f"    class {','.join(terminal_ids)} terminal")

    return "\n".join(lines) + "\n"
