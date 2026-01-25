from typing import Dict, Any, List
from framework.graph.node import NodeProtocol, NodeContext, NodeResult
from framework.memory.hub import MemoryHub

class MemoryRecallNode(NodeProtocol):
    """
    Node that retrieves context from the Persistent Memory Hub.
    Concept: 'Recall' before 'Act'.
    """
    
    async def execute(self, ctx: NodeContext) -> NodeResult:
        """
        Executes memory retrieval.
        """
        
        # 1. Identify what to search for
        # Try input keys first, then goal context
        query = ctx.input_data.get("goal") or ctx.input_data.get("query") or ctx.input_data.get("user_query")
        
        if not query and ctx.goal_context:
            query = ctx.goal_context
            
        if not query:
            # Nothing to search, pass success but no change
            return NodeResult(success=True, output={})
            
        # 2. Access the Hub via Runtime
        # The runtime MUST have 'memory_hub' initialized.
        runtime = ctx.runtime
        if not hasattr(runtime, "memory_hub"):
            # If memory system is not active, just warn
            return NodeResult(success=True, output={}, error="Memory Hub not available")
            
        hub: MemoryHub = runtime.memory_hub
        
        # 3. Recall
        # top_k=3 is a good default for context window limits
        
        # Check for optional outcome filtering
        filters = {}
        outcome_filter = ctx.input_data.get("recall_outcome")
        if outcome_filter:
            filters["execution_outcome"] = outcome_filter

        past_experiences = await hub.recall(query, top_k=3, filters=filters)
        
        # 4. Inject into Context (Shared Memory)
        # formatting as a clean string or keeping structured
        context_str = "\n".join([f"- {m['content']}" for m in past_experiences])
        
        # Safety: Limit context size to prevent overflow (simplistic char limit)
        MAX_CONTEXT_CHARS = 4000
        if len(context_str) > MAX_CONTEXT_CHARS:
            context_str = context_str[:MAX_CONTEXT_CHARS] + "... (truncated)"
        
        output = {
            "historical_context": context_str,
            "raw_memories": past_experiences
        }
        
        # Write to shared memory if output keys are defined, or just return result
        # Typically the graph wiring handles mapping, but we can write to memory directly if needed
        # For now, we return it in output for the Executor/Edge to handle or next node to read
        # But per NodeProtocol pattern, we should write to ctx.memory if we want explicit availability
        ctx.memory.write("historical_context", context_str)
        
        return NodeResult(success=True, output=output)


class MemoryLearnNode(NodeProtocol):
    """
    Node that saves the result of an action to the Persistent Memory Hub.
    Concept: 'Learn' after 'Act'.
    """
    async def execute(self, ctx: NodeContext) -> NodeResult:
        """
        Learns from execution.
        
        Expected Input:
        - "learn_text": The content to remember (e.g. "Deployment worked with flag --force")
        - "learn_metadata": Optional dict of metadata
        """
        text = ctx.input_data.get("learn_text")
        if not text:
            # Maybe try to learn from the output of the *previous* node if available in memory?
            # For now, explicit input only.
            return NodeResult(success=True, output={}, error="No 'learn_text' provided to learn.")
            
        runtime = ctx.runtime
        if not hasattr(runtime, "memory_hub"):
            return NodeResult(success=True, output={}, error="Memory Hub not available")
            
        metadata = ctx.input_data.get("learn_metadata", {})
        metadata["source_node"] = ctx.node_id
        outcome = ctx.input_data.get("learn_outcome") # e.g. "success", "failure"
        
        await runtime.memory_hub.remember(text, metadata, outcome=outcome, source_type="internal")
        
        return NodeResult(success=True, output={"status": "memorized"})

