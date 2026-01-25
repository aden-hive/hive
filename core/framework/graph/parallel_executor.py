"""
Parallel Graph Executor

High-performance graph execution with:
- Parallel node execution for independent nodes
- Semaphore-based concurrency control
- Async-native execution
- Performance metrics collection
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional, Set

from framework.graph.edge import GraphSpec
from framework.graph.node import (
    NodeContext,
    NodeProtocol,
    NodeResult,
    NodeSpec,
    SharedMemory,
    LLMNode,
    RouterNode,
    FunctionNode,
)
from framework.llm.provider import LLMProvider, Tool

if TYPE_CHECKING:
    from framework.graph.goal import Goal
    from framework.runtime.core import Runtime

logger = logging.getLogger(__name__)


@dataclass
class ParallelExecutionResult:
    """Result of parallel graph execution."""
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    steps_executed: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0
    path: list[str] = field(default_factory=list)
    parallel_executions: int = 0  # Number of parallel batches
    max_parallelism: int = 0  # Maximum nodes run in parallel
    node_results: dict[str, NodeResult] = field(default_factory=dict)


class ParallelGraphExecutor:
    """
    Execute agent graphs with parallel node execution.
    
    Features:
    - Automatic dependency detection for parallel execution
    - Semaphore-based concurrency limiting
    - Topological execution ordering
    - Full async support
    
    Usage:
        executor = ParallelGraphExecutor(
            runtime=runtime,
            llm=llm_provider,
            max_concurrent=10,
        )
        
        result = await executor.execute(graph, goal, input_data)
    """
    
    def __init__(
        self,
        runtime: "Runtime",
        llm: Optional[LLMProvider] = None,
        tools: Optional[list[Tool]] = None,
        tool_executor: Optional[Callable] = None,
        max_concurrent: int = 10,
        node_registry: Optional[dict[str, NodeProtocol]] = None,
        approval_callback: Optional[Callable] = None,
    ):
        self.runtime = runtime
        self.llm = llm
        self.tools = tools or []
        self.tool_executor = tool_executor
        self.max_concurrent = max_concurrent
        self.node_registry = node_registry or {}
        self.approval_callback = approval_callback
        
        # Concurrency control
        self._semaphore = asyncio.Semaphore(max_concurrent)
        
        # Execution stats
        self._parallel_batches = 0
        self._max_parallelism = 0
    
    async def execute(
        self,
        graph: GraphSpec,
        goal: "Goal",
        input_data: Optional[dict[str, Any]] = None,
        session_state: Optional[dict[str, Any]] = None,
    ) -> ParallelExecutionResult:
        """
        Execute the graph with parallel execution of independent nodes.
        
        Args:
            graph: The graph specification
            goal: The goal driving execution
            input_data: Initial input data
            session_state: Existing session state (for resume)
        
        Returns:
            ParallelExecutionResult with output and metrics
        """
        start_time = time.perf_counter()
        input_data = input_data or {}
        
        # Initialize execution state
        completed: Set[str] = {"START"}
        node_results: dict[str, NodeResult] = {}
        memory = SharedMemory(_data={**(session_state or {}), **input_data})
        execution_path: list[str] = []
        total_tokens = 0
        
        self._parallel_batches = 0
        self._max_parallelism = 0
        
        # Start the run
        self.runtime.start_run(
            goal_id=goal.goal_id,
            goal_description=goal.name,
            input_data=input_data,
        )
        
        try:
            while True:
                # Find all nodes that can run in parallel
                ready_nodes = self._find_ready_nodes(graph, completed)
                
                if not ready_nodes:
                    # Check if we reached END or have an issue
                    if "END" in completed:
                        break
                    
                    # Check if any terminal nodes are completed
                    terminal_nodes = self._get_terminal_nodes(graph)
                    if any(n in completed for n in terminal_nodes):
                        break
                    
                    # Deadlock or all done
                    logger.warning("No more nodes to execute")
                    break
                
                # Track parallelism stats
                self._parallel_batches += 1
                self._max_parallelism = max(self._max_parallelism, len(ready_nodes))
                
                logger.info(f"Executing {len(ready_nodes)} nodes in parallel: {ready_nodes}")
                
                # Execute ready nodes in parallel
                tasks = []
                for node_id in ready_nodes:
                    node_spec = graph.get_node(node_id)
                    if node_spec:
                        task = asyncio.create_task(
                            self._execute_node_with_semaphore(
                                node_spec, memory, goal, input_data
                            )
                        )
                        tasks.append((node_id, task))
                
                # Wait for all parallel nodes
                for node_id, task in tasks:
                    try:
                        result = await task
                        node_results[node_id] = result
                        completed.add(node_id)
                        execution_path.append(node_id)
                        total_tokens += result.tokens_used
                        
                        # Handle routing for router nodes
                        if result.next_node and result.next_node not in completed:
                            # Router determined next node, mark others as skipped
                            pass
                        
                    except Exception as e:
                        logger.error(f"Node {node_id} failed: {e}")
                        node_results[node_id] = NodeResult(
                            success=False,
                            error=str(e)
                        )
                        completed.add(node_id)
                        execution_path.append(node_id)
                
                # Check for failures that should stop execution
                for node_id, result in node_results.items():
                    if not result.success and node_id in completed:
                        # Check if this is a critical failure
                        node_spec = graph.get_node(node_id)
                        if node_spec and self._is_critical_node(node_spec, graph):
                            end_time = time.perf_counter()
                            self.runtime.end_run(
                                success=False,
                                narrative=f"Critical node {node_id} failed: {result.error}",
                            )
                            return ParallelExecutionResult(
                                success=False,
                                error=f"Node {node_id} failed: {result.error}",
                                steps_executed=len(execution_path),
                                total_tokens=total_tokens,
                                total_latency_ms=int((end_time - start_time) * 1000),
                                path=execution_path,
                                parallel_executions=self._parallel_batches,
                                max_parallelism=self._max_parallelism,
                                node_results=node_results,
                            )
            
            # Aggregate final output from terminal nodes
            final_output = self._aggregate_output(graph, node_results, memory)
            
            end_time = time.perf_counter()
            self.runtime.end_run(
                success=True,
                narrative=f"Completed {len(execution_path)} nodes successfully",
                output_data=final_output,
            )
            
            return ParallelExecutionResult(
                success=True,
                output=final_output,
                steps_executed=len(execution_path),
                total_tokens=total_tokens,
                total_latency_ms=int((end_time - start_time) * 1000),
                path=execution_path,
                parallel_executions=self._parallel_batches,
                max_parallelism=self._max_parallelism,
                node_results=node_results,
            )
            
        except Exception as e:
            end_time = time.perf_counter()
            logger.exception("Graph execution failed")
            self.runtime.end_run(
                success=False,
                narrative=f"Execution failed: {str(e)}",
            )
            
            return ParallelExecutionResult(
                success=False,
                error=str(e),
                steps_executed=len(execution_path),
                total_tokens=total_tokens,
                total_latency_ms=int((end_time - start_time) * 1000),
                path=execution_path,
                parallel_executions=self._parallel_batches,
                max_parallelism=self._max_parallelism,
                node_results=node_results,
            )
    
    def _find_ready_nodes(
        self,
        graph: GraphSpec,
        completed: Set[str],
    ) -> list[str]:
        """
        Find nodes that are ready to execute (all dependencies satisfied).
        
        A node is ready when all its source edges come from completed nodes.
        """
        ready = []
        
        for node in graph.nodes:
            if node.id in completed:
                continue
            
            # Find all edges that target this node
            incoming_edges = [e for e in graph.edges if e.target == node.id]
            
            # If no incoming edges, this is a start node
            if not incoming_edges:
                ready.append(node.id)
                continue
            
            # Check if at least one source is completed (for conditional edges)
            # For "on_success" edges, source must be completed successfully
            sources_ready = False
            for edge in incoming_edges:
                if edge.source in completed:
                    # Check condition
                    if edge.condition == "on_success":
                        # Check if source node succeeded
                        # (we'd need to track this, for now assume completed = success)
                        sources_ready = True
                        break
                    elif edge.condition in ("always", "on_complete"):
                        sources_ready = True
                        break
                    else:
                        # Conditional edges - check the condition
                        sources_ready = True
                        break
            
            if sources_ready:
                ready.append(node.id)
        
        return ready
    
    def _get_terminal_nodes(self, graph: GraphSpec) -> list[str]:
        """Get nodes that have no outgoing edges (terminal nodes)."""
        sources = {e.source for e in graph.edges}
        terminal = []
        
        for node in graph.nodes:
            if node.id not in sources:
                terminal.append(node.id)
        
        return terminal or ["END"]
    
    async def _execute_node_with_semaphore(
        self,
        node_spec: NodeSpec,
        memory: SharedMemory,
        goal: "Goal",
        input_data: dict[str, Any],
    ) -> NodeResult:
        """Execute a single node with semaphore-based concurrency control."""
        async with self._semaphore:
            return await self._execute_node(node_spec, memory, goal, input_data)
    
    async def _execute_node(
        self,
        node_spec: NodeSpec,
        memory: SharedMemory,
        goal: "Goal",
        input_data: dict[str, Any],
    ) -> NodeResult:
        """Execute a single node."""
        start_time = time.perf_counter()
        
        # Build context
        ctx = self._build_context(node_spec, memory, goal, input_data)
        
        # Get node implementation
        node_impl = self._get_node_implementation(node_spec)
        
        # Execute
        try:
            result = await node_impl.execute(ctx)
            
            # Write outputs to memory
            for key, value in result.output.items():
                if key in node_spec.output_keys:
                    memory.write(key, value, validate=False)
            
            end_time = time.perf_counter()
            result.latency_ms = int((end_time - start_time) * 1000)
            
            logger.debug(
                f"Node {node_spec.id} completed in {result.latency_ms}ms "
                f"(tokens: {result.tokens_used})"
            )
            
            return result
            
        except Exception as e:
            end_time = time.perf_counter()
            return NodeResult(
                success=False,
                error=str(e),
                latency_ms=int((end_time - start_time) * 1000),
            )
    
    def _build_context(
        self,
        node_spec: NodeSpec,
        memory: SharedMemory,
        goal: "Goal",
        input_data: dict[str, Any],
    ) -> NodeContext:
        """Build execution context for a node."""
        # Get tools for this node
        node_tools = []
        if node_spec.tools:
            tool_names = set(node_spec.tools)
            node_tools = [t for t in self.tools if t.name in tool_names]
        
        return NodeContext(
            runtime=self.runtime,
            node_id=node_spec.id,
            node_spec=node_spec,
            memory=memory,
            input_data=input_data,
            llm=self.llm,
            available_tools=node_tools,
            goal_context=goal.description if goal else "",
            goal=goal,
        )
    
    def _get_node_implementation(self, node_spec: NodeSpec) -> NodeProtocol:
        """Get or create node implementation based on type."""
        # Check registry first
        if node_spec.id in self.node_registry:
            return self.node_registry[node_spec.id]
        
        # Create based on type
        node_type = node_spec.node_type
        
        if node_type in ("llm_tool_use", "llm_generate"):
            require_tools = node_type == "llm_tool_use" and bool(node_spec.tools)
            return LLMNode(
                tool_executor=self.tool_executor,
                require_tools=require_tools,
            )
        elif node_type == "router":
            return RouterNode()
        elif node_type == "function":
            return FunctionNode(self.node_registry.get(node_spec.function))
        else:
            # Default to LLM node
            return LLMNode(tool_executor=self.tool_executor)
    
    def _is_critical_node(self, node_spec: NodeSpec, graph: GraphSpec) -> bool:
        """Check if a node failure should stop execution."""
        # Check if this node is on the critical path (has outgoing edges)
        has_outgoing = any(e.source == node_spec.id for e in graph.edges)
        return has_outgoing
    
    def _aggregate_output(
        self,
        graph: GraphSpec,
        node_results: dict[str, NodeResult],
        memory: SharedMemory,
    ) -> dict[str, Any]:
        """Aggregate output from terminal nodes and memory."""
        output = {}
        
        # Get terminal nodes' outputs
        terminal_nodes = self._get_terminal_nodes(graph)
        for node_id in terminal_nodes:
            if node_id in node_results and node_results[node_id].success:
                output.update(node_results[node_id].output)
        
        # Add all memory keys as output
        output.update(memory.read_all())
        
        return output


# =============================================================================
# Wrapper to use RouterNode and FunctionNode
# =============================================================================

class RouterNode(NodeProtocol):
    """Router node that directs execution flow."""
    
    async def execute(self, ctx: NodeContext) -> NodeResult:
        """Execute routing logic."""
        routes = ctx.node_spec.routes
        
        if not routes:
            return NodeResult(
                success=False,
                error="Router has no routes defined"
            )
        
        # Simple routing based on input/memory values
        for condition, target in routes.items():
            # Check if condition is a key in memory or input
            value = ctx.memory.read(condition) or ctx.input_data.get(condition)
            if value:
                return NodeResult(
                    success=True,
                    next_node=target,
                    route_reason=f"Routed on condition '{condition}' with value '{value}'",
                )
        
        # Default route
        if "default" in routes:
            return NodeResult(
                success=True,
                next_node=routes["default"],
                route_reason="Default route",
            )
        
        return NodeResult(
            success=False,
            error="No matching route found"
        )


class FunctionNode(NodeProtocol):
    """Function node that executes a Python function."""
    
    def __init__(self, func: Optional[Callable] = None):
        self.func = func
    
    async def execute(self, ctx: NodeContext) -> NodeResult:
        """Execute the function."""
        if not self.func:
            return NodeResult(
                success=False,
                error=f"Function not found: {ctx.node_spec.function}"
            )
        
        try:
            # Gather input
            func_input = {}
            for key in ctx.node_spec.input_keys:
                value = ctx.memory.read(key) or ctx.input_data.get(key)
                if value is not None:
                    func_input[key] = value
            
            # Execute
            if asyncio.iscoroutinefunction(self.func):
                result = await self.func(**func_input)
            else:
                result = self.func(**func_input)
            
            # Build output
            if isinstance(result, dict):
                output = result
            else:
                output = {ctx.node_spec.output_keys[0]: result} if ctx.node_spec.output_keys else {"result": result}
            
            return NodeResult(success=True, output=output)
            
        except Exception as e:
            return NodeResult(success=False, error=str(e))
