import logging
from typing import List, Dict, Any, Set
from collections import deque

logger = logging.getLogger(__name__)

class ValidationResult:
    """
    Resultado de validação unificado. 
    Prioriza a estrutura da 'main' com compatibilidade para 'valid'.
    """
    def __init__(self, success: bool, errors: List[str] = None):
        self.success = success
        self.valid = success  
        self.errors = errors or []

    @property
    def error(self) -> str:
        """Retorna as mensagens de erro combinadas em uma única string."""
        return "; ".join(self.errors) if self.errors else ""

    def __bool__(self):
        return self.success

class GraphValidator:
    """
    Valida a integridade topológica e a segurança contra injeção de código.
    """

    @staticmethod
    def validate(graph_spec: Any) -> ValidationResult:
        """
        Validação Topológica: Verifica integridade, ciclos (DFS) e conectividade (BFS).
        """
        # 1. Verificação de Atributos Básicos
        if not all(hasattr(graph_spec, attr) for attr in ["nodes", "edges", "entry_node"]):
            return ValidationResult(False, ["GraphSpec missing required attributes (nodes, edges, entry_node)"])

        node_ids = {n.id for n in graph_spec.nodes}
        adj_list = {n_id: [] for n_id in node_ids}
        
        for edge in graph_spec.edges:
            if edge.source not in node_ids or edge.target not in node_ids:
                return ValidationResult(False, [f"Edge references invalid node: {edge.source}->{edge.target}"])
            adj_list[edge.source].append(edge.target)

        if graph_spec.entry_node not in node_ids:
            return ValidationResult(False, [f"Entry node '{graph_spec.entry_node}' not found"])

        # 2. Detecção de Ciclos (DFS)
        visited, rec_stack = set(), set()
        
        def has_cycle(u):
            visited.add(u)
            rec_stack.add(u)
            for v in adj_list[u]:
                if v not in visited:
                    if has_cycle(v): return True
                elif v in rec_stack: return True
            rec_stack.remove(u)
            return False

        for node_id in node_ids:
            if node_id not in visited:
                if has_cycle(node_id):
                    return ValidationResult(False, [f"Cycle detected involving node '{node_id}'"])

        # 3. Verificação de Conectividade (BFS)
        reachable = {graph_spec.entry_node}
        q = deque([graph_spec.entry_node])
        
        while q:
            u = q.popleft()
            for v in adj_list[u]:
                if v not in reachable:
                    reachable.add(v)
                    q.append(v)
                        
        unreachable = node_ids - reachable
        if unreachable:
            return ValidationResult(False, [f"Unreachable nodes: {unreachable}"])

        return ValidationResult(True)

    def _contains_code_indicators(self, value: str) -> bool:
        """Verifica padrões de código (Python, JS, SQL, HTML) para evitar injeção."""
        code_indicators = [
            "def ", "class ", "import ", "from ", "async def ", "await ",
            "function ", "const ", "let ", "=> {", "SELECT ", "INSERT ", 
            "DROP ", "<script", "<?php"
        ]

        if len(value) < 10000:
            return any(ind in value for ind in code_indicators)
        
        # Amostragem estratégica para strings longas (Start, 25%, 50%, 75%, End)
        sample_positions = [0, len(value)//4, len(value)//2, 3*len(value)//4, max(0, len(value)-2000)]
        for pos in sample_positions:
            chunk = value[pos : pos + 2000]
            if any(ind in chunk for ind in code_indicators):
                return True
        return False

    def validate_output_keys(
        self, output: Dict[str, Any], expected_keys: List[str], max_length: int = 5000
    ) -> ValidationResult:
        """Valida presença, comprimento e segurança das chaves de saída."""
        if not isinstance(output, dict):
            return ValidationResult(False, [f"Output is not a dict, got {type(output).__name__}"])

        errors = []
        for key in expected_keys:
            if key not in output:
                errors.append(f"Missing expected key: {key}")
                continue
            
            val_str = str(output[key])
            if self._contains_code_indicators(val_str):
                logger.warning(f"Security Warning: Key '{key}' may contain code indicators.")

            if len(val_str) > max_length:
                errors.append(f"Key '{key}' exceeds max length ({len(val_str)} > {max_length})")

        return ValidationResult(len(errors) == 0, errors)