
from typing import List, Dict, Any, Set

class ValidationResult:
    def __init__(self, valid: bool, error: str = ""):
        self.valid = valid
        self.error = error

    def __bool__(self):
        return self.valid

class GraphValidator:
    """
    Validates graph structure reliability.
    Prevents 'technical cornas' (infinite loops, disconnected nodes).
    """

    @staticmethod
    def validate(graph_spec: Any) -> ValidationResult:
        """
        Run all validation checks on a GraphSpec-like object.
        Expected object structure: 
        - nodes: list of NodeSpec (with 'id')
        - edges: list of EdgeSpec (with 'source', 'target')
        - entry_node: str
        """
        
        # 1. Integrity Check (Basic Fields)
        if not hasattr(graph_spec, "nodes") or not hasattr(graph_spec, "edges") or not hasattr(graph_spec, "entry_node"):
             return ValidationResult(False, "GraphSpec missing required attributes (nodes, edges, entry_node)")

        # Convert list-based spec to fast-lookup dicts
        node_ids = {n.id for n in graph_spec.nodes}
        adj_list = {n_id: [] for n_id in node_ids}
        
        for edge in graph_spec.edges:
            if edge.source not in node_ids:
                return ValidationResult(False, f"Edge references missing source node: {edge.source}")
            if edge.target not in node_ids:
                return ValidationResult(False, f"Edge references missing target node: {edge.target}")
            adj_list[edge.source].append(edge.target)

        # 2. Cycle Detection (DFS)
        # We assume directed graphs. A cycle is fatal for simple DAG agents, 
        # but some agents MAY want loops (Retry Loops). 
        # However, for Safety, we usually warn or error on unintended cycles.
        # For this implementation, we will act as a strict DAG enforcer to prevent infinite loops 
        # unless specifically annotated (future feature).
        
        # Checking for cycles using recursion stack
        visited = set()
        rec_stack = set()
        
        def has_cycle(u):
            visited.add(u)
            rec_stack.add(u)
            
            for v in adj_list[u]:
                if v not in visited:
                    if has_cycle(v):
                        return True
                elif v in rec_stack:
                    return True
            
            rec_stack.remove(u)
            return False

        # Check from entry node first (most important)
        if graph_spec.entry_node not in node_ids:
             return ValidationResult(False, f"Entry node '{graph_spec.entry_node}' not found in nodes")
             
        # Full scan (in case of disconnected components that might be triggered async)
        # But actually, only reachable cycles matter usually? 
        # Let's scan all nodes to be safe.
        for node_id in node_ids:
            if node_id not in visited:
                if has_cycle(node_id):
                    return ValidationResult(False, f"Cycle detected involving node '{node_id}'")

        # 3. Connectivity/Reachability (optional strictness)
        # Verify that all nodes are reachable from entry_node (BFS)
        # Disconnected islands are technically dead code.
        reachable = set()
        queue = [graph_spec.entry_node]
        reachable.add(graph_spec.entry_node)
        
        from collections import deque
        q = deque([graph_spec.entry_node])
        
        while q:
            u = q.popleft()
            for v in adj_list[u]:
                if v not in reachable:
                    reachable.add(v)
                    q.append(v)
                    
        # Check against all nodes
        unreachable = node_ids - reachable
        # Note: "start" node might be isolated if we are mutating? 
        # For now, we Log Warn but maybe not Fail? 
        # User requested "Connectivity", let's fail if significant islands exist?
        # Let's return Valid but with warning logic handled by caller? 
        # No, simpler: Fail. Dead code is messy.
        if unreachable:
             return ValidationResult(False, f"Unreachable nodes detected: {unreachable}")

        return ValidationResult(True)


class OutputValidator:
    """
    Validates output from nodes against schema.
    Restored to maintain compatibility with GraphExecutor.
    """
    
    def validate_all(
        self,
        output: Dict[str, Any],
        expected_keys: List[str],
        check_hallucination: bool = True
    ) -> ValidationResult:
        """
        Validate that output contains all expected keys.
        """
        missing = [key for key in expected_keys if key not in output]
        if missing:
            return ValidationResult(False, f"Missing required output keys: {missing}")
            
        return ValidationResult(True)
