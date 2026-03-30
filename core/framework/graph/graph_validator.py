"""Graph structure validator for agent workflows.

Validates the graph structure, node dependencies, and ensures
that every node's input_keys are satisfied by reachable predecessors.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from framework.graph.edge import EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec

logger = logging.getLogger(__name__)


@dataclass
class GraphValidationResult:
    """Result of graph structure validation."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """Add an error message."""
        self.errors.append(message)
        self.valid = False

    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        self.warnings.append(message)


class GraphDependencyValidator:
    """
    Validates the structure and dependencies of an agent graph.

    Performs static analysis to catch issues before execution:
    - Input/output matching between nodes
    - Cycle detection
    - Edge reference validation
    """

    def __init__(self, graph: GraphSpec):
        """Initialize validator with a graph spec."""
        self.graph = graph
        self.node_map = {node.id: node for node in graph.nodes}
        self.edge_map: dict[str, list[EdgeSpec]] = self._build_edge_map()
        self.reverse_edge_map: dict[str, list[str]] = self._build_reverse_edge_map()
        self.output_index: dict[str, set[str]] = self._build_output_index()

    def _build_edge_map(self) -> dict[str, list[EdgeSpec]]:
        """Build mapping from source node to outgoing edges."""
        edge_map: dict[str, list[EdgeSpec]] = {}
        for edge in self.graph.edges:
            if edge.source not in edge_map:
                edge_map[edge.source] = []
            edge_map[edge.source].append(edge)
        return edge_map

    def _build_reverse_edge_map(self) -> dict[str, list[str]]:
        """Build mapping from target node to source nodes."""
        reverse_map: dict[str, list[str]] = {}
        for edge in self.graph.edges:
            if edge.target not in reverse_map:
                reverse_map[edge.target] = []
            reverse_map[edge.target].append(edge.source)
        return reverse_map

    def _build_output_index(self) -> dict[str, set[str]]:
        """Build index of all outputs produced by each node."""
        output_index = {}
        for node in self.graph.nodes:
            outputs = set(node.output_keys)
            # Include nullable_output_keys if present
            if hasattr(node, "nullable_output_keys") and node.nullable_output_keys:
                outputs.update(node.nullable_output_keys)
            output_index[node.id] = outputs
        return output_index

    def _get_reachable_predecessors(self, node_id: str) -> set[str]:
        """
        Get all reachable predecessors for a node using BFS.

        Returns:
            Set of node IDs that can reach the given node.
        """
        visited = set()
        queue = deque(self.reverse_edge_map.get(node_id, []))

        while queue:
            pred = queue.popleft()
            if pred in visited:
                continue
            visited.add(pred)
            queue.extend(self.reverse_edge_map.get(pred, []))

        return visited

    def validate(self) -> GraphValidationResult:
        """Run all validation checks."""
        result = GraphValidationResult()

        # 1. Basic structure validation
        self._validate_nodes_exist(result)
        self._validate_entry_node(result)
        self._validate_terminal_nodes(result)

        # 2. Validate each node's inputs are satisfied
        self._validate_input_satisfaction(result)

        # 3. Detect cycles
        cycles = self._detect_cycles()
        if cycles:
            result.add_error(f"Dependency cycles detected: {self._format_cycles(cycles)}")

        # 4. Validate edges
        self._validate_edges(result)

        # 5. Check for unused outputs (warning)
        self._detect_unused_outputs(result)

        return result

    def _validate_nodes_exist(self, result: GraphValidationResult) -> None:
        """Validate that all referenced nodes exist."""
        # Collect all entry nodes from graph
        entry_nodes = set()
        if self.graph.entry_node:
            entry_nodes.add(self.graph.entry_node)

        # Add entry_points if they exist
        if hasattr(self.graph, "entry_points") and self.graph.entry_points:
            entry_nodes.update(self.graph.entry_points.keys())

        # Add async_entry_points if they exist
        if hasattr(self.graph, "async_entry_points") and self.graph.async_entry_points:
            for aep in self.graph.async_entry_points:
                if hasattr(aep, "entry_node") and aep.entry_node:
                    entry_nodes.add(aep.entry_node)

        # Check edges reference existing nodes
        for edge in self.graph.edges:
            if edge.source not in self.node_map:
                result.add_error(f"Edge references unknown source node: '{edge.source}'")
            if edge.target not in self.node_map:
                result.add_error(f"Edge references unknown target node: '{edge.target}'")

        # Check entry nodes exist
        for entry in entry_nodes:
            if entry not in self.node_map:
                result.add_error(f"Entry node '{entry}' not found in graph")

    def _validate_entry_node(self, result: GraphValidationResult) -> None:
        """Validate that entry node exists."""
        # Collect all entry nodes
        entry_nodes = set()
        if self.graph.entry_node:
            entry_nodes.add(self.graph.entry_node)

        if hasattr(self.graph, "entry_points") and self.graph.entry_points:
            entry_nodes.update(self.graph.entry_points.keys())

        if hasattr(self.graph, "async_entry_points") and self.graph.async_entry_points:
            for aep in self.graph.async_entry_points:
                if hasattr(aep, "entry_node") and aep.entry_node:
                    entry_nodes.add(aep.entry_node)

        if not entry_nodes:
            result.add_error("Graph has no entry node defined")
            return

        for entry in entry_nodes:
            if entry not in self.node_map:
                result.add_error(f"Entry node '{entry}' not found in graph")

    def _validate_terminal_nodes(self, result: GraphValidationResult) -> None:
        """Validate that terminal nodes exist."""
        for terminal in self.graph.terminal_nodes:
            if terminal not in self.node_map:
                result.add_error(f"Terminal node '{terminal}' not found in graph")

    def _validate_input_satisfaction(self, result: GraphValidationResult) -> None:
        """
        Validate that each node's inputs are satisfied by reachable predecessors.

        A node's input is satisfied if:
        - It is provided by at least one reachable predecessor's outputs
        - OR it is provided externally (entry node inputs are exempt)
        """
        # Collect all entry nodes that are exempt from input validation
        entry_nodes = set()
        if self.graph.entry_node:
            entry_nodes.add(self.graph.entry_node)

        if hasattr(self.graph, "entry_points") and self.graph.entry_points:
            entry_nodes.update(self.graph.entry_points.keys())

        if hasattr(self.graph, "async_entry_points") and self.graph.async_entry_points:
            for aep in self.graph.async_entry_points:
                if hasattr(aep, "entry_node") and aep.entry_node:
                    entry_nodes.add(aep.entry_node)

        for node in self.graph.nodes:
            # Skip validation for entry nodes (inputs provided externally)
            if node.id in entry_nodes:
                continue

            if not node.input_keys:
                continue

            # Get reachable predecessors
            predecessors = self._get_reachable_predecessors(node.id)

            # Check each input key
            missing_inputs = []
            for input_key in node.input_keys:
                provided = False
                for pred_id in predecessors:
                    if input_key in self.output_index.get(pred_id, set()):
                        provided = True
                        break

                if not provided:
                    missing_inputs.append(input_key)

            if missing_inputs:
                # Get direct predecessors for better error message
                direct_preds = self.reverse_edge_map.get(node.id, [])
                if direct_preds:
                    available_outputs = self._get_available_outputs(direct_preds)
                    result.add_error(
                        f"Node '{node.id}' requires inputs {missing_inputs} but none of its "
                        f"predecessors ({direct_preds}) produce these outputs. "
                        f"Available outputs from predecessors: {available_outputs}"
                    )
                else:
                    result.add_error(
                        f"Node '{node.id}' requires inputs {missing_inputs} but has no predecessors. "
                        f"Add an edge from a node that produces these outputs."
                    )

    def _get_available_outputs(self, node_ids: list[str]) -> dict[str, list[str]]:
        """Get outputs available from a list of nodes."""
        available = {}
        for node_id in node_ids:
            if node_id in self.output_index and self.output_index[node_id]:
                available[node_id] = list(self.output_index[node_id])
        return available

    def _detect_cycles(self) -> list[list[str]]:
        """Detect cycles in the graph using DFS."""
        visited = set()
        rec_stack = set()
        cycles = []

        def dfs(node_id: str, parent_map: dict[str, str]) -> list[str] | None:
            visited.add(node_id)
            rec_stack.add(node_id)

            for edge in self.edge_map.get(node_id, []):
                neighbor = edge.target
                if neighbor not in visited:
                    parent_map[neighbor] = node_id
                    result = dfs(neighbor, parent_map)
                    if result:
                        return result
                elif neighbor in rec_stack:
                    # Cycle detected, reconstruct the cycle
                    cycle = [neighbor]
                    curr = node_id
                    while curr != neighbor and curr in parent_map:
                        cycle.insert(0, curr)
                        curr = parent_map.get(curr, "")
                        if not curr:
                            break
                    cycle.insert(0, neighbor)
                    return cycle
            rec_stack.remove(node_id)
            return None

        for node_id in self.node_map.keys():
            if node_id not in visited:
                parent_map: dict[str, str] = {}
                cycle = dfs(node_id, parent_map)
                if cycle:
                    cycles.append(cycle)

        return cycles

    def _format_cycles(self, cycles: list[list[str]]) -> str:
        """Format cycles for user-friendly output."""
        formatted = []
        for cycle in cycles:
            formatted.append(" → ".join(cycle))
        return "; ".join(formatted)

    def _validate_edges(self, result: GraphValidationResult) -> None:
        """Validate edge properties."""
        seen_edges = set()
        for edge in self.graph.edges:
            edge_key = (edge.source, edge.target)

            # Check for self-loop
            if edge.source == edge.target:
                result.add_error(f"Self-loop detected: node '{edge.source}' has edge to itself")

            # Check for duplicate edges
            if edge_key in seen_edges:
                result.add_warning(
                    f"Duplicate edge from '{edge.source}' to '{edge.target}'. "
                    "Only one edge is needed."
                )
            seen_edges.add(edge_key)

    def _detect_unused_outputs(self, result: GraphValidationResult) -> None:
        """Detect outputs that are never used by any successor."""
        # Collect all inputs that are used
        used_outputs: set[str] = set()
        for node in self.graph.nodes:
            for input_key in node.input_keys:
                used_outputs.add(input_key)

        # Check each node's outputs
        for node in self.graph.nodes:
            unused = []
            for output_key in node.output_keys:
                if output_key not in used_outputs:
                    unused.append(output_key)

            if unused:
                # Check if this node has any successors
                has_successors = any(edge.source == node.id for edge in self.graph.edges)
                if has_successors and node.id != self.graph.entry_node:
                    result.add_warning(
                        f"Node '{node.id}' produces outputs {unused} that are never consumed. "
                        "These outputs will be ignored."
                    )
