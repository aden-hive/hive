from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec
from validation.errors import ValidationError, GraphValidationError
from validation.validation_result import ValidationResult


@dataclass(frozen=True)
class _Unknown:
    def __getitem__(self, _key: Any) -> "_Unknown":
        return self

    def __getattr__(self, _name: str) -> "_Unknown":
        return self

    def __bool__(self) -> bool:
        return True

    def __eq__(self, _other: Any) -> bool:
        return True

    def __ne__(self, _other: Any) -> bool:
        return False


class WorkflowGraphValidator:
    def __init__(self, allow_cycles: bool | None = None) -> None:
        self.allow_cycles = allow_cycles

    def validate(self, graph: GraphSpec) -> ValidationResult:
        errors: list[ValidationError] = []

        node_map = {node.id: node for node in graph.nodes}

        if graph.entry_node not in node_map:
            errors.append(
                ValidationError(
                    error_type="missing_entry",
                    nodes=(graph.entry_node,),
                    message=f"Entry node '{graph.entry_node}' does not exist in graph",
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

        return ValidationResult(valid=True, errors=[])

    def _validate_edges(self, graph: GraphSpec, node_map: dict[str, NodeSpec]) -> list[ValidationError]:
        errors: list[ValidationError] = []

        for edge in graph.edges:
            if edge.source not in node_map:
                errors.append(
                    ValidationError(
                        error_type="invalid_edge",
                        nodes=(edge.source, edge.target),
                        message=f"Edge '{edge.id}' references missing source '{edge.source}'",
                    )
                )
            if edge.target not in node_map:
                errors.append(
                    ValidationError(
                        error_type="invalid_edge",
                        nodes=(edge.source, edge.target),
                        message=f"Edge '{edge.id}' references missing target '{edge.target}'",
                    )
                )

        for node in node_map.values():
            for route_target in (node.routes or {}).values():
                if route_target not in node_map:
                    errors.append(
                        ValidationError(
                            error_type="invalid_edge",
                            nodes=(node.id, route_target),
                            message=f"Router '{node.id}' routes to missing target '{route_target}'",
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
                        message=f"Node '{node_id}' is unreachable from entry '{graph.entry_node}'",
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
                            message=f"Conditional edge '{edge.id}' is missing condition_expr",
                        )
                    )
                    continue

                if not self._can_evaluate_condition(edge.condition_expr, node_map.get(edge.source)):
                    errors.append(
                        ValidationError(
                            error_type="broken_conditional",
                            nodes=(edge.source, edge.target),
                            message=(
                                f"Conditional edge '{edge.id}' has an invalid expression: "
                                f"{edge.condition_expr}"
                            ),
                        )
                    )

        for node_id, edges in outgoing.items():
            if not edges:
                continue

            if all(edge.condition == EdgeCondition.CONDITIONAL for edge in edges):
                resolvable = any(
                    edge.condition_expr and self._can_evaluate_condition(edge.condition_expr, node_map.get(node_id))
                    for edge in edges
                )
                if not resolvable:
                    errors.append(
                        ValidationError(
                            error_type="no_resolvable_path",
                            nodes=(node_id,),
                            message=(
                                f"Node '{node_id}' has only conditional edges with no resolvable path"
                            ),
                        )
                    )

        return errors

    def _validate_cycles(self, graph: GraphSpec, node_map: dict[str, NodeSpec]) -> list[ValidationError]:
        if self.allow_cycles is True or getattr(graph, "allow_cycles", False):
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
                                    "Execution cycle detected without allow_cycle or allow_loop metadata: "
                                    f"{' -> '.join(cycle_nodes)}"
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

        changed = True
        iterations = 0

        while changed and iterations < len(node_map) * 2:
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
                            f"{sorted(missing)}"
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
        if getattr(graph, "allow_cycles", False):
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

    def _can_evaluate_condition(self, expr: str, source_node: NodeSpec | None) -> bool:
        unknown = _Unknown()
        output_keys = source_node.output_keys if source_node else []

        output_placeholder = {key: unknown for key in output_keys}
        memory_placeholder = {key: unknown for key in output_keys}

        context = {
            "output": output_placeholder,
            "memory": memory_placeholder,
            "result": unknown,
            "true": True,
            "false": False,
        }

        try:
            eval(expr, {"__builtins__": {}}, context)
            return True
        except Exception:
            return False
