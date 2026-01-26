from __future__ import annotations

import ast
from typing import Any, Iterable

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec
from framework.validation.errors import ValidationError, GraphValidationError
class _ConditionSafetyVisitor(ast.NodeVisitor):
    allowed_nodes = {
        ast.Expression,
        ast.BoolOp,
        ast.UnaryOp,
        ast.BinOp,
        ast.Compare,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Subscript,
        ast.Attribute,
        ast.And,
        ast.Or,
        ast.Not,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.Is,
        ast.IsNot,
        ast.In,
        ast.NotIn,
    }

    def __init__(self, allowed_names: set[str]) -> None:
        self.allowed_names = allowed_names
        self.invalid_reason: str | None = None

    def visit(self, node: ast.AST) -> Any:
        if type(node) not in self.allowed_nodes:
            self.invalid_reason = f"Unsupported syntax: {type(node).__name__}"
            return None
        return super().visit(node)

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id not in self.allowed_names:
            self.invalid_reason = f"Unknown symbol '{node.id}'"
            return None
        return None

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        self.visit(node.value)
        return None

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        self.visit(node.value)
        self.visit(node.slice)
        return None

    def visit_Constant(self, node: ast.Constant) -> Any:
        return None


class WorkflowGraphValidator:
    """
    Deterministic pre-execution validator for workflow graphs.

    This utility validates graph structure and data flow before execution.
    It does not execute any workflow code.
    """

    def __init__(self, allow_cycles: bool | None = None) -> None:
        self.allow_cycles = allow_cycles

    def validate_or_raise(self, graph: GraphSpec) -> None:
        errors: list[ValidationError] = []

        node_map = {node.id: node for node in graph.nodes}

        if graph.entry_node not in node_map:
            errors.append(
                ValidationError(
                    error_type="missing_entry",
                    nodes=(graph.entry_node,),
                    message=f"Entry node '{graph.entry_node}' does not exist in graph.",
                )
            )
            raise GraphValidationError(errors)

        errors.extend(self._validate_edges(graph, node_map))
        errors.extend(self._validate_reachability(graph, node_map))
        errors.extend(self._validate_conditionals(graph, node_map))
        errors.extend(self._validate_cycles(graph, node_map))
        errors.extend(self._validate_inputs(graph, node_map))

        if errors:
            raise GraphValidationError(errors)

    def _validate_edges(self, graph: GraphSpec, node_map: dict[str, NodeSpec]) -> list[ValidationError]:
        errors: list[ValidationError] = []

        for edge in graph.edges:
            if edge.source not in node_map:
                errors.append(
                    ValidationError(
                        error_type="invalid_edge",
                        nodes=(edge.source, edge.target),
                        message=(
                            f"Edge '{edge.id}' references missing source '{edge.source}'. "
                            "Fix the edge source or add the missing node."
                        ),
                    )
                )
            if edge.target not in node_map:
                errors.append(
                    ValidationError(
                        error_type="invalid_edge",
                        nodes=(edge.source, edge.target),
                        message=(
                            f"Edge '{edge.id}' references missing target '{edge.target}'. "
                            "Fix the edge target or add the missing node."
                        ),
                    )
                )

        for node in node_map.values():
            for route_target in (node.routes or {}).values():
                if route_target not in node_map:
                    errors.append(
                        ValidationError(
                            error_type="invalid_edge",
                            nodes=(node.id, route_target),
                            message=(
                                f"Router '{node.id}' routes to missing target '{route_target}'. "
                                "Update routes or add the target node."
                            ),
                        )
                    )

        return errors

    def _validate_reachability(self, graph: GraphSpec, node_map: dict[str, NodeSpec]) -> list[ValidationError]:
        reachable = self._compute_reachable(graph, node_map, graph.entry_node)
        errors: list[ValidationError] = []

        for node_id in node_map:
            if node_id not in reachable:
                errors.append(
                    ValidationError(
                        error_type="unreachable_node",
                        nodes=(node_id,),
                        message=(
                            f"Node '{node_id}' is unreachable from entry '{graph.entry_node}'. "
                            "Add an edge from a reachable node or remove this node."
                        ),
                    )
                )

        return errors

    def _validate_conditionals(self, graph: GraphSpec, node_map: dict[str, NodeSpec]) -> list[ValidationError]:
        errors: list[ValidationError] = []
        outgoing = self._outgoing_edges(graph)

        for edge in graph.edges:
            if edge.condition == EdgeCondition.CONDITIONAL:
                if not edge.condition_expr:
                    errors.append(
                        ValidationError(
                            error_type="broken_conditional",
                            nodes=(edge.source, edge.target),
                            message=(
                                f"Conditional edge '{edge.id}' is missing condition_expr. "
                                "Provide a boolean expression like output['status'] == true."
                            ),
                        )
                    )
                    continue

                safe, reason = self._is_condition_safe(edge.condition_expr, graph, node_map.get(edge.source))
                if not safe:
                    errors.append(
                        ValidationError(
                            error_type="broken_conditional",
                            nodes=(edge.source, edge.target),
                            message=(
                                f"Conditional edge '{edge.id}' has an invalid expression: "
                                f"{edge.condition_expr}. {reason}"
                            ),
                        )
                    )

        for node_id, edges in outgoing.items():
            if not edges:
                continue

            if all(edge.condition == EdgeCondition.CONDITIONAL for edge in edges):
                resolvable = any(
                    edge.condition_expr
                    and self._is_condition_safe(edge.condition_expr, graph, node_map.get(node_id))[0]
                    for edge in edges
                )
                if not resolvable:
                    errors.append(
                        ValidationError(
                            error_type="no_resolvable_path",
                            nodes=(node_id,),
                            message=(
                                f"Node '{node_id}' only has conditional edges and none are valid. "
                                "Fix the condition syntax or add an always/on_success edge."
                            ),
                        )
                    )

        return errors

    def _validate_cycles(self, graph: GraphSpec, node_map: dict[str, NodeSpec]) -> list[ValidationError]:
        if self._cycles_globally_allowed(graph):
            return []

        adjacency = self._build_adjacency(graph, node_map)
        errors: list[ValidationError] = []

        visited: set[str] = set()
        stack: list[str] = []
        on_stack: set[str] = set()

        def dfs(node_id: str) -> None:
            visited.add(node_id)
            stack.append(node_id)
            on_stack.add(node_id)

            for neighbor in adjacency.get(node_id, []):
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in on_stack:
                    cycle_nodes = tuple(stack[stack.index(neighbor):])
                    if not self._cycle_allowed(graph, node_map, cycle_nodes):
                        errors.append(
                            ValidationError(
                                error_type="infinite_cycle",
                                nodes=cycle_nodes,
                                message=(
                                    "Execution cycle detected without allow_cycles or per-node/edge loop allowance: "
                                    f"{' -> '.join(cycle_nodes)}. "
                                    "Set allow_cycles on the validator or graph, or add allow_loop/allow_cycle metadata."
                                ),
                            )
                        )

            stack.pop()
            on_stack.remove(node_id)

        for node_id in node_map:
            if node_id not in visited:
                dfs(node_id)

        return errors

    def _validate_inputs(self, graph: GraphSpec, node_map: dict[str, NodeSpec]) -> list[ValidationError]:
        entry_node = node_map[graph.entry_node]
        outgoing = self._outgoing_edges(graph)

        available_before: dict[str, set[str]] = {node_id: set() for node_id in node_map}
        available_before[entry_node.id] = set(entry_node.input_keys)

        all_possible_keys = set(graph.memory_keys)
        for node in node_map.values():
            all_possible_keys.update(node.input_keys)
            all_possible_keys.update(node.output_keys)

        max_iterations = max(len(node_map) * 2, len(node_map) * max(len(all_possible_keys), 1))

        changed = True
        iterations = 0

        while changed and iterations < max_iterations:
            iterations += 1
            changed = False

            for edge in graph.edges:
                if edge.source not in node_map or edge.target not in node_map:
                    continue

                source_node = node_map[edge.source]
                target_node = node_map[edge.target]

                source_inputs = available_before[edge.source]
                if not set(source_node.input_keys).issubset(source_inputs):
                    continue

                source_outputs = set(source_node.output_keys)
                mapped_outputs = self._map_available_keys(edge, source_inputs, source_outputs)

                candidate = set(source_inputs)
                candidate.update(mapped_outputs)

                if candidate - available_before[target_node.id]:
                    available_before[target_node.id].update(candidate)
                    changed = True

            for node_id, edges in outgoing.items():
                if not edges:
                    continue
                node = node_map[node_id]
                if not set(node.input_keys).issubset(available_before[node_id]):
                    continue

        errors: list[ValidationError] = []

        for node_id, node in node_map.items():
            required_inputs = set(node.input_keys)
            if not required_inputs.issubset(available_before[node_id]):
                missing = required_inputs - available_before[node_id]
                errors.append(
                    ValidationError(
                        error_type="unsatisfied_input",
                        nodes=(node_id,),
                        message=(
                            f"Node '{node_id}' requires inputs that cannot be satisfied: "
                            f"{sorted(missing)}. "
                            "Ensure upstream nodes output these keys or add input mappings."
                        ),
                    )
                )

        return errors

    def _compute_reachable(
        self,
        graph: GraphSpec,
        node_map: dict[str, NodeSpec],
        start: str,
    ) -> set[str]:
        reachable: set[str] = set()
        to_visit = [start]

        adjacency = self._build_adjacency(graph, node_map)

        while to_visit:
            current = to_visit.pop()
            if current in reachable:
                continue
            reachable.add(current)
            to_visit.extend(adjacency.get(current, []))

        return reachable

    def _build_adjacency(self, graph: GraphSpec, node_map: dict[str, NodeSpec]) -> dict[str, list[str]]:
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_map}

        for edge in graph.edges:
            if edge.source in adjacency:
                adjacency[edge.source].append(edge.target)

        for node in node_map.values():
            for target in (node.routes or {}).values():
                adjacency.setdefault(node.id, []).append(target)

        return adjacency

    def _outgoing_edges(self, graph: GraphSpec) -> dict[str, list[EdgeSpec]]:
        outgoing: dict[str, list[EdgeSpec]] = {}
        for edge in graph.edges:
            outgoing.setdefault(edge.source, []).append(edge)
        return outgoing

    def _map_available_keys(
        self,
        edge: EdgeSpec,
        available_inputs: set[str],
        source_outputs: set[str],
    ) -> set[str]:
        if not edge.input_mapping:
            return set(source_outputs)

        mapped: set[str] = set()
        for target_key, source_key in edge.input_mapping.items():
            if source_key in available_inputs or source_key in source_outputs:
                mapped.add(target_key)
        return mapped

    def _cycle_allowed(
        self,
        graph: GraphSpec,
        node_map: dict[str, NodeSpec],
        cycle_nodes: Iterable[str],
    ) -> bool:
        if self._cycles_globally_allowed(graph):
            return True

        cycle_set = set(cycle_nodes)
        for node_id in cycle_set:
            node = node_map.get(node_id)
            if node and getattr(node, "allow_loop", False):
                return True

        for edge in graph.edges:
            if edge.source in cycle_set and edge.target in cycle_set:
                if getattr(edge, "allow_cycle", False):
                    return True

        return False

    def _cycles_globally_allowed(self, graph: GraphSpec) -> bool:
        if self.allow_cycles is True:
            return True
        if self.allow_cycles is None and getattr(graph, "allow_cycles", False):
            return True
        return False

    def _is_condition_safe(
        self,
        expr: str,
        graph: GraphSpec,
        source_node: NodeSpec | None,
    ) -> tuple[bool, str]:
        allowed_names = {"output", "memory", "result", "true", "false"}
        allowed_names.update(graph.memory_keys)

        if source_node:
            allowed_names.update(source_node.output_keys)
            allowed_names.update(source_node.input_keys)

        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as exc:
            return False, f"Syntax error: {exc.msg}"

        visitor = _ConditionSafetyVisitor(allowed_names)
        visitor.visit(tree)
        if visitor.invalid_reason:
            return False, visitor.invalid_reason

        return True, ""
