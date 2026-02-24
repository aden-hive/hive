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
from pathlib import Path
from typing import Any

from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import (
    NodeContext,
    NodeProtocol,
    NodeResult,
    NodeSpec,
    SharedMemory,
)
from framework.graph.output_cleaner import CleansingConfig, OutputCleaner
from framework.graph.validator import OutputValidator
from framework.llm.provider import LLMProvider, Tool
from framework.observability import set_trace_context
from framework.runtime.core import Runtime
from framework.schemas.checkpoint import Checkpoint
from framework.storage.checkpoint_store import CheckpointStore


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
        runtime_logger: Any = None,
        storage_path: str | Path | None = None,
        loop_config: dict[str, Any] | None = None,
        accounts_prompt: str = "",
        accounts_data: list[dict] | None = None,
        tool_provider_map: dict[str, str] | None = None,
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
            runtime_logger: Optional RuntimeLogger for per-graph-run logging
            storage_path: Optional base path for conversation persistence
            loop_config: Optional EventLoopNode configuration (max_iterations, etc.)
            accounts_prompt: Connected accounts block for system prompt injection
            accounts_data: Raw account data for per-node prompt generation
            tool_provider_map: Tool name to provider name mapping for account routing
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
        self.runtime_logger = runtime_logger
        self._storage_path = Path(storage_path) if storage_path else None
        self._loop_config = loop_config or {}
        self.accounts_prompt = accounts_prompt
        self.accounts_data = accounts_data
        self.tool_provider_map = tool_provider_map

        # Initialize output cleaner
        self.cleansing_config = cleansing_config or CleansingConfig()
        self.output_cleaner = OutputCleaner(
            config=self.cleansing_config,
            llm_provider=llm,
        )

        # Parallel execution settings
        self.enable_parallel_execution = enable_parallel_execution
        self._parallel_config = parallel_config or ParallelExecutionConfig()

        # Pause/resume control
        self._pause_requested = asyncio.Event()

    def _write_progress(
        self,
        current_node: str,
        path: list[str],
        memory: Any,
        node_visit_counts: dict[str, int],
    ) -> None:
        """Update state.json with live progress at node transitions.

        Reads the existing state.json (written by ExecutionStream at session
        start) and patches the progress fields in-place.  This keeps
        state.json as the single source of truth — readers always see
        current progress, not stale initial values.

        The write is synchronous and best-effort: never blocks execution.
        """
        if not self._storage_path:
            return
        try:
            import json as _json
            from datetime import datetime

            state_path = self._storage_path / "state.json"
            if state_path.exists():
                state_data = _json.loads(state_path.read_text(encoding="utf-8"))
            else:
                state_data = {}

            # Patch progress fields
            progress = state_data.setdefault("progress", {})
            progress["current_node"] = current_node
            progress["path"] = list(path)
            progress["node_visit_counts"] = dict(node_visit_counts)
            progress["steps_executed"] = len(path)

            # Update timestamp
            timestamps = state_data.setdefault("timestamps", {})
            timestamps["updated_at"] = datetime.now().isoformat()

            # Persist full memory so state.json is sufficient for resume
            # even if the process dies before the final write.
            memory_snapshot = memory.read_all()
            state_data["memory"] = memory_snapshot
            state_data["memory_keys"] = list(memory_snapshot.keys())

            state_path.write_text(_json.dumps(state_data, indent=2), encoding="utf-8")
        except Exception:
            pass  # Best-effort — never block execution

    def _validate_tools(self, graph: GraphSpec) -> list[str]:
        """
        Validate that all tools declared by reachable nodes are available.

        Only checks nodes reachable from graph.entry_node via edges.
        Nodes belonging to other entry points (e.g. the coder node when
        entering via ticket_triage) are skipped — they will be validated
        when their own entry point triggers execution.

        Returns:
            List of error messages (empty if all tools are available)
        """
        errors = []
        available_tool_names = {t.name for t in self.tools}

        # Compute reachable nodes from the execution's entry node
        reachable: set[str] = set()
        to_visit = [graph.entry_node]
        while to_visit:
            nid = to_visit.pop()
            if nid in reachable:
                continue
            reachable.add(nid)
            for edge in graph.get_outgoing_edges(nid):
                to_visit.append(edge.target)

        for node in graph.nodes:
            if node.id not in reachable:
                continue
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
        checkpoint_config: "CheckpointConfig | None" = None,
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
        # Add agent_id to trace context for correlation
        set_trace_context(agent_id=graph.id)

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

        # Continuous conversation mode state
        is_continuous = getattr(graph, "conversation_mode", "isolated") == "continuous"
        continuous_conversation = None  # NodeConversation threaded across nodes
        cumulative_tools: list = []  # Tools accumulate, never removed
        cumulative_tool_names: set[str] = set()
        cumulative_output_keys: list[str] = []  # Output keys from all visited nodes

        # Initialize checkpoint store if checkpointing is enabled
        checkpoint_store: CheckpointStore | None = None
        if checkpoint_config and checkpoint_config.enabled and self._storage_path:
            checkpoint_store = CheckpointStore(self._storage_path)
            self.logger.info("✓ Checkpointing enabled")

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
                # Restore memory from previous session.
                # Skip validation — this data was already validated when
                # originally written, and research text triggers false
                # positives on the code-indicator heuristic.
                for key, value in memory_data.items():
                    memory.write(key, value, validate=False)
                self.logger.info(f"📥 Restored session state with {len(memory_data)} memory keys")

        # Write new input data to memory (each key individually).
        # Skip when resuming from a paused session — restored memory already
        # contains all state including the original input, and re-writing
        # input_data would overwrite intermediate results with stale values.
        _is_resuming = bool(session_state and session_state.get("paused_at"))
        if input_data and not _is_resuming:
            for key, value in input_data.items():
                memory.write(key, value)

        # Detect event-triggered execution (timer/webhook) — no interactive user.
        _event_triggered = bool(input_data and isinstance(input_data.get("event"), dict))

        path: list[str] = []
        total_tokens = 0
        total_latency = 0
        node_retry_counts: dict[str, int] = {}  # Track retries per node
        node_visit_counts: dict[str, int] = {}  # Track visits for feedback loops
        _is_retry = False  # True when looping back for a retry (not a new visit)

        # Restore node_visit_counts from session state if available
        if session_state and "node_visit_counts" in session_state:
            node_visit_counts = dict(session_state["node_visit_counts"])
            if node_visit_counts:
                self.logger.info(f"📥 Restored node visit counts: {node_visit_counts}")

                # If resuming at a specific node (paused_at), that node was counted
                # but never completed, so decrement its count
                paused_at = session_state.get("paused_at")
                if (
                    paused_at
                    and paused_at in node_visit_counts
                    and node_visit_counts[paused_at] > 0
                ):
                    old_count = node_visit_counts[paused_at]
                    node_visit_counts[paused_at] -= 1
                    self.logger.info(
                        f"📥 Decremented visit count for paused node '{paused_at}': "
                        f"{old_count} -> {node_visit_counts[paused_at]}"
                    )

        # Determine entry point (may differ if resuming)
        # Check if resuming from checkpoint
        if session_state and session_state.get("resume_from_checkpoint") and checkpoint_store:
            checkpoint_id = session_state["resume_from_checkpoint"]
            try:
                checkpoint = await checkpoint_store.load_checkpoint(checkpoint_id)

                if checkpoint:
                    self.logger.info(
                        f"🔄 Resuming from checkpoint: {checkpoint_id} "
                        f"(node: {checkpoint.current_node})"
                    )

                    # Restore memory from checkpoint
                    for key, value in checkpoint.shared_memory.items():
                        memory.write(key, value, validate=False)

                    # Start from checkpoint's next node or current node
                    current_node_id = (
                        checkpoint.next_node or checkpoint.current_node or graph.entry_node
                    )

                    # Restore execution path
                    path.extend(checkpoint.execution_path)

                    self.logger.info(
                        f"📥 Restored memory with {len(checkpoint.shared_memory)} keys, "
                        f"resuming at node: {current_node_id}"
                    )
                else:
                    self.logger.warning(
                        f"Checkpoint {checkpoint_id} not found, resuming from normal entry point"
                    )
                    # Check if resuming from paused_at (fallback to session state)
                    paused_at = session_state.get("paused_at") if session_state else None
                    if paused_at and graph.get_node(paused_at) is not None:
                        current_node_id = paused_at
                        self.logger.info(f"🔄 Resuming from paused node: {paused_at}")
                    else:
                        current_node_id = graph.get_entry_point(session_state)

            except Exception as e:
                self.logger.error(
                    f"Failed to load checkpoint {checkpoint_id}: {e}, "
                    f"resuming from normal entry point"
                )
                # Check if resuming from paused_at (fallback to session state)
                paused_at = session_state.get("paused_at") if session_state else None
                if paused_at and graph.get_node(paused_at) is not None:
                    current_node_id = paused_at
                    self.logger.info(f"🔄 Resuming from paused node: {paused_at}")
                else:
                    current_node_id = graph.get_entry_point(session_state)
        else:
            # Check if resuming from paused_at (session state resume)
            paused_at = session_state.get("paused_at") if session_state else None
            node_ids = [n.id for n in graph.nodes]
            self.logger.debug(f"paused_at={paused_at}, available node IDs={node_ids}")

            if paused_at and graph.get_node(paused_at) is not None:
                # Resume from paused_at node directly (works for any node, not just pause_nodes)
                current_node_id = paused_at

                # Restore execution path from session state if available
                if session_state:
                    execution_path = session_state.get("execution_path", [])
                    if execution_path:
                        path.extend(execution_path)
                        self.logger.info(
                            f"🔄 Resuming from paused node: {paused_at} "
                            f"(restored path: {execution_path})"
                        )
                    else:
                        self.logger.info(f"🔄 Resuming from paused node: {paused_at}")
                else:
                    self.logger.info(f"🔄 Resuming from paused node: {paused_at}")
            else:
                # Fall back to normal entry point logic
                self.logger.warning(
                    f"⚠ paused_at={paused_at} is not a valid node, falling back to entry point"
                )
                current_node_id = graph.get_entry_point(session_state)

        steps = 0

        # Fresh shared-session execution: clear stale cursor so the entry
        # node doesn't restore a filled OutputAccumulator from the previous
        # webhook run (which would cause the judge to accept immediately).
        # The conversation history is preserved (continuous memory).
        _is_fresh_shared = bool(
            session_state
            and session_state.get("resume_session_id")
            and not session_state.get("paused_at")
            and not session_state.get("resume_from_checkpoint")
        )
        if _is_fresh_shared and is_continuous and self._storage_path:
            try:
                from framework.storage.conversation_store import FileConversationStore

                entry_conv_path = self._storage_path / "conversations"
                if entry_conv_path.exists():
                    _store = FileConversationStore(base_path=entry_conv_path)

                    # Read cursor to find next seq for the transition marker.
                    _cursor = await _store.read_cursor() or {}
                    _next_seq = _cursor.get("next_seq", 0)
                    if _next_seq == 0:
                        # Fallback: scan part files for max seq
                        _parts = await _store.read_parts()
                        if _parts:
                            _next_seq = max(p.get("seq", 0) for p in _parts) + 1

                    # Reset cursor — clears stale accumulator outputs and
                    # iteration counter so the node starts fresh work while
                    # the conversation thread carries forward.
                    await _store.write_cursor({})

                    # Append a transition marker so the LLM knows a new
                    # event arrived and previous results are outdated.
                    await _store.write_part(
                        _next_seq,
                        {
                            "role": "user",
                            "content": (
                                "--- NEW EVENT TRIGGER ---\n"
                                "A new event has been received. "
                                "Process this as a fresh request — "
                                "previous outputs are no longer valid."
                            ),
                            "seq": _next_seq,
                            "is_transition_marker": True,
                        },
                    )
                    self.logger.info(
                        "🔄 Cleared stale cursor and added transition marker "
                        "for shared-session entry node '%s'",
                        current_node_id,
                    )
            except Exception:
                self.logger.debug(
                    "Could not prepare conversation store for shared-session entry node '%s'",
                    current_node_id,
                    exc_info=True,
                )

        if session_state and current_node_id != graph.entry_node:
            self.logger.info(f"🔄 Resuming from: {current_node_id}")

            # Emit resume event
            if self._event_bus:
                await self._event_bus.emit_execution_resumed(
                    stream_id=self._stream_id,
                    node_id=current_node_id,
                )

        # Start run
        _run_id = self.runtime.start_run(
            goal_id=goal.id,
            goal_description=goal.description,
            input_data=input_data or {},
        )

        if self.runtime_logger:
            # Extract session_id from storage_path if available (for unified sessions)
            session_id = ""
            if self._storage_path and self._storage_path.name.startswith("session_"):
                session_id = self._storage_path.name
            self.runtime_logger.start_run(goal_id=goal.id, session_id=session_id)

        self.logger.info(f"🚀 Starting execution: {goal.name}")
        self.logger.info(f"   Goal: {goal.description}")
        self.logger.info(f"   Entry node: {graph.entry_node}")

        # Set per-execution data_dir so data tools (save_data, load_data, etc.)
        # and spillover files share the same session-scoped directory.
        _ctx_token = None
        if self._storage_path:
            from framework.runner.tool_registry import ToolRegistry

            _ctx_token = ToolRegistry.set_execution_context(
                data_dir=str(self._storage_path / "data"),
            )

        try:
            while steps < graph.max_steps:
                steps += 1

                # Check for pause request
                if self._pause_requested.is_set():
                    self.logger.info("⏸ Pause detected - stopping at node boundary")

                    # Emit pause event
                    if self._event_bus:
                        await self._event_bus.emit_execution_paused(
                            stream_id=self._stream_id,
                            node_id=current_node_id,
                            reason="User requested pause (Ctrl+Z)",
                        )

                    # Create session state for pause
                    saved_memory = memory.read_all()
                    pause_session_state: dict[str, Any] = {
                        "memory": saved_memory,  # Include memory for resume
                        "execution_path": list(path),
                        "node_visit_counts": dict(node_visit_counts),
                    }

                    # Create a pause checkpoint
                    if checkpoint_store:
                        pause_checkpoint = self._create_checkpoint(
                            checkpoint_type="pause",
                            current_node=current_node_id,
                            execution_path=path,
                            memory=memory,
                            next_node=current_node_id,
                            is_clean=True,
                        )
                        await checkpoint_store.save_checkpoint(pause_checkpoint)
                        pause_session_state["latest_checkpoint_id"] = pause_checkpoint.checkpoint_id
                        pause_session_state["resume_from_checkpoint"] = (
                            pause_checkpoint.checkpoint_id
                        )

                    # Return with paused status
                    return ExecutionResult(
                        success=False,
                        output=saved_memory,
                        path=path,
                        paused_at=current_node_id,
                        error="Execution paused by user request",
                        session_state=pause_session_state,
                        node_visit_counts=dict(node_visit_counts),
                    )

                # Get current node
                node_spec = graph.get_node(current_node_id)
                if node_spec is None:
                    raise RuntimeError(f"Node not found: {current_node_id}")

                # Enforce max_node_visits (feedback/callback edge support)
                # Don't increment visit count on retries — retries are not new visits
                if not _is_retry:
                    cnt = node_visit_counts.get(current_node_id, 0) + 1
                    node_visit_counts[current_node_id] = cnt
                _is_retry = False
                max_visits = getattr(node_spec, "max_node_visits", 0)
                if max_visits > 0 and node_visit_counts[current_node_id] > max_visits:
                    self.logger.warning(
                        f"   ⊘ Node '{node_spec.name}' visit limit reached "
                        f"({node_visit_counts[current_node_id]}/{max_visits}), skipping"
                    )
                    # Skip execution — follow outgoing edges using current memory
                    skip_result = NodeResult(success=True, output=memory.read_all())
                    next_node = await self._follow_edges(
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

                # Clear stale nullable outputs from previous visits.
                # When a node is re-visited (e.g. review → process-batch → review),
                # nullable outputs from the PREVIOUS visit linger in shared memory.
                # This causes stale edge conditions to fire (e.g. "feedback is not None"
                # from visit 1 triggers even when visit 2 sets "final_summary" instead).
                # Clearing them ensures only the CURRENT visit's outputs affect routing.
                if node_visit_counts.get(current_node_id, 0) > 1:
                    nullable_keys = getattr(node_spec, "nullable_output_keys", None) or []
                    for key in nullable_keys:
                        if memory.read(key) is not None:
                            memory.write(key, None, validate=False)
                            self.logger.info(
                                f"   🧹 Cleared stale nullable output '{key}' from previous visit"
                            )

                # Check if pause (HITL) before execution
                if current_node_id in graph.pause_nodes:
                    self.logger.info(f"⏸ Paused at HITL node: {node_spec.name}")
                    # Execute this node, then pause
                    # (We'll check again after execution and save state)

                self.logger.info(f"\n▶ Step {steps}: {node_spec.name} ({node_spec.node_type})")
                self.logger.info(f"   Inputs: {node_spec.input_keys}")
                self.logger.info(f"   Outputs: {node_spec.output_keys}")

                # Continuous mode: accumulate tools and output keys from this node
                if is_continuous and node_spec.tools:
                    for t in self.tools:
                        if t.name in node_spec.tools and t.name not in cumulative_tool_names:
                            cumulative_tools.append(t)
                            cumulative_tool_names.add(t.name)
                if is_continuous and node_spec.output_keys:
                    for k in node_spec.output_keys:
                        if k not in cumulative_output_keys:
                            cumulative_output_keys.append(k)

                # Build context for node
                ctx = self._build_context(
                    node_spec=node_spec,
                    memory=memory,
                    goal=goal,
                    input_data=input_data or {},
                    max_tokens=graph.max_tokens,
                    continuous_mode=is_continuous,
                    inherited_conversation=continuous_conversation if is_continuous else None,
                    override_tools=cumulative_tools if is_continuous else None,
                    cumulative_output_keys=cumulative_output_keys if is_continuous else None,
                    event_triggered=_event_triggered,
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

                # CHECKPOINT: node_start
                if (
                    checkpoint_store
                    and checkpoint_config
                    and checkpoint_config.should_checkpoint_node_start()
                ):
                    checkpoint = self._create_checkpoint(
                        checkpoint_type="node_start",
                        current_node=node_spec.id,
                        execution_path=list(path),
                        memory=memory,
                        is_clean=(sum(node_retry_counts.values()) == 0),
                    )

                    if checkpoint_config.async_checkpoint:
                        # Non-blocking checkpoint save
                        asyncio.create_task(checkpoint_store.save_checkpoint(checkpoint))
                    else:
                        # Blocking checkpoint save
                        await checkpoint_store.save_checkpoint(checkpoint)

                # Emit node-started event (skip event_loop nodes — they emit their own)
                if self._event_bus and node_spec.node_type != "event_loop":
                    await self._event_bus.emit_node_loop_started(
                        stream_id=self._stream_id, node_id=current_node_id
                    )

                # Execute node
                self.logger.info("   Executing...")
                result = await node_impl.execute(ctx)

                # Emit node-completed event (skip event_loop nodes)
                if self._event_bus and node_spec.node_type != "event_loop":
                    await self._event_bus.emit_node_loop_completed(
                        stream_id=self._stream_id, node_id=current_node_id, iterations=1
                    )

                # Ensure runtime logging has an L2 entry for this node
                if self.runtime_logger:
                    self.runtime_logger.ensure_node_logged(
                        node_id=node_spec.id,
                        node_name=node_spec.name,
                        node_type=node_spec.node_type,
                        success=result.success,
                        error=result.error,
                        tokens_used=result.tokens_used,
                        latency_ms=result.latency_ms,
                    )

                if result.success:
                    # Validate output before accepting it.
                    # Skip for event_loop nodes — their judge system is
                    # the sole acceptance mechanism (see WP-8).  Empty
                    # strings and other flexible outputs are legitimate
                    # for LLM-driven nodes that already passed the judge.
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

                    # Write node outputs to memory BEFORE edge evaluation
                    # This enables direct key access in conditional expressions (e.g., "score > 80")
                    # Without this, conditional edges can only use output['key'] syntax
                    if result.output:
                        for key, value in result.output.items():
                            memory.write(key, value, validate=False)
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

                    # EventLoopNode instances handle retry internally via judge —
                    # executor retry would cause catastrophic retry multiplication.
                    # Only override for actual EventLoopNode instances, not custom
                    # NodeProtocol implementations that happen to use node_type="event_loop"
                    from framework.graph.event_loop_node import EventLoopNode

                    if isinstance(node_impl, EventLoopNode) and max_retries > 0:
                        self.logger.warning(
                            f"EventLoopNode '{node_spec.id}' has max_retries={max_retries}. "
                            "Overriding to 0 — event loop nodes handle retry internally via judge."
                        )
                        max_retries = 0

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

                        # Emit retry event
                        if self._event_bus:
                            await self._event_bus.emit_node_retry(
                                stream_id=self._stream_id,
                                node_id=current_node_id,
                                retry_count=retry_count,
                                max_retries=max_retries,
                                error=result.error or "",
                            )

                        _is_retry = True
                        continue
                    else:
                        # Max retries exceeded - check for failure handlers
                        self.logger.error(
                            f"   ✗ Max retries ({max_retries}) exceeded for node {current_node_id}"
                        )

                        # Check if there's an ON_FAILURE edge to follow
                        next_node = await self._follow_edges(
                            graph=graph,
                            goal=goal,
                            current_node_id=current_node_id,
                            current_node_spec=node_spec,
                            result=result,  # result.success=False triggers ON_FAILURE
                            memory=memory,
                        )

                        if next_node:
                            # Found a failure handler - route to it
                            self.logger.info(f"   → Routing to failure handler: {next_node}")
                            current_node_id = next_node
                            continue  # Continue execution with handler
                        else:
                            # No failure handler - terminate execution
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

                            # Calculate quality metrics
                            total_retries_count = sum(node_retry_counts.values())
                            nodes_failed = list(node_retry_counts.keys())

                            if self.runtime_logger:
                                await self.runtime_logger.end_run(
                                    status="failure",
                                    duration_ms=total_latency,
                                    node_path=path,
                                    execution_quality="failed",
                                )

                            # Save memory for potential resume
                            saved_memory = memory.read_all()
                            failure_session_state = {
                                "memory": saved_memory,
                                "execution_path": list(path),
                                "node_visit_counts": dict(node_visit_counts),
                                "resume_from": current_node_id,
                            }

                            return ExecutionResult(
                                success=False,
                                error=(
                                    f"Node '{node_spec.name}' failed after "
                                    f"{max_retries} attempts: {result.error}"
                                ),
                                output=saved_memory,
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
                                session_state=failure_session_state,
                            )

                # Check if we just executed a pause node - if so, save state and return
                # This must happen BEFORE determining next node, since pause nodes may have no edges
                if node_spec.id in graph.pause_nodes:
                    self.logger.info("💾 Saving session state after pause node")

                    # Emit pause event
                    if self._event_bus:
                        await self._event_bus.emit_execution_paused(
                            stream_id=self._stream_id,
                            node_id=node_spec.id,
                            reason="HITL pause node",
                        )

                    saved_memory = memory.read_all()
                    session_state_out = {
                        "paused_at": node_spec.id,
                        "resume_from": f"{node_spec.id}_resume",  # Resume key
                        "memory": saved_memory,
                        "execution_path": list(path),
                        "node_visit_counts": dict(node_visit_counts),
                        "next_node": None,  # Will resume from entry point
                    }

                    self.runtime.end_run(
                        success=True,
                        output_data=saved_memory,
                        narrative=f"Paused at {node_spec.name} after {steps} steps",
                    )

                    # Calculate quality metrics
                    total_retries_count = sum(node_retry_counts.values())
                    nodes_failed = [nid for nid, count in node_retry_counts.items() if count > 0]
                    exec_quality = "degraded" if total_retries_count > 0 else "clean"

                    if self.runtime_logger:
                        await self.runtime_logger.end_run(
                            status="success",
                            duration_ms=total_latency,
                            node_path=path,
                            execution_quality=exec_quality,
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
                        total_retries=total_retries_count,
                        nodes_with_failures=nodes_failed,
                        retry_details=dict(node_retry_counts),
                        had_partial_failures=len(nodes_failed) > 0,
                        execution_quality=exec_quality,
                        node_visit_counts=dict(node_visit_counts),
                    )

                # Check if this is a terminal node - if so, we're done
                if node_spec.id in graph.terminal_nodes:
                    self.logger.info(f"✓ Reached terminal node: {node_spec.name}")
                    break

                # Determine next node
                if result.next_node:
                    # Router explicitly set next node
                    self.logger.info(f"   → Router directing to: {result.next_node}")

                    # Emit edge traversed event for router-directed edge
                    if self._event_bus:
                        await self._event_bus.emit_edge_traversed(
                            stream_id=self._stream_id,
                            source_node=current_node_id,
                            target_node=result.next_node,
                            edge_condition="router",
                        )

                    current_node_id = result.next_node
                    self._write_progress(current_node_id, path, memory, node_visit_counts)
                else:
                    # Get all traversable edges for fan-out detection
                    traversable_edges = await self._get_all_traversable_edges(
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

                        # Emit edge traversed events for fan-out branches
                        if self._event_bus:
                            for edge in traversable_edges:
                                await self._event_bus.emit_edge_traversed(
                                    stream_id=self._stream_id,
                                    source_node=current_node_id,
                                    target_node=edge.target,
                                    edge_condition=edge.condition.value
                                    if hasattr(edge.condition, "value")
                                    else str(edge.condition),
                                )

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
                            self._write_progress(current_node_id, path, memory, node_visit_counts)
                        else:
                            # No convergence point - branches are terminal
                            self.logger.info("   → Parallel branches completed (no convergence)")
                            break
                    else:
                        # Sequential: follow single edge (existing logic via _follow_edges)
                        next_node = await self._follow_edges(
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

                        # Emit edge traversed event for sequential edge
                        if self._event_bus:
                            await self._event_bus.emit_edge_traversed(
                                stream_id=self._stream_id,
                                source_node=current_node_id,
                                target_node=next_node,
                            )

                        # CHECKPOINT: node_complete (after determining next node)
                        if (
                            checkpoint_store
                            and checkpoint_config
                            and checkpoint_config.should_checkpoint_node_complete()
                        ):
                            checkpoint = self._create_checkpoint(
                                checkpoint_type="node_complete",
                                current_node=node_spec.id,
                                execution_path=list(path),
                                memory=memory,
                                next_node=next_node,
                                is_clean=(sum(node_retry_counts.values()) == 0),
                            )

                            if checkpoint_config.async_checkpoint:
                                asyncio.create_task(checkpoint_store.save_checkpoint(checkpoint))
                            else:
                                await checkpoint_store.save_checkpoint(checkpoint)

                        # Periodic checkpoint pruning
                        if (
                            checkpoint_store
                            and checkpoint_config
                            and checkpoint_config.should_prune_checkpoints(len(path))
                        ):
                            asyncio.create_task(
                                checkpoint_store.prune_checkpoints(
                                    max_age_days=checkpoint_config.checkpoint_max_age_days
                                )
                            )

                        current_node_id = next_node

                # Write progress snapshot at node transition
                self._write_progress(current_node_id, path, memory, node_visit_counts)

                # Continuous mode: thread conversation forward with transition marker
                if is_continuous and result.conversation is not None:
                    continuous_conversation = result.conversation

                    # Look up the next node spec for the transition marker
                    next_spec = graph.get_node(current_node_id)
                    if next_spec and next_spec.node_type == "event_loop":
                        from framework.graph.prompt_composer import (
                            build_accounts_prompt,
                            build_narrative,
                            build_transition_marker,
                            compose_system_prompt,
                        )

                        # Build Layer 2 (narrative) from current state
                        narrative = build_narrative(memory, path, graph)

                        # Read agent working memory (adapt.md) once for both
                        # system prompt and transition marker.
                        _adapt_text: str | None = None
                        if self._storage_path:
                            _adapt_path = self._storage_path / "data" / "adapt.md"
                            if _adapt_path.exists():
                                _raw = _adapt_path.read_text(encoding="utf-8").strip()
                                _adapt_text = _raw or None

                        # Merge adapt.md into narrative for system prompt
                        if _adapt_text:
                            narrative = (
                                f"{narrative}\n\n--- Agent Memory ---\n{_adapt_text}"
                                if narrative
                                else _adapt_text
                            )

                        # Build per-node accounts prompt for the next node
                        _node_accounts = self.accounts_prompt or None
                        if self.accounts_data and self.tool_provider_map:
                            _node_accounts = (
                                build_accounts_prompt(
                                    self.accounts_data,
                                    self.tool_provider_map,
                                    node_tool_names=next_spec.tools,
                                )
                                or None
                            )

                        # Compose new system prompt (Layer 1 + 2 + 3 + accounts)
                        new_system = compose_system_prompt(
                            identity_prompt=getattr(graph, "identity_prompt", None),
                            focus_prompt=next_spec.system_prompt,
                            narrative=narrative,
                            accounts_prompt=_node_accounts,
                        )
                        continuous_conversation.update_system_prompt(new_system)

                        # Insert transition marker into conversation
                        data_dir = str(self._storage_path / "data") if self._storage_path else None
                        marker = build_transition_marker(
                            previous_node=node_spec,
                            next_node=next_spec,
                            memory=memory,
                            cumulative_tool_names=sorted(cumulative_tool_names),
                            data_dir=data_dir,
                            adapt_content=_adapt_text,
                        )
                        await continuous_conversation.add_user_message(
                            marker,
                            is_transition_marker=True,
                        )

                        # Set current phase for phase-aware compaction
                        continuous_conversation.set_current_phase(next_spec.id)

                        # Opportunistic compaction at transition:
                        # 1. Prune old tool results (free, no LLM call)
                        # 2. If still over 80%, do a phase-graduated compact
                        if continuous_conversation.usage_ratio() > 0.5:
                            await continuous_conversation.prune_old_tool_results(
                                protect_tokens=2000,
                            )
                        if continuous_conversation.needs_compaction():
                            self.logger.info(
                                "   Phase-boundary compaction (%.0f%% usage)",
                                continuous_conversation.usage_ratio() * 100,
                            )
                            summary = (
                                f"Summary of earlier phases (before {next_spec.name}). "
                                "See transition markers for phase details."
                            )
                            await continuous_conversation.compact(
                                summary,
                                keep_recent=4,
                                phase_graduated=True,
                            )

                # Update input_data for next node
                input_data = result.output

            # Collect output
            output = memory.read_all()

            self.logger.info("\n✓ Execution complete!")
            self.logger.info(f"   Steps: {steps}")
            self.logger.info(f"   Path: {' → '.join(path)}")
            self.logger.info(f"   Total tokens: {total_tokens}")
            self.logger.info(f"   Total latency: {total_latency}ms")

            # Calculate execution quality metrics
            total_retries_count = sum(node_retry_counts.values())
            nodes_failed = [nid for nid, count in node_retry_counts.items() if count > 0]
            exec_quality = "degraded" if total_retries_count > 0 else "clean"

            # Update narrative to reflect execution quality
            quality_suffix = ""
            if exec_quality == "degraded":
                retries = total_retries_count
                failed = len(nodes_failed)
                quality_suffix = f" ({retries} retries across {failed} nodes)"

            self.runtime.end_run(
                success=True,
                output_data=output,
                narrative=(
                    f"Executed {steps} steps through path: {' -> '.join(path)}{quality_suffix}"
                ),
            )

            if self.runtime_logger:
                await self.runtime_logger.end_run(
                    status="success" if exec_quality != "failed" else "failure",
                    duration_ms=total_latency,
                    node_path=path,
                    execution_quality=exec_quality,
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
                session_state={
                    "memory": output,  # output IS memory.read_all()
                    "execution_path": list(path),
                    "node_visit_counts": dict(node_visit_counts),
                },
            )

        except asyncio.CancelledError:
            # Handle cancellation (e.g., TUI quit) - save as paused instead of failed
            self.logger.info("⏸ Execution cancelled - saving state for resume")

            # Flush WIP accumulator outputs from the interrupted node's
            # cursor.json into SharedMemory so they survive resume.  The
            # accumulator writes to cursor.json on every set() call, but
            # only writes to SharedMemory when the judge ACCEPTs.  Without
            # this, edge conditions checking these keys see None on resume.
            if current_node_id and self._storage_path:
                try:
                    import json as _json

                    cursor_path = (
                        self._storage_path / "conversations" / "cursor.json"
                    )
                    if cursor_path.exists():
                        cursor_data = _json.loads(cursor_path.read_text(encoding="utf-8"))
                        wip_outputs = cursor_data.get("outputs", {})
                        for key, value in wip_outputs.items():
                            if value is not None:
                                memory.write(key, value, validate=False)
                        if wip_outputs:
                            self.logger.info(
                                "Flushed %d WIP accumulator outputs to memory: %s",
                                len(wip_outputs),
                                list(wip_outputs.keys()),
                            )
                except Exception:
                    self.logger.debug(
                        "Could not flush accumulator outputs from cursor",
                        exc_info=True,
                    )

            # Save memory and state for resume
            saved_memory = memory.read_all()
            session_state_out: dict[str, Any] = {
                "memory": saved_memory,
                "execution_path": list(path),
                "node_visit_counts": dict(node_visit_counts),
            }

            # Calculate quality metrics
            total_retries_count = sum(node_retry_counts.values())
            nodes_failed = [nid for nid, count in node_retry_counts.items() if count > 0]
            exec_quality = "degraded" if total_retries_count > 0 else "clean"

            if self.runtime_logger:
                await self.runtime_logger.end_run(
                    status="paused",
                    duration_ms=total_latency,
                    node_path=path,
                    execution_quality=exec_quality,
                )

            # Return with paused status
            return ExecutionResult(
                success=False,
                error="Execution paused by user",
                output=saved_memory,
                steps_executed=steps,
                total_tokens=total_tokens,
                total_latency_ms=total_latency,
                path=path,
                paused_at=current_node_id,  # Save where we were
                session_state=session_state_out,
                total_retries=total_retries_count,
                nodes_with_failures=nodes_failed,
                retry_details=dict(node_retry_counts),
                had_partial_failures=len(nodes_failed) > 0,
                execution_quality=exec_quality,
                node_visit_counts=dict(node_visit_counts),
            )

        except Exception as e:
            import traceback

            stack_trace = traceback.format_exc()

            self.runtime.report_problem(
                severity="critical",
                description=str(e),
            )
            self.runtime.end_run(
                success=False,
                narrative=f"Failed at step {steps}: {e}",
            )

            # Log the crashing node to L2 with full stack trace
            if self.runtime_logger and node_spec is not None:
                self.runtime_logger.ensure_node_logged(
                    node_id=node_spec.id,
                    node_name=node_spec.name,
                    node_type=node_spec.node_type,
                    success=False,
                    error=str(e),
                    stacktrace=stack_trace,
                )

            # Calculate quality metrics even for exceptions
            total_retries_count = sum(node_retry_counts.values())
            nodes_failed = list(node_retry_counts.keys())

            if self.runtime_logger:
                await self.runtime_logger.end_run(
                    status="failure",
                    duration_ms=total_latency,
                    node_path=path,
                    execution_quality="failed",
                )

            # Flush WIP accumulator outputs (same as CancelledError path)
            if current_node_id and self._storage_path:
                try:
                    import json as _json

                    cursor_path = (
                        self._storage_path / "conversations" / "cursor.json"
                    )
                    if cursor_path.exists():
                        cursor_data = _json.loads(cursor_path.read_text(encoding="utf-8"))
                        for key, value in cursor_data.get("outputs", {}).items():
                            if value is not None:
                                memory.write(key, value, validate=False)
                except Exception:
                    self.logger.debug(
                        "Could not flush accumulator outputs from cursor",
                        exc_info=True,
                    )

            # Save memory and state for potential resume
            saved_memory = memory.read_all()
            session_state_out: dict[str, Any] = {
                "memory": saved_memory,
                "execution_path": list(path),
                "node_visit_counts": dict(node_visit_counts),
                "resume_from": current_node_id,
            }

            # Mark latest checkpoint for resume on failure
            if checkpoint_store:
                try:
                    checkpoints = await checkpoint_store.list_checkpoints()
                    if checkpoints:
                        # Find latest clean checkpoint
                        index = await checkpoint_store.load_index()
                        if index:
                            latest_clean = index.get_latest_clean_checkpoint()
                            if latest_clean:
                                session_state_out["resume_from_checkpoint"] = (
                                    latest_clean.checkpoint_id
                                )
                                session_state_out["latest_checkpoint_id"] = (
                                    latest_clean.checkpoint_id
                                )
                                self.logger.info(
                                    f"💾 Marked checkpoint for resume: {latest_clean.checkpoint_id}"
                                )
                except Exception as checkpoint_err:
                    self.logger.warning(f"Failed to mark checkpoint for resume: {checkpoint_err}")

            return ExecutionResult(
                success=False,
                error=str(e),
                output=saved_memory,
                steps_executed=steps,
                path=path,
                total_retries=total_retries_count,
                nodes_with_failures=nodes_failed,
                retry_details=dict(node_retry_counts),
                had_partial_failures=len(nodes_failed) > 0,
                execution_quality="failed",
                node_visit_counts=dict(node_visit_counts),
                session_state=session_state_out,
            )

        finally:
            if _ctx_token is not None:
                from framework.runner.tool_registry import ToolRegistry

                ToolRegistry.reset_execution_context(_ctx_token)

    def _build_context(
        self,
        node_spec: NodeSpec,
        memory: SharedMemory,
        goal: Goal,
        input_data: dict[str, Any],
        max_tokens: int = 4096,
        continuous_mode: bool = False,
        inherited_conversation: Any = None,
        override_tools: list | None = None,
        cumulative_output_keys: list[str] | None = None,
        event_triggered: bool = False,
    ) -> NodeContext:
        """Build execution context for a node."""
        # Filter tools to those available to this node
        if override_tools is not None:
            # Continuous mode: use cumulative tool set
            available_tools = list(override_tools)
        else:
            available_tools = []
            if node_spec.tools:
                available_tools = [t for t in self.tools if t.name in node_spec.tools]

        # Create scoped memory view
        scoped_memory = memory.with_permissions(
            read_keys=node_spec.input_keys,
            write_keys=node_spec.output_keys,
        )

        # Build per-node accounts prompt (filtered to this node's tools)
        node_accounts_prompt = self.accounts_prompt
        if self.accounts_data and self.tool_provider_map:
            from framework.graph.prompt_composer import build_accounts_prompt

            node_accounts_prompt = build_accounts_prompt(
                self.accounts_data,
                self.tool_provider_map,
                node_tool_names=node_spec.tools,
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
            runtime_logger=self.runtime_logger,
            pause_event=self._pause_requested,  # Pass pause event for granular control
            continuous_mode=continuous_mode,
            inherited_conversation=inherited_conversation,
            cumulative_output_keys=cumulative_output_keys or [],
            event_triggered=event_triggered,
            accounts_prompt=node_accounts_prompt,
            execution_id=self.runtime.execution_id,
        )

    VALID_NODE_TYPES = {
        "event_loop",
    }
    # Node types removed in v0.5 — provide migration guidance
    REMOVED_NODE_TYPES = {
        "function": "event_loop",
        "llm_tool_use": "event_loop",
        "llm_generate": "event_loop",
        "router": "event_loop",  # Unused theoretical infrastructure
        "human_input": "event_loop",  # Use client_facing=True instead
    }

    def _get_node_implementation(
        self, node_spec: NodeSpec, cleanup_llm_model: str | None = None
    ) -> NodeProtocol:
        """Get or create a node implementation."""
        # Check registry first
        if node_spec.id in self.node_registry:
            return self.node_registry[node_spec.id]

        # Reject removed node types with migration guidance
        if node_spec.node_type in self.REMOVED_NODE_TYPES:
            replacement = self.REMOVED_NODE_TYPES[node_spec.node_type]
            raise RuntimeError(
                f"Node type '{node_spec.node_type}' was removed in v0.5. "
                f"Migrate node '{node_spec.id}' to '{replacement}'. "
                f"See https://github.com/adenhq/hive/issues/4753 for migration guide."
            )

        # Validate node type
        if node_spec.node_type not in self.VALID_NODE_TYPES:
            raise RuntimeError(
                f"Invalid node type '{node_spec.node_type}' for node '{node_spec.id}'. "
                f"Must be one of: {sorted(self.VALID_NODE_TYPES)}."
            )

        # Create based on type (only event_loop is valid)
        if node_spec.node_type == "event_loop":
            # Auto-create EventLoopNode with sensible defaults.
            # Custom configs can still be pre-registered via node_registry.
            from framework.graph.event_loop_node import EventLoopNode, LoopConfig

            # Create a FileConversationStore if a storage path is available
            conv_store = None
            if self._storage_path:
                from framework.storage.conversation_store import FileConversationStore

                store_path = self._storage_path / "conversations"
                conv_store = FileConversationStore(base_path=store_path)

            # Auto-configure spillover directory for large tool results.
            # When a tool result exceeds max_tool_result_chars, the full
            # content is written to spillover_dir and the agent gets a
            # truncated preview with instructions to use load_data().
            # Uses storage_path/data which is session-scoped, matching the
            # data_dir set via execution context for data tools.
            spillover = None
            if self._storage_path:
                spillover = str(self._storage_path / "data")

            lc = self._loop_config
            default_max_iter = 100 if node_spec.client_facing else 50
            node = EventLoopNode(
                event_bus=self._event_bus,
                judge=None,  # implicit judge: accept when output_keys are filled
                config=LoopConfig(
                    max_iterations=lc.get("max_iterations", default_max_iter),
                    max_tool_calls_per_turn=lc.get("max_tool_calls_per_turn", 10),
                    tool_call_overflow_margin=lc.get("tool_call_overflow_margin", 0.5),
                    stall_detection_threshold=lc.get("stall_detection_threshold", 3),
                    max_history_tokens=lc.get("max_history_tokens", 32000),
                    max_tool_result_chars=lc.get("max_tool_result_chars", 3_000),
                    spillover_dir=spillover,
                ),
                tool_executor=self.tool_executor,
                conversation_store=conv_store,
            )
            # Cache so inject_event() is reachable for client-facing input
            self.node_registry[node_spec.id] = node
            return node

        # Should never reach here due to validation above
        raise RuntimeError(f"Unhandled node type: {node_spec.node_type}")

    async def _follow_edges(
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

            if await edge.should_traverse(
                source_success=result.success,
                source_output=result.output,
                memory=memory.read_all(),
                llm=self.llm,
                goal=goal,
                source_node_name=current_node_spec.name if current_node_spec else current_node_id,
                target_node_name=target_node_spec.name if target_node_spec else edge.target,
            ):
                # Validate and clean output before mapping inputs.
                # Use full memory state (not just result.output) because
                # target input_keys may come from earlier nodes in the
                # graph, not only from the immediate source node.
                if self.cleansing_config.enabled and target_node_spec:
                    output_to_validate = memory.read_all()

                    validation = self.output_cleaner.validate_output(
                        output=output_to_validate,
                        source_node_id=current_node_id,
                        target_node_spec=target_node_spec,
                    )

                    if not validation.valid:
                        self.logger.warning(f"⚠ Output validation failed: {validation.errors}")

                        # Clean the output
                        cleaned_output = await self.output_cleaner.clean_output(
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

    async def _get_all_traversable_edges(
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
            if await edge.should_traverse(
                source_success=result.success,
                source_output=result.output,
                memory=memory.read_all(),
                llm=self.llm,
                goal=goal,
                source_node_name=current_node_spec.name if current_node_spec else current_node_id,
                target_node_name=target_node_spec.name if target_node_spec else edge.target,
            ):
                traversable.append(edge)

        # Priority filtering for CONDITIONAL edges:
        # When multiple CONDITIONAL edges match, keep only the highest-priority
        # group.  This prevents mutually-exclusive conditional branches (e.g.
        # forward vs. feedback) from incorrectly triggering fan-out.
        # ON_SUCCESS / other edge types are unaffected.
        if len(traversable) > 1:
            conditionals = [e for e in traversable if e.condition == EdgeCondition.CONDITIONAL]
            if len(conditionals) > 1:
                max_prio = max(e.priority for e in conditionals)
                traversable = [
                    e
                    for e in traversable
                    if e.condition != EdgeCondition.CONDITIONAL or e.priority == max_prio
                ]

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

            # Get node implementation to check its type
            branch_impl = self._get_node_implementation(node_spec, graph.cleanup_llm_model)

            effective_max_retries = node_spec.max_retries
            # Only override for actual EventLoopNode instances, not custom NodeProtocol impls
            from framework.graph.event_loop_node import EventLoopNode

            if isinstance(branch_impl, EventLoopNode) and effective_max_retries > 1:
                self.logger.warning(
                    f"EventLoopNode '{node_spec.id}' has "
                    f"max_retries={effective_max_retries}. Overriding "
                    "to 1 — event loop nodes handle retry internally."
                )
                effective_max_retries = 1

            branch.status = "running"

            try:
                # Validate and clean output before mapping inputs (same as _follow_edges).
                # Use full memory state since target input_keys may come
                # from earlier nodes, not just the immediate source.
                if self.cleansing_config.enabled and node_spec:
                    mem_snapshot = memory.read_all()
                    validation = self.output_cleaner.validate_output(
                        output=mem_snapshot,
                        source_node_id=source_node_spec.id if source_node_spec else "unknown",
                        target_node_spec=node_spec,
                    )

                    if not validation.valid:
                        self.logger.warning(
                            f"⚠ Output validation failed for branch "
                            f"{branch.node_id}: {validation.errors}"
                        )
                        cleaned_output = await self.output_cleaner.clean_output(
                            output=mem_snapshot,
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
                for attempt in range(effective_max_retries):
                    branch.retry_count = attempt

                    # Build context for this branch
                    ctx = self._build_context(node_spec, memory, goal, mapped, graph.max_tokens)
                    node_impl = self._get_node_implementation(node_spec, graph.cleanup_llm_model)

                    # Emit node-started event (skip event_loop nodes)
                    if self._event_bus and node_spec.node_type != "event_loop":
                        await self._event_bus.emit_node_loop_started(
                            stream_id=self._stream_id, node_id=branch.node_id
                        )

                    self.logger.info(
                        f"      ▶ Branch {node_spec.name}: executing (attempt {attempt + 1})"
                    )
                    result = await node_impl.execute(ctx)
                    last_result = result

                    # Ensure L2 entry for this branch node
                    if self.runtime_logger:
                        self.runtime_logger.ensure_node_logged(
                            node_id=node_spec.id,
                            node_name=node_spec.name,
                            node_type=node_spec.node_type,
                            success=result.success,
                            error=result.error,
                            tokens_used=result.tokens_used,
                            latency_ms=result.latency_ms,
                        )

                    # Emit node-completed event (skip event_loop nodes)
                    if self._event_bus and node_spec.node_type != "event_loop":
                        await self._event_bus.emit_node_loop_completed(
                            stream_id=self._stream_id, node_id=branch.node_id, iterations=1
                        )

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
                        f"retry {attempt + 1}/{effective_max_retries}"
                    )

                # All retries exhausted
                branch.status = "failed"
                branch.error = last_result.error if last_result else "Unknown error"
                branch.result = last_result
                self.logger.error(
                    f"      ✗ Branch {node_spec.name}: "
                    f"failed after {effective_max_retries} attempts"
                )
                return branch, last_result

            except Exception as e:
                import traceback

                stack_trace = traceback.format_exc()
                branch.status = "failed"
                branch.error = str(e)
                self.logger.error(f"      ✗ Branch {branch.node_id}: exception - {e}")

                # Log the crashing branch node to L2 with full stack trace
                if self.runtime_logger and node_spec is not None:
                    self.runtime_logger.ensure_node_logged(
                        node_id=node_spec.id,
                        node_name=node_spec.name,
                        node_type=node_spec.node_type,
                        success=False,
                        error=str(e),
                        stacktrace=stack_trace,
                    )

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

    def request_pause(self) -> None:
        """
        Request graceful pause of the current execution.

        The execution will pause at the next node boundary after the current
        node completes. A checkpoint will be saved at the pause point, allowing
        the execution to be resumed later.

        This method is safe to call from any thread.
        """
        self._pause_requested.set()
        self.logger.info("⏸ Pause requested - will pause at next node boundary")

    def _create_checkpoint(
        self,
        checkpoint_type: str,
        current_node: str,
        execution_path: list[str],
        memory: SharedMemory,
        next_node: str | None = None,
        is_clean: bool = True,
    ) -> Checkpoint:
        """
        Create a checkpoint from current execution state.

        Args:
            checkpoint_type: Type of checkpoint (node_start, node_complete)
            current_node: Current node ID
            execution_path: Nodes executed so far
            memory: SharedMemory instance
            next_node: Next node to execute (for node_complete checkpoints)
            is_clean: Whether execution was clean up to this point

        Returns:
            New Checkpoint instance
        """

        return Checkpoint.create(
            checkpoint_type=checkpoint_type,
            session_id=self._storage_path.name if self._storage_path else "unknown",
            current_node=current_node,
            execution_path=execution_path,
            shared_memory=memory.read_all(),
            next_node=next_node,
            is_clean=is_clean,
        )
