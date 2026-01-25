from typing import Dict, Any, List, Optional
from framework.graph.node import NodeProtocol, NodeContext, NodeResult
from framework.graph.mutation import GraphDelta

class DynamicEvolutionNode(NodeProtocol):
    """
    Node that decides if the current graph structure is sufficient 
    or if it needs to request an evolution (mutation) based on memory.
    
    Standard Flow:
    1. Recall memories related to current goal.
    2. Analyze failure rate.
    3. If high failure rate, trigger evolution.
    """
    
    def __init__(self, failure_threshold: float = 0.5):
        self.failure_threshold = failure_threshold

    async def execute(self, ctx: NodeContext) -> NodeResult:
        query = ctx.input_data.get("goal") or ctx.input_data.get("query")
        if not query:
            return NodeResult(success=True, output={"status": "no_query_to_analyze"})

        runtime = ctx.runtime
        if not hasattr(runtime, "memory_hub"):
             return NodeResult(success=True, output={"status": "no_memory_hub"})

        # 1. Recupera sucessos e falhas similares (RAG)
        # We want to see both to calculate rate
        memories = await runtime.memory_hub.recall(query, top_k=10)
        
        # 2. Analisa se o caminho atual costuma falhar
        failure_rate, critical_failures = self._analyze_failures(memories)
        
        if failure_rate > self.failure_threshold:
            # GATILHO DE EVOLUÇÃO
            # Construir instrução de evolução baseada no que falhou vs o que funcionou
            evolution_instruction = self._build_evolution_instruction(query, critical_failures, memories)
            
            # In a real scenario, this output would be consumed by a "Coding Agent" 
            # or a "GraphBuilder" node next in the chain.
            # We mark it as 'trigger_evolution' for the runtime or next node to pick up.
            
            return NodeResult(
                success=False, # Mark as 'failure' to stop standard flow if needed, branch to evolution
                output={
                    "trigger_evolution": True, 
                    "instruction": evolution_instruction,
                    "reason": f"High failure rate ({failure_rate:.2%}) detected for this goal."
                }
            )
            
        return NodeResult(success=True, output={"path": "continue_standard", "failure_rate": failure_rate})

    def _analyze_failures(self, memories: List[Dict[str, Any]]) -> tuple[float, List[Dict[str, Any]]]:
        if not memories:
            return 0.0, []
            
        failure_count = 0
        failures = []
        
        for m in memories:
            outcome = m.get('outcome') # Now top-level key from Hub
            if outcome == 'failure':
                failure_count += 1
                failures.append(m)
                
        rate = failure_count / len(memories)
        return rate, failures

    def _build_evolution_instruction(self, query: str, failures: List[Dict[str, Any]], all_memories: List[Dict[str, Any]]) -> str:
        # Simple prompt construction
        # Find if there are ANY successes for similar query to use as example
        successes = [m for m in all_memories if m.get('outcome') == 'success']
        
        instruction = f"Goal '{query}' has a high failure rate.\n"
        if successes:
            best_practice = successes[0]['content'] # heuristic: pick first success
            instruction += f"SUGGESTION: Adapt graph to match successful pattern: {best_practice}\n"
        else:
            instruction += "SUGGESTION: Current approach fails consistently. Attempt distinct strategy.\n"
            
        instruction += "\nRecent Failures:\n"
        for f in failures[:3]:
            instruction += f"- {f['content']}\n"
            
        return instruction
