"""
Graph Executor - Runs agent graphs.

The executor:
1. Takes a GraphSpec and Goal
2. Initializes shared memory
3. Executes nodes following edges
4. Records all decisions to Runtime
5. Returns the final result
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from framework.graph.edge import EdgeSpec, GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import (
    FunctionNode,
    LLMNode,
    NodeContext,
    NodeProtocol,
    NodeResult,
    NodeSpec,
    RouterNode,
    SharedMemory,
)
from framework.graph.output_cleaner import CleansingConfig, OutputCleaner
from framework.graph.validator import OutputValidator
from framework.llm.provider import LLMProvider, Tool
from framework.runtime.core import Runtime


@dataclass
class ExecutionResult:
    """Result of executing a graph."""

    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    steps_executed: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0
    path: list[str] = field(default_factory=list)  # Node IDs traversed
    paused_at: str | None = None  # Node ID where execution paused for HITL
    session_state: dict[str, Any] = field(default_factory=dict)  # State to resume from


@dataclass
class ParallelBranch:
    """Tracks a single branch in parallel fan-out execution."""

    branch_id: str
    node_id: str
    edge: EdgeSpec
    result: "NodeResult | None" = None
    status: str = "pending"  # pending, running, completed, failed
    retry_count: int = 0
    error: str | None = None


@dataclass
class ParallelExecutionConfig:
    """Configuration for parallel execution behavior."""

    # Error handling: "fail_all" cancels all on first failure,
    # "continue_others" lets remaining branches complete,
    # "wait_all" waits for all and reports all failures
    on_branch_failure: str = "fail_all"

    # Memory conflict handling when branches write same key
    memory_conflict_strategy: str = "last_wins"  # "last_wins", "first_wins", "error"

    # Timeout per branch in seconds
    branch_timeout_seconds: float = 300.0


class GraphExecutor:
    """
    Executes agent graphs.

    Example:
        executor = GraphExecutor(
            runtime=runtime,
            llm=llm,
            tools=tools,
            tool_executor=my_tool_executor,
        )

        result = await executor.execute(
            graph=graph_spec,
            goal=goal,
            input_data={"expression": "2 + 3"},
        )
    """

    def __init__(
        self,
        runtime: Runtime,
        llm: LLMProvider | None = None,
        tools: list[Tool] | None = None,
        tool_executor: Callable | None = None,
        node_registry: dict[str, NodeProtocol] | None = None,
        approval_callback: Callable | None = None,
        cleansing_config: CleansingConfig | None = None,
        enable_parallel_execution: bool = True,
        parallel_config: ParallelExecutionConfig | None = None,
    ):
        """
        Initialize the executor.

        Args:
            runtime: Runtime for decision logging
            llm: LLM provider for LLM nodes
            tools: Available tools
            tool_executor: Function to execute tools
            node_registry: Custom node implementations by ID
            approval_callback: Optional callback for human-in-the-loop approval
            cleansing_config: Optional output cleansing configuration
            enable_parallel_execution: Enable parallel fan-out execution (default True)
            parallel_config: Configuration for parallel execution behavior
        """
        self.runtime = runtime
        self.llm = llm
        self.tools = tools or []
        self.tool_executor = tool_executor
        self.node_registry = node_registry or {}
        self.approval_callback = approval_callback
        self.validator = OutputValidator()
        self.logger = logging.getLogger(__name__)

        # Initialize output cleaner
        self.cleansing_config = cleansing_config or CleansingConfig()
        self.output_cleaner = OutputCleaner(
            config=self.cleansing_config,
            llm_provider=llm,
        )

        # Parallel execution settings
        self.enable_parallel_execution = enable_parallel_execution
        self._parallel_config = parallel_config or ParallelExecutionConfig()

    def _validate_tools(self, graph: GraphSpec) -> list[str]:
        """
        Validate that all tools declared by nodes are available.

        Returns:
            List of error messages (empty if all tools are available)
        """
        errors = []
        available_tool_names = {t.name for t in self.tools}

        for node in graph.nodes:
            if node.tools:
                missing = set(node.tools) - available_tool_names
                if missing:
                    available = sorted(available_tool_names) if available_tool_names else "none"
                    errors.append(
                        f"Node '{node.name}' (id={node.id}) requires tools "
                        f"{sorted(missing)} but they are not registered. "
                        f"Available tools: {available}"
                    )

        return errors

    async def execute(
        self,
        graph: GraphSpec,
        goal: Goal,
        input_data: dict[str, Any] | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """
        Execute a graph for a goal.

        Args:
            graph: The graph specification
            goal: The goal driving execution
            input_data: Initial input data
            session_state: Optional session state to resume from (with paused_at, memory, etc.)

        Returns:
            ExecutionResult with output and metrics
        """
        # Validate graph
        errors = graph.validate()
        if errors:
            return ExecutionResult(
                success=False,
                error=f"Invalid graph: {errors}",
            )

        # Validate tool availability
        tool_errors = self._validate_tools(graph)
        if tool_errors:
            self.logger.error("❌ Tool validation failed:")
            for err in tool_errors:
                self.logger.error(f"   • {err}")
            return ExecutionResult(
                success=False,
                error=(
                    f"Missing tools: {'; '.join(tool_errors)}. "
                    "Register tools via ToolRegistry or remove tool declarations from nodes."
                ),
            )

        # Initialize execution state
        memory = SharedMemory()

        # Restore session state if provided
        if session_state and "memory" in session_state:
            memory_data = session_state["memory"]
            # [RESTORED] Type safety check
            if not isinstance(memory_data, dict):
                self.logger.warning(
                    f"⚠️ Invalid memory data type in session state: "
                    f"{type(memory_data).__name__}, expected dict"
                )
            else:
                # Restore memory from previous session
                for key, value in memory_data.items():
                    memory.write(key, value)
                self.logger.info(f"📥 Restored session state with {len(memory_data)} memory keys")

        # Write new input data to memory (each key individually)
        if input_data:
            for key, value in input_data.items():
                memory.write(key, value)

        path: list[str] = []
        total_tokens = 0
        total_latency = 0
        node_retry_counts: dict[str, int] = {}  # Track retries per node

        # Determine entry point (may differ if resuming)
        current_node_id = graph.get_entry_point(session_state)
        steps = 0

        if session_state and current_node_id != graph.entry_node:
            self.logger.info(f"🔄 Resuming from: {current_node_id}")

        # Start run
        _run_id = self.runtime.start_run(
            goal_id=goal.id,
            goal_description=goal.description,
            input_data=input_data or {},
        )

        self.logger.info(f"🚀 Starting execution: {goal.name}")
        self.logger.info(f"   Goal: {goal.description}")
        self.logger.info(f"   Entry node: {graph.entry_node}")

        try:
            while steps < graph.max_steps:
                steps += 1

                # Get current node
                node_spec = graph.get_node(current_node_id)
                if node_spec is None:
                    raise RuntimeError(f"Node not found: {current_node_id}")

                path.append(current_node_id)

                # Check if pause (HITL) before execution
                if current_node_id in graph.pause_nodes:
                    self.logger.info(f"⏸ Paused at HITL node: {node_spec.name}")
                    # Execute this node, then pause
                    # (We'll check again after execution and save state)

                self.logger.info(f"\n▶ Step {steps}: {node_spec.name} ({node_spec.node_type})")
                self.logger.info(f"   Inputs: {node_spec.input_keys}")
                self.logger.info(f"   Outputs: {node_spec.output_keys}")

                # Build context for node
                ctx = self._build_context(
                    node_spec=node_spec,
                    memory=memory,
                    goal=goal,
                    input_data=input_data or {},
                    max_tokens=graph.max_tokens,
                )

                # Log actual input data being read
                if node_spec.input_keys:
                    self.logger.info("   Reading from memory:")
                    for key in node_spec.input_keys:
                        value = memory.read(key)
                        if value is not None:
                            # Truncate long values for readability
                            value_str = str(value)
                            if len(value_str) > 200:
                                value_str = value_str[:200] + "..."
                            self.logger.info(f"      {key}: {value_str}")

                # Get or create node implementation
                node_impl = self._get_node_implementation(node_spec, graph.cleanup_llm_model)

                # Validate inputs
                validation_errors = node_impl.validate_input(ctx)
                if validation_errors:
                    self.logger.warning(f"⚠ Validation warnings: {validation_errors}")
                    self.runtime.report_problem(
                        severity="warning",
                        description=f"Validation errors for {current_node_id}: {validation_errors}",
                    )

                # Execute node
                self.logger.info("   Executing...")
                result = await node_impl.execute(ctx)

                if result.success:
                    # Validate output before accepting it
                    if result.output and node_spec.output_keys:
                        validation = self.validator.validate_all(
                            output=result.output,
                            expected_keys=node_spec.output_keys,
                            check_hallucination=True,
                        )
                        if not validation.success:
                            self.logger.error(f"   ✗ Output validation failed: {validation.error}")
                            result = NodeResult(
                                success=False,
                                error=f"Output validation failed: {validation.error}",
                                output={},
                                tokens_used=result.tokens_used,
                                latency_ms=result.latency_ms,
                            )

                if result.success:
                    self.logger.info(
                        f"   ✓ Success (tokens: {result.tokens_used}, "
                        f"latency: {result.latency_ms}ms)"
                    )

                    # Generate and log human-readable summary
                    summary = result.to_summary(node_spec)
                    self.logger.info(f"   📝 Summary: {summary}")

                    # Log what was written to memory (detailed view)
                    if result.output:
                        self.logger.info("   Written to memory:")
                        for key, value in result.output.items():
                            value_str = str(value)
                            if len(value_str) > 200:
                                value_str = value_str[:200] + "..."
                            self.logger.info(f"      {key}: {value_str}")
                else:
                    self.logger.error(f"   ✗ Failed: {result.error}")

                total_tokens += result.tokens_used
                total_latency += result.latency_ms

                # Handle failure
                if not result.success:
                    # Track retries per node
                    node_retry_counts[current_node_id] = (
                        node_retry_counts.get(current_node_id, 0) + 1
                    )

                    # [CORRECTED] Use node_spec.max_retries instead of hardcoded 3
                    max_retries = getattr(node_spec, "max_retries", 3)

                    if node_retry_counts[current_node_id] < max_retries:
                        # Retry - don't increment steps for retries
                        steps -= 1

                        # --- EXPONENTIAL BACKOFF ---
                        retry_count = node_retry_counts[current_node_id]
                        # Backoff formula: 1.0 * (2^(retry - 1)) -> 1s, 2s, 4s...
                        delay = 1.0 * (2 ** (retry_count - 1))
                        self.logger.info(f"   Using backoff: Sleeping {delay}s before retry...")
                        await asyncio.sleep(delay)
                        # --------------------------------------

                        self.logger.info(
                            f"   ↻ Retrying ({node_retry_counts[current_node_id]}/{max_retries})..."
                        )
                        continue
                    else:
                        # Max retries exceeded - fail the execution
                        self.logger.error(
                            f"   ✗ Max retries ({max_retries}) exceeded for node {current_node_id}"
                        )
                        self.runtime.report_problem(
                            severity="critical",
                            description=(
                                f"Node {current_node_id} failed after "
                                f"{max_retries} attempts: {result.error}"
                            ),
                        )
                        self.runtime.end_run(
                            success=False,
                            output_data=memory.read_all(),
                            narrative=(
                                f"Failed at {node_spec.name} after "
                                f"{max_retries} retries: {result.error}"
                            ),
                        )
                        return ExecutionResult(
                            success=False,
                            error=(
                                f"Node '{node_spec.name}' failed after "
                                f"{max_retries} attempts: {result.error}"
                            ),
                            output=memory.read_all(),
                            steps_executed=steps,
                            total_tokens=total_tokens,
                            total_latency_ms=total_latency,
                            path=path,
                        )

                # Check if we just executed a pause node - if so, save state and return
                # This must happen BEFORE determining next node, since pause nodes may have no edges
                if node_spec.id in graph.pause_nodes:
                    self.logger.info("💾 Saving session state after pause node")
                    saved_memory = memory.read_all()
                    session_state_out = {
                        "paused_at": node_spec.id,
                        "resume_from": f"{node_spec.id}_resume",  # Resume key
                        "memory": saved_memory,
                        "next_node": None,  # Will resume from entry point
                    }

                    self.runtime.end_run(
                        success=True,
                        output_data=saved_memory,
                        narrative=f"Paused at {node_spec.name} after {steps} steps",
                    )

                    return ExecutionResult(
                        success=True,
                        output=saved_memory,
                        steps_executed=steps,
                        total_tokens=total_tokens,
                        total_latency_ms=total_latency,
                        path=path,
                        paused_at=node_spec.id,
                        session_state=session_state_out,
                    )

                # Check if this is a terminal node - if so, we're done
                if node_spec.id in graph.terminal_nodes:
                    self.logger.info(f"✓ Reached terminal node: {node_spec.name}")
                    break

                # Determine next node
                if result.next_node:
                    # Router explicitly set next node
                    self.logger.info(f"   → Router directing to: {result.next_node}")
                    current_node_id = result.next_node
                else:
                    # Get all traversable edges for fan-out detection
                    traversable_edges = self._get_all_traversable_edges(
                        graph=graph,
                        goal=goal,
                        current_node_id=current_node_id,
                        current_node_spec=node_spec,
                        result=result,
                        memory=memory,
                    )

                    if not traversable_edges:
                        self.logger.info("   → No more edges, ending execution")
                        break  # No valid edge, end execution

                    # Check for fan-out (multiple traversable edges)
                    if self.enable_parallel_execution and len(traversable_edges) > 1:
                        # Find convergence point (fan-in node)
                        targets = [e.target for e in traversable_edges]
                        fan_in_node = self._find_convergence_node(graph, targets)

                        # Execute branches in parallel
                        (
                            _branch_results,
                            branch_tokens,
                            branch_latency,
                        ) = await self._execute_parallel_branches(
                            graph=graph,
                            goal=goal,
                            edges=traversable_edges,
                            memory=memory,
                            source_result=result,
                            source_node_spec=node_spec,
                            path=path,
                        )

                        total_tokens += branch_tokens
                        total_latency += branch_latency

                        # Continue from fan-in node
                        if fan_in_node:
                            self.logger.info(f"   ⑃ Fan-in: converging at {fan_in_node}")
                            current_node_id = fan_in_node
                        else:
                            # No convergence point - branches are terminal
                            self.logger.info("   → Parallel branches completed (no convergence)")
                            break
                    else:
                        # Sequential: follow single edge (existing logic via _follow_edges)
                        next_node = self._follow_edges(
                            graph=graph,
                            goal=goal,
                            current_node_id=current_node_id,
                            current_node_spec=node_spec,
                            result=result,
                            memory=memory,
                        )
                        if next_node is None:
                            self.logger.info("   → No more edges, ending execution")
                            break
                        next_spec = graph.get_node(next_node)
                        self.logger.info(f"   → Next: {next_spec.name if next_spec else next_node}")
                        current_node_id = next_node

                # Update input_data for next node
                input_data = result.output

            # Collect output
            output = memory.read_all()

            self.logger.info("\n✓ Execution complete!")
            self.logger.info(f"   Steps: {steps}")
            self.logger.info(f"   Path: {' → '.join(path)}")
            self.logger.info(f"   Total tokens: {total_tokens}")
            self.logger.info(f"   Total latency: {total_latency}ms")

            self.runtime.end_run(
                success=True,
                output_data=output,
                narrative=f"Executed {steps} steps through path: {' -> '.join(path)}",
            )

            return ExecutionResult(
                success=True,
                output=output,
                steps_executed=steps,
                total_tokens=total_tokens,
                total_latency_ms=total_latency,
                path=path,
            )

        except Exception as e:
            self.runtime.report_problem(
                severity="critical",
                description=str(e),
            )
            self.runtime.end_run(
                success=False,
                narrative=f"Failed at step {steps}: {e}",
            )
            return ExecutionResult(
                success=False,
                error=str(e),
                steps_executed=steps,
                path=path,
            )

    def _build_context(
        self,
        node_spec: NodeSpec,
        memory: SharedMemory,
        goal: Goal,
        input_data: dict[str, Any],
        max_tokens: int = 4096,
    ) -> NodeContext:
        """Build execution context for a node."""
        # Filter tools to those available to this node
        available_tools = []
        if node_spec.tools:
            available_tools = [t for t in self.tools if t.name in node_spec.tools]

        # Create scoped memory view
        scoped_memory = memory.with_permissions(
            read_keys=node_spec.input_keys,
            write_keys=node_spec.output_keys,
        )

        return NodeContext(
            runtime=self.runtime,
            node_id=node_spec.id,
            node_spec=node_spec,
            memory=scoped_memory,
            input_data=input_data,
            llm=self.llm,
            available_tools=available_tools,
            goal_context=goal.to_prompt_context(),
            goal=goal,  # Pass Goal object for LLM-powered routers
            max_tokens=max_tokens,
        )

    # Valid node types - no ambiguous "llm" type allowed
    VALID_NODE_TYPES = {"llm_tool_use", "llm_generate", "router", "function", "human_input"}

    def _get_node_implementation(
        self, node_spec: NodeSpec, cleanup_llm_model: str | None = None
    ) -> NodeProtocol:
        """Get or create a node implementation."""
        # Check registry first
        if node_spec.id in self.node_registry:
            return self.node_registry[node_spec.id]

        # Validate node type
        if node_spec.node_type not in self.VALID_NODE_TYPES:
            raise RuntimeError(
                f"Invalid node type '{node_spec.node_type}' for node '{node_spec.id}'. "
                f"Must be one of: {sorted(self.VALID_NODE_TYPES)}. "
                f"Use 'llm_tool_use' for nodes that call tools, 'llm_generate' for text generation."
            )

        # Create based on type
        if node_spec.node_type == "llm_tool_use":
            if not node_spec.tools:
                raise RuntimeError(
                    f"Node '{node_spec.id}' is type 'llm_tool_use' but declares no tools. "
                    "Either add tools to the node or change type to 'llm_generate'."
                )
            return LLMNode(
                tool_executor=self.tool_executor,
                require_tools=True,
                cleanup_llm_model=cleanup_llm_model,
            )

        if node_spec.node_type == "llm_generate":
            return LLMNode(
                tool_executor=None,
                require_tools=False,
                cleanup_llm_model=cleanup_llm_model,
            )

        if node_spec.node_type == "router":
            return RouterNode()

        if node_spec.node_type == "function":
            # Function nodes need explicit registration
            raise RuntimeError(
                f"Function node '{node_spec.id}' not registered. Register with node_registry."
            )

        if node_spec.node_type == "human_input":
            # Human input nodes are handled specially by HITL mechanism
            return LLMNode(
                tool_executor=None,
                require_tools=False,
                cleanup_llm_model=cleanup_llm_model,
            )

        # Should never reach here due to validation above
        raise RuntimeError(f"Unhandled node type: {node_spec.node_type}")

    def _follow_edges(
        self,
        graph: GraphSpec,
        goal: Goal,
        current_node_id: str,
        current_node_spec: Any,
        result: NodeResult,
        memory: SharedMemory,
    ) -> str | None:
        """Determine the next node by following edges."""
        edges = graph.get_outgoing_edges(current_node_id)

        for edge in edges:
            target_node_spec = graph.get_node(edge.target)

            if edge.should_traverse(
                source_success=result.success,
                source_output=result.output,
                memory=memory.read_all(),
                llm=self.llm,
                goal=goal,
                source_node_name=current_node_spec.name if current_node_spec else current_node_id,
                target_node_name=target_node_spec.name if target_node_spec else edge.target,
            ):
                # Validate and clean output before mapping inputs
                if self.cleansing_config.enabled and target_node_spec:
                    output_to_validate = result.output

                    validation = self.output_cleaner.validate_output(
                        output=output_to_validate,
                        source_node_id=current_node_id,
                        target_node_spec=target_node_spec,
                    )

                    if not validation.valid:
                        self.logger.warning(f"⚠ Output validation failed: {validation.errors}")

                        # Clean the output
                        cleaned_output = self.output_cleaner.clean_output(
                            output=output_to_validate,
                            source_node_id=current_node_id,
                            target_node_spec=target_node_spec,
                            validation_errors=validation.errors,
                        )

                        # Update result with cleaned output
                        result.output = cleaned_output

                        # Write cleaned output back to memory (skip validation for LLM output)
                        for key, value in cleaned_output.items():
                            memory.write(key, value, validate=False)

                        # Revalidate
                        revalidation = self.output_cleaner.validate_output(
                            output=cleaned_output,
                            source_node_id=current_node_id,
                            target_node_spec=target_node_spec,
                        )

                        if revalidation.valid:
                            self.logger.info("✓ Output cleaned and validated successfully")
                        else:
                            self.logger.error(
                                f"✗ Cleaning failed, errors remain: {revalidation.errors}"
                            )
                            # Continue anyway if fallback_to_raw is True

                # Map inputs (skip validation for processed LLM output)
                mapped = edge.map_inputs(result.output, memory.read_all())
                for key, value in mapped.items():
                    memory.write(key, value, validate=False)

                return edge.target

        return None

    def _get_all_traversable_edges(
        self,
        graph: GraphSpec,
        goal: Goal,
        current_node_id: str,
        current_node_spec: Any,
        result: NodeResult,
        memory: SharedMemory,
    ) -> list[EdgeSpec]:
        """
        Get ALL edges that should be traversed (for fan-out detection).

        Unlike _follow_edges which returns the first match, this returns
        all matching edges to enable parallel execution.
        """
        edges = graph.get_outgoing_edges(current_node_id)
        traversable = []

        for edge in edges:
            target_node_spec = graph.get_node(edge.target)
            if edge.should_traverse(
                source_success=result.success,
                source_output=result.output,
                memory=memory.read_all(),
                llm=self.llm,
                goal=goal,
                source_node_name=current_node_spec.name if current_node_spec else current_node_id,
                target_node_name=target_node_spec.name if target_node_spec else edge.target,
            ):
                traversable.append(edge)

        return traversable

    def _find_convergence_node(
        self,
        graph: GraphSpec,
        parallel_targets: list[str],
    ) -> str | None:
        """
        Find the common target node where parallel branches converge (fan-in).

        Args:
            graph: The graph specification
            parallel_targets: List of node IDs that are running in parallel

        Returns:
            Node ID where all branches converge, or None if no convergence
        """
        # Get all nodes that parallel branches lead to
        next_nodes: dict[str, int] = {}  # node_id -> count of branches leading to it

        for target in parallel_targets:
            outgoing = graph.get_outgoing_edges(target)
            for edge in outgoing:
                next_nodes[edge.target] = next_nodes.get(edge.target, 0) + 1

        # Convergence node is where ALL branches lead
        for node_id, count in next_nodes.items():
            if count == len(parallel_targets):
                return node_id

        # Fallback: return most common target if any
        if next_nodes:
            return max(next_nodes.keys(), key=lambda k: next_nodes[k])

        return None

    async def _execute_parallel_branches(
        self,
        graph: GraphSpec,
        goal: Goal,
        edges: list[EdgeSpec],
        memory: SharedMemory,
        source_result: NodeResult,
        source_node_spec: Any,
        path: list[str],
    ) -> tuple[dict[str, NodeResult], int, int]:
        """
        Execute multiple branches in parallel using asyncio.gather.

        Args:
            graph: The graph specification
            goal: The execution goal
            edges: List of edges to follow in parallel
            memory: Shared memory instance
            source_result: Result from the source node
            source_node_spec: Spec of the source node
            path: Execution path list to update

        Returns:
            Tuple of (branch_results dict, total_tokens, total_latency)
        """
        branches: dict[str, ParallelBranch] = {}

        # Create branches for each edge
        for edge in edges:
            branch_id = f"{edge.source}_to_{edge.target}"
            branches[branch_id] = ParallelBranch(
                branch_id=branch_id,
                node_id=edge.target,
                edge=edge,
            )

        self.logger.info(f"   ⑂ Fan-out: executing {len(branches)} branches in parallel")
        for branch in branches.values():
            target_spec = graph.get_node(branch.node_id)
            self.logger.info(f"      • {target_spec.name if target_spec else branch.node_id}")

        async def execute_single_branch(
            branch: ParallelBranch,
        ) -> tuple[ParallelBranch, NodeResult | Exception]:
            """Execute a single branch with retry logic."""
            node_spec = graph.get_node(branch.node_id)
            if node_spec is None:
                branch.status = "failed"
                branch.error = f"Node {branch.node_id} not found in graph"
                return branch, RuntimeError(branch.error)
            branch.status = "running"

            try:
                # Validate and clean output before mapping inputs (same as _follow_edges)
                if self.cleansing_config.enabled and node_spec:
                    validation = self.output_cleaner.validate_output(
                        output=source_result.output,
                        source_node_id=source_node_spec.id if source_node_spec else "unknown",
                        target_node_spec=node_spec,
                    )

                    if not validation.valid:
                        self.logger.warning(
                            f"⚠ Output validation failed for branch "
                            f"{branch.node_id}: {validation.errors}"
                        )
                        cleaned_output = self.output_cleaner.clean_output(
                            output=source_result.output,
                            source_node_id=source_node_spec.id if source_node_spec else "unknown",
                            target_node_spec=node_spec,
                            validation_errors=validation.errors,
                        )
                        # Write cleaned output to memory
                        for key, value in cleaned_output.items():
                            await memory.write_async(key, value)

                # Map inputs via edge
                mapped = branch.edge.map_inputs(source_result.output, memory.read_all())
                for key, value in mapped.items():
                    await memory.write_async(key, value)

                # Execute with retries
                last_result = None
                for attempt in range(node_spec.max_retries):
                    branch.retry_count = attempt

                    # Build context for this branch
                    ctx = self._build_context(node_spec, memory, goal, mapped, graph.max_tokens)
                    node_impl = self._get_node_implementation(node_spec, graph.cleanup_llm_model)

                    self.logger.info(
                        f"      ▶ Branch {node_spec.name}: executing (attempt {attempt + 1})"
                    )
                    result = await node_impl.execute(ctx)
                    last_result = result

                    if result.success:
                        # Write outputs to shared memory using async write
                        for key, value in result.output.items():
                            await memory.write_async(key, value)

                        branch.result = result
                        branch.status = "completed"
                        self.logger.info(
                            f"      ✓ Branch {node_spec.name}: success "
                            f"(tokens: {result.tokens_used}, latency: {result.latency_ms}ms)"
                        )
                        return branch, result

                    self.logger.warning(
                        f"      ↻ Branch {node_spec.name}: "
                        f"retry {attempt + 1}/{node_spec.max_retries}"
                    )

                # All retries exhausted
                branch.status = "failed"
                branch.error = last_result.error if last_result else "Unknown error"
                branch.result = last_result
                self.logger.error(
                    f"      ✗ Branch {node_spec.name}: "
                    f"failed after {node_spec.max_retries} attempts"
                )
                return branch, last_result

            except Exception as e:
                branch.status = "failed"
                branch.error = str(e)
                self.logger.error(f"      ✗ Branch {branch.node_id}: exception - {e}")
                return branch, e

        # Execute all branches concurrently
        tasks = [execute_single_branch(b) for b in branches.values()]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # Process results
        total_tokens = 0
        total_latency = 0
        branch_results: dict[str, NodeResult] = {}
        failed_branches: list[ParallelBranch] = []

        for branch, result in results:
            path.append(branch.node_id)

            if isinstance(result, Exception):
                failed_branches.append(branch)
            elif result is None or not result.success:
                failed_branches.append(branch)
            else:
                total_tokens += result.tokens_used
                total_latency += result.latency_ms
                branch_results[branch.branch_id] = result

        # Handle failures based on config
        if failed_branches:
            failed_names = [graph.get_node(b.node_id).name for b in failed_branches]
            if self._parallel_config.on_branch_failure == "fail_all":
                raise RuntimeError(f"Parallel execution failed: branches {failed_names} failed")
            elif self._parallel_config.on_branch_failure == "continue_others":
                self.logger.warning(
                    f"⚠ Some branches failed ({failed_names}), continuing with successful ones"
                )

        self.logger.info(
            f"   ⑃ Fan-out complete: {len(branch_results)}/{len(branches)} branches succeeded"
        )
        return branch_results, total_tokens, total_latency

    def register_node(self, node_id: str, implementation: NodeProtocol) -> None:
        """Register a custom node implementation."""
        self.node_registry[node_id] = implementation

    def register_function(self, node_id: str, func: Callable) -> None:
        """Register a function as a node."""
        self.node_registry[node_id] = FunctionNode(func)
