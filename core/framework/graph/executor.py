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
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
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

    # Execution quality metrics
    total_retries: int = 0  # Total number of retries across all nodes
    nodes_with_failures: list[str] = field(default_factory=list)  # Failed but recovered
    retry_details: dict[str, int] = field(default_factory=dict)  # {node_id: retry_count}
    had_partial_failures: bool = False  # True if any node failed but eventually succeeded
    execution_quality: str = "clean"  # "clean", "degraded", or "failed"

    # Visit tracking (for feedback/callback edges)
    node_visit_counts: dict[str, int] = field(default_factory=dict)  # {node_id: visit_count}

    @property
    def is_clean_success(self) -> bool:
        """True only if execution succeeded with no retries or failures."""
        return self.success and self.execution_quality == "clean"

    @property
    def is_degraded_success(self) -> bool:
        """True if execution succeeded but had retries or partial failures."""
        return self.success and self.execution_quality == "degraded"


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
        event_bus: Any | None = None,
        stream_id: str = "",
        storage_path: str | Path | None = None,
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
            event_bus: Optional event bus for emitting node lifecycle events
            stream_id: Stream ID for event correlation
            storage_path: Optional base path for conversation persistence
        """
        self.runtime = runtime
        self.llm = llm
        self.tools = tools or []
        self.tool_executor = tool_executor
        self.node_registry = node_registry or {}
        self.approval_callback = approval_callback
        self.validator = OutputValidator()
        self.logger = logging.getLogger(__name__)
        self._event_bus = event_bus
        self._stream_id = stream_id
        self._storage_path = Path(storage_path) if storage_path else None

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
        node_visit_counts: dict[str, int] = {}  # Track visits for feedback loops
        _is_retry = False  # True when looping back for a retry (not a new visit)

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

        # Persistence Sentinel Initialization
        from core.runtime.crash_safe_state import enable_crash_safe_state
        persist = enable_crash_safe_state(self.runtime)

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

                # Enforce max_node_visits (feedback/callback edge support)
                if not _is_retry:
                    cnt = node_visit_counts.get(current_node_id, 0) + 1
                    node_visit_counts[current_node_id] = cnt
                _is_retry = False
                max_visits = getattr(node_spec, "max_node_visits", 1)
                if max_visits > 0 and node_visit_counts[current_node_id] > max_visits:
                    self.logger.warning(
                        f"   ⊘ Node '{node_spec.name}' visit limit reached "
                        f"({node_visit_counts[current_node_id]}/{max_visits}), skipping"
                    )
                    # Skip execution — follow outgoing edges using current memory
                    skip_result = NodeResult(success=True, output=memory.read_all())
                    next_node = self._follow_edges(
                        graph=graph,
                        goal=goal,
                        current_node_id=current_node_id,
                        current_node_spec=node_spec,
                        result=skip_result,
                        memory=memory,
                    )
                    if next_node is None:
                        self.logger.info("   → No more edges after visit limit, ending")
                        break
                    current_node_id = next_node
                    continue

                path.append(current_node_id)

                # Check if pause (HITL) before execution
                if current_node_id in graph.pause_nodes:
                    self.logger.info(f"⏸ Paused at HITL node: {node_spec.name}")

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
                            value_str = str(value)
                            if len(value_str) > 200:
                                value_str = value_str[:200] + "..."
                            self.logger.info(f"      {key}: {value_str}")

                # Get implementation
                node_impl = self._get_node_implementation(node_spec, graph.cleanup_llm_model)

                # Validate inputs
                validation_errors = node_impl.validate_input(ctx)
                if validation_errors:
                    self.logger.warning(f"⚠ Validation warnings: {validation_errors}")
                    self.runtime.report_problem(
                        severity="warning",
                        description=f"Validation errors for {current_node_id}: {validation_errors}",
                    )

                # Emit node-started event
                if self._event_bus and node_spec.node_type != "event_loop":
                    await self._event_bus.emit_node_loop_started(
                        stream_id=self._stream_id, node_id=current_node_id
                    )

                # Execute node
                self.logger.info("   Executing...")
                result = await node_impl.execute(ctx)

                # Emit node-completed event
                if self._event_bus and node_spec.node_type != "event_loop":
                    await self._event_bus.emit_node_loop_completed(
                        stream_id=self._stream_id, node_id=current_node_id, iterations=1
                    )

                if result.success:
                    if (
                        result.output
                        and node_spec.output_keys
                        and node_spec.node_type != "event_loop"
                    ):
                        validation = self.validator.validate_all(
                            output=result.output,
                            expected_keys=node_spec.output_keys,
                            check_hallucination=True,
                            nullable_keys=node_spec.nullable_output_keys,
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
                    summary = result.to_summary(node_spec)
                    self.logger.info(f"   📝 Summary: {summary}")

                    if result.output:
                        self.logger.info("   Written to memory:")
                        for key, value in result.output.items():
                            value_str = str(value)
                            if len(value_str) > 200:
                                value_str = value_str[:200] + "..."
                            self.logger.info(f"      {key}: {value_str}")
                    
                    # Atomic Checkpoint after successful execution and memory write
                    persist()
                else:
                    self.logger.error(f"   ✗ Failed: {result.error}")

                total_tokens += result.tokens_used
                total_latency += result.latency_ms

                # Handle failure
                if not result.success:
                    node_retry_counts[current_node_id] = (
                        node_retry_counts.get(current_node_id, 0) + 1
                    )
                    max_retries = getattr(node_spec, "max_retries", 3)

                    if node_spec.node_type == "event_loop" and max_retries > 0:
                        self.logger.warning(
                            f"EventLoopNode '{node_spec.id}' has max_retries={max_retries}. "
                            "Overriding to 0 — event loop nodes handle retry internally via judge."
                        )
                        max_retries = 0

                    if node_retry_counts[current_node_id] < max_retries:
                        steps -= 1
                        retry_count = node_retry_counts[current_node_id]
                        delay = 1.0 * (2 ** (retry_count - 1))
                        self.logger.info(f"   Using backoff: Sleeping {delay}s before retry...")
                        await asyncio.sleep(delay)
                        self.logger.info(
                            f"   ↻ Retrying ({node_retry_counts[current_node_id]}/{max_retries})..."
                        )
                        _is_retry = True
                        continue
                    else:
                        self.logger.error(
                            f"   ✗ Max retries ({max_retries}) exceeded for node {current_node_id}"
                        )
                        next_node = self._follow_edges(
                            graph=graph,
                            goal=goal,
                            current_node_id=current_node_id,
                            current_node_spec=node_spec,
                            result=result,
                            memory=memory,
                        )

                        if next_node:
                            self.logger.info(f"   → Routing to failure handler: {next_node}")
                            current_node_id = next_node
                            continue
                        else:
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

                            total_retries_count = sum(node_retry_counts.values())
                            nodes_failed = list(node_retry_counts.keys())

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
                                total_retries=total_retries_count,
                                nodes_with_failures=nodes_failed,
                                retry_details=dict(node_retry_counts),
                                had_partial_failures=len(nodes_failed) > 0,
                                execution_quality="failed",
                                node_visit_counts=dict(node_visit_counts),
                            )

                # Check HITL pause
                if node_spec.id in graph.pause_nodes:
                    self.logger.info("💾 Saving session state after pause node")
                    saved_memory = memory.read_all()
                    session_state_out = {
                        "paused_at": node_spec.id,
                        "resume_from": f"{node_spec.id}_resume",
                        "memory": saved_memory,
                        "next_node": None,
                    }

                    self.runtime.end_run(
                        success=True,
                        output_data=saved_memory,
                        narrative=f"Paused at {node_spec.name} after {steps} steps",
                    )

                    total_retries_count = sum(node_retry_counts.values())
                    nodes_failed = [nid for nid, count in node_retry_counts.items() if count > 0]
                    exec_quality = "degraded" if total_retries_count > 0 else "clean"

                    return ExecutionResult(
                        success=True,
                        output=saved_memory,
                        steps_executed=steps,
                        total_tokens=total_tokens,
                        total_latency_ms=total_latency,
                        path=path,
                        paused_at=node_spec.id,
                        session_state=session_state_out,
                        total_retries=total_retries_count,
                        nodes_with_failures=nodes_failed,
                        retry_details=dict(node_retry_counts),
                        had_partial_failures=len(nodes_failed) > 0,
                        execution_quality=exec_quality,
                        node_visit_counts=dict(node_visit_counts),
                    )

                # Check Terminal node
                if node_spec.id in graph.terminal_nodes:
                    self.logger.info(f"✓ Reached terminal node: {node_spec.name}")
                    break

                # Determine next node
                if result.next_node:
                    self.logger.info(f"   → Router directing to: {result.next_node}")
                    current_node_id = result.next_node
                else:
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
                        break

                    if self.enable_parallel_execution and len(traversable_edges) > 1:
                        targets = [e.target for e in traversable_edges]
                        fan_in_node = self._find_convergence_node(graph, targets)

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

                        if fan_in_node:
                            self.logger.info(f"   ⑃ Fan-in: converging at {fan_in_node}")
                            current_node_id = fan_in_node
                        else:
                            self.logger.info("   → Parallel branches completed (no convergence)")
                            break
                    else:
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

                input_data = result.output

            output = memory.read_all()

            self.logger.info("\n✓ Execution complete!")
            self.logger.info(f"   Steps: {steps}")
            self.logger.info(f"   Path: {' → '.join(path)}")
            self.logger.info(f"   Total tokens: {total_tokens}")
            self.logger.info(f"   Total latency: {total_latency}ms")

            total_retries_count = sum(node_retry_counts.values())
            nodes_failed = [nid for nid, count in node_retry_counts.items() if count > 0]
            exec_quality = "degraded" if total_retries_count > 0 else "clean"

            quality_suffix = ""
            if exec_quality == "degraded":
                quality_suffix = f" ({total_retries_count} retries across {len(nodes_failed)} nodes)"

            self.runtime.end_run(
                success=True,
                output_data=output,
                narrative=(
                    f"Executed {steps} steps through path: {' -> '.join(path)}{quality_suffix}"
                ),
            )

            return ExecutionResult(
                success=True,
                output=output,
                steps_executed=steps,
                total_tokens=total_tokens,
                total_latency_ms=total_latency,
                path=path,
                total_retries=total_retries_count,
                nodes_with_failures=nodes_failed,
                retry_details=dict(node_retry_counts),
                had_partial_failures=len(nodes_failed) > 0,
                execution_quality=exec_quality,
                node_visit_counts=dict(node_visit_counts),
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

            total_retries_count = sum(node_retry_counts.values())
            nodes_failed = list(node_retry_counts.keys())

            return ExecutionResult(
                success=False,
                error=str(e),
                steps_executed=steps,
                path=path,
                total_retries=total_retries_count,
                nodes_with_failures=nodes_failed,
                retry_details=dict(node_retry_counts),
                had_partial_failures=len(nodes_failed) > 0,
                execution_quality="failed",
                node_visit_counts=dict(node_visit_counts),
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
        available_tools = []
        if node_spec.tools:
            available_tools = [t for t in self.tools if t.name in node_spec.tools]

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
            goal=goal,
            max_tokens=max_tokens,
        )

    VALID_NODE_TYPES = {
        "llm_tool_use",
        "llm_generate",
        "router",
        "function",
        "human_input",
        "event_loop",
    }
    DEPRECATED_NODE_TYPES = {"llm_tool_use": "event_loop", "llm_generate": "event_loop"}

    def _get_node_implementation(
        self, node_spec: NodeSpec, cleanup_llm_model: str | None = None
    ) -> NodeProtocol:
        """Get or create a node implementation."""
        if node_spec.id in self.node_registry:
            return self.node_registry[node_spec.id]

        if node_spec.node_type not in self.VALID_NODE_TYPES:
            raise RuntimeError(
                f"Invalid node type '{node_spec.node_type}' for node '{node_spec.id}'."
            )

        if node_spec.node_type == "llm_tool_use":
            return LLMNode(tool_executor=self.tool_executor, require_tools=True, cleanup_llm_model=cleanup_llm_model)

        if node_spec.node_type == "llm_generate":
            return LLMNode(tool_executor=None, require_tools=False, cleanup_llm_model=cleanup_llm_model)

        if node_spec.node_type == "router":
            return RouterNode()

        if node_spec.node_type == "event_loop":
            from framework.graph.event_loop_node import EventLoopNode, LoopConfig
            conv_store = None
            if self._storage_path:
                from framework.storage.conversation_store import FileConversationStore
                conv_store = FileConversationStore(base_path=self._storage_path / "conversations" / node_spec.id)
            node = EventLoopNode(
                event_bus=self._event_bus,
                judge=None,
                config=LoopConfig(max_iterations=100, max_tool_result_chars=3_000, spillover_dir=str(self._storage_path / "data") if self._storage_path else None),
                tool_executor=self.tool_executor,
                conversation_store=conv_store,
            )
            self.node_registry[node_spec.id] = node
            return node

        if node_spec.node_type == "human_input":
            return LLMNode(tool_executor=None, require_tools=False, cleanup_llm_model=cleanup_llm_model)

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
                if self.cleansing_config.enabled and target_node_spec:
                    output_to_validate = memory.read_all()
                    validation = self.output_cleaner.validate_output(output_to_validate, current_node_id, target_node_spec)
                    if not validation.valid:
                        cleaned = self.output_cleaner.clean_output(output_to_validate, current_node_id, target_node_spec, validation.errors)
                        result.output = cleaned
                        for key, value in cleaned.items():
                            memory.write(key, value, validate=False)
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
        """Get ALL edges that should be traversed."""
        edges = graph.get_outgoing_edges(current_node_id)
        traversable = [e for e in edges if e.should_traverse(result.success, result.output, memory.read_all(), self.llm, goal, current_node_spec.name if current_node_spec else current_node_id, graph.get_node(e.target).name if graph.get_node(e.target) else e.target)]
        if len(traversable) > 1:
            conditionals = [e for e in traversable if e.condition == EdgeCondition.CONDITIONAL]
            if len(conditionals) > 1:
                max_prio = max(e.priority for e in conditionals)
                traversable = [e for e in traversable if e.condition != EdgeCondition.CONDITIONAL or e.priority == max_prio]
        return traversable

    def _find_convergence_node(self, graph, parallel_targets) -> str | None:
        next_nodes: dict[str, int] = {}
        for target in parallel_targets:
            for edge in graph.get_outgoing_edges(target):
                next_nodes[edge.target] = next_nodes.get(edge.target, 0) + 1
        for node_id, count in next_nodes.items():
            if count == len(parallel_targets): return node_id
        return max(next_nodes.keys(), key=lambda k: next_nodes[k]) if next_nodes else None

    async def _execute_parallel_branches(
        self, graph, goal, edges, memory, source_result, source_node_spec, path
    ) -> tuple[dict[str, NodeResult], int, int]:
        async def execute_single_branch(edge):
            node_spec = graph.get_node(edge.target)
            mapped = edge.map_inputs(source_result.output, memory.read_all())
            for key, value in mapped.items(): await memory.write_async(key, value)
            ctx = self._build_context(node_spec, memory, goal, mapped, graph.max_tokens)
            node_impl = self._get_node_implementation(node_spec, graph.cleanup_llm_model)
            if self._event_bus: await self._event_bus.emit_node_loop_started(stream_id=self._stream_id, node_id=edge.target)
            res = await node_impl.execute(ctx)
            if res.success:
                for key, value in res.output.items(): await memory.write_async(key, value)
            return edge.target, res
        tasks = [execute_single_branch(e) for e in edges]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        total_t = total_l = 0
        for nid, res in results:
            path.append(nid)
            total_t += res.tokens_used
            total_l += res.latency_ms
        return {}, total_t, total_l

    def register_node(self, node_id, implementation): self.node_registry[node_id] = implementation
    def register_function(self, node_id, func): self.node_registry[node_id] = FunctionNode(func)