"""
Graph Executor - Runs agent graphs.

The executor:
1. Takes a GraphSpec and Goal
2. Initializes data buffer
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
from framework.graph.context import GraphContext, build_node_context
from framework.graph.conversation import LEGACY_RUN_ID
from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import (
    DataBuffer,
    NodeProtocol,
    NodeResult,
    NodeSpec,
)
from framework.graph.validator import OutputValidator
from framework.llm.provider import LLMProvider, Tool
from framework.observability import set_trace_context
from framework.runtime.core import Runtime
from framework.schemas.checkpoint import Checkpoint
from framework.storage.checkpoint_store import CheckpointStore
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)


def _default_max_context_tokens() -> int:
    """Resolve max_context_tokens from global config, falling back to 32000."""
    try:
        from framework.config import get_max_context_tokens

        return get_max_context_tokens()
    except Exception:
        return 32_000


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

    # Buffer conflict handling when branches write same key
    buffer_conflict_strategy: str = "last_wins"  # "last_wins", "first_wins", "error"

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
        enable_parallel_execution: bool = True,
        parallel_config: ParallelExecutionConfig | None = None,
        event_bus: Any | None = None,
        stream_id: str = "",
        execution_id: str = "",
        run_id: str = "",
        runtime_logger: Any = None,
        storage_path: str | Path | None = None,
        loop_config: dict[str, Any] | None = None,
        accounts_prompt: str = "",
        accounts_data: list[dict] | None = None,
        tool_provider_map: dict[str, str] | None = None,
        dynamic_tools_provider: Callable | None = None,
        dynamic_prompt_provider: Callable | None = None,
        dynamic_memory_provider: Callable | None = None,
        iteration_metadata_provider: Callable | None = None,
        skills_catalog_prompt: str = "",
        protocols_prompt: str = "",
        skill_dirs: list[str] | None = None,
        context_warn_ratio: float | None = None,
        batch_init_nudge: str | None = None,
        colony_memory_dir: Any = None,
        colony_worker_sessions_dir: Any = None,
        colony_recall_cache: dict[str, str] | None = None,
        colony_reflect_llm: Any = None,
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
            dynamic_tools_provider: Optional callback returning current
                tool list (for mode switching)
            dynamic_prompt_provider: Optional callback returning current
                system prompt (for phase switching)
            dynamic_memory_provider: Optional callback returning the current
                memory block to inject into node prompts
            skills_catalog_prompt: Available skills catalog for system prompt
            protocols_prompt: Default skill operational protocols for system prompt
            skill_dirs: Skill base directories for Tier 3 resource access
            context_warn_ratio: Token usage ratio to trigger DS-13 preservation warning
            batch_init_nudge: System prompt nudge for DS-12 batch auto-detection
        """
        self.runtime = runtime
        self.llm = llm
        self.tools = tools or []
        self.tool_executor = tool_executor
        self.node_registry = node_registry or {}
        self.approval_callback = approval_callback
        self.validator = OutputValidator()
        self.logger = logging.getLogger(__name__)
        self.logger.debug(
            "[GraphExecutor.__init__] Created with"
            " stream_id=%s, execution_id=%s,"
            " initial node_registry keys: %s",
            stream_id,
            execution_id,
            list(self.node_registry.keys()),
        )
        self._event_bus = event_bus
        self._stream_id = stream_id
        self._execution_id = execution_id or getattr(runtime, "execution_id", "")
        self._run_id = run_id
        self.runtime_logger = runtime_logger
        self._storage_path = Path(storage_path) if storage_path else None
        self._loop_config = loop_config or {}
        self.accounts_prompt = accounts_prompt
        self.accounts_data = accounts_data
        self.tool_provider_map = tool_provider_map
        self.dynamic_tools_provider = dynamic_tools_provider
        self.dynamic_prompt_provider = dynamic_prompt_provider
        self.dynamic_memory_provider = dynamic_memory_provider
        self.iteration_metadata_provider = iteration_metadata_provider
        self.skills_catalog_prompt = skills_catalog_prompt
        self.protocols_prompt = protocols_prompt
        self.skill_dirs: list[str] = skill_dirs or []
        self.context_warn_ratio: float | None = context_warn_ratio
        self.batch_init_nudge: str | None = batch_init_nudge
        self.colony_memory_dir = colony_memory_dir
        self.colony_worker_sessions_dir = colony_worker_sessions_dir
        self.colony_recall_cache = colony_recall_cache or {}
        self.colony_reflect_llm = colony_reflect_llm

        if protocols_prompt:
            self.logger.info(
                "GraphExecutor[%s] received protocols_prompt (%d chars)",
                stream_id,
                len(protocols_prompt),
            )
        else:
            self.logger.warning(
                "GraphExecutor[%s] received EMPTY protocols_prompt",
                stream_id,
            )

        # Parallel execution settings
        self.enable_parallel_execution = enable_parallel_execution
        self._parallel_config = parallel_config or ParallelExecutionConfig()

        # Pause/resume control
        self._pause_requested = asyncio.Event()

        # Track the currently executing node for external injection routing
        self.current_node_id: str | None = None

    def _write_progress(
        self,
        current_node: str,
        path: list[str],
        buffer: Any,
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
        state_path = self._storage_path / "state.json"
        try:
            import json as _json
            from datetime import datetime

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

            # Persist full buffer so state.json is sufficient for resume
            # even if the process dies before the final write.
            buffer_snapshot = buffer.read_all()
            state_data["data_buffer"] = buffer_snapshot
            state_data["buffer_keys"] = list(buffer_snapshot.keys())
            if self._run_id:
                state_data["current_run_id"] = self._run_id

            with atomic_write(state_path, encoding="utf-8") as f:
                _json.dump(state_data, f, indent=2)
        except Exception:
            logger.warning(
                "Failed to persist progress state to %s",
                state_path,
                exc_info=True,
            )

    def _validate_tools(self, graph: GraphSpec) -> list[str]:
        """
        Validate that all tools declared by reachable nodes are available.

        Only checks nodes reachable from graph.entry_node via edges.
        Nodes belonging to other entry points are skipped — they will be validated
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

    # Max chars of formatted messages before proactively splitting for LLM.
    _PHASE_LLM_CHAR_LIMIT = 240_000
    _PHASE_LLM_MAX_DEPTH = 10

    async def _phase_llm_compact(
        self,
        conversation: Any,
        next_spec: NodeSpec,
        messages: list,
        _depth: int = 0,
    ) -> str:
        """Summarise messages for phase-boundary compaction.

        Uses the same recursive binary-search splitting as EventLoopNode.
        """
        from framework.graph.conversation import extract_tool_call_history
        from framework.graph.event_loop_node import _is_context_too_large_error

        if _depth > self._PHASE_LLM_MAX_DEPTH:
            raise RuntimeError("Phase LLM compaction recursion limit")

        # Format messages
        lines: list[str] = []
        for m in messages:
            if m.role == "tool":
                c = m.content[:500] + ("..." if len(m.content) > 500 else "")
                lines.append(f"[tool result]: {c}")
            elif m.role == "assistant" and m.tool_calls:
                names = [tc.get("function", {}).get("name", "?") for tc in m.tool_calls]
                lines.append(
                    f"[assistant (calls: {', '.join(names)})]: "
                    f"{m.content[:200] if m.content else ''}"
                )
            else:
                lines.append(f"[{m.role}]: {m.content}")
        formatted = "\n\n".join(lines)

        # Proactive split
        if len(formatted) > self._PHASE_LLM_CHAR_LIMIT and len(messages) > 1:
            summary = await self._phase_llm_compact_split(
                conversation,
                next_spec,
                messages,
                _depth,
            )
        else:
            max_tokens = getattr(conversation, "_max_context_tokens", 32000)
            target_tokens = max_tokens // 2
            target_chars = target_tokens * 4

            prompt = (
                "You are compacting an AI agent's conversation history "
                "at a phase boundary.\n\n"
                f"NEXT PHASE: {next_spec.name}\n"
            )
            if next_spec.description:
                prompt += f"NEXT PHASE PURPOSE: {next_spec.description}\n"
            prompt += (
                f"\nCONVERSATION MESSAGES:\n{formatted}\n\n"
                "INSTRUCTIONS:\n"
                f"Write a summary of approximately {target_chars} characters "
                f"(~{target_tokens} tokens).\n"
                "Preserve user-stated rules, constraints, and preferences "
                "verbatim. Preserve key decisions and results from earlier "
                "phases. Preserve context needed for the next phase.\n"
            )
            summary_budget = max(1024, max_tokens // 2)
            try:
                response = await self._llm.acomplete(
                    messages=[{"role": "user", "content": prompt}],
                    system=(
                        "You are a conversation compactor. Write a detailed "
                        "summary preserving context for the next phase."
                    ),
                    max_tokens=summary_budget,
                )
                summary = response.content
            except Exception as e:
                if _is_context_too_large_error(e) and len(messages) > 1:
                    summary = await self._phase_llm_compact_split(
                        conversation,
                        next_spec,
                        messages,
                        _depth,
                    )
                else:
                    raise

        # Append tool history at top level only
        if _depth == 0:
            tool_history = extract_tool_call_history(messages)
            if tool_history and "TOOLS ALREADY CALLED" not in summary:
                summary += "\n\n" + tool_history

        return summary

    async def _phase_llm_compact_split(
        self,
        conversation: Any,
        next_spec: NodeSpec,
        messages: list,
        _depth: int,
    ) -> str:
        """Split messages in half and summarise each half."""
        mid = max(1, len(messages) // 2)
        s1 = await self._phase_llm_compact(
            conversation,
            next_spec,
            messages[:mid],
            _depth + 1,
        )
        s2 = await self._phase_llm_compact(
            conversation,
            next_spec,
            messages[mid:],
            _depth + 1,
        )
        return s1 + "\n\n" + s2

    def _get_runtime_log_session_id(self) -> str:
        """Return the session-backed execution ID for runtime logging, if any."""
        if not self._storage_path:
            return ""
        if self._storage_path.parent.name != "sessions":
            return ""
        return self._storage_path.name

    async def execute(
        self,
        graph: GraphSpec,
        goal: Goal,
        input_data: dict[str, Any] | None = None,
        session_state: dict[str, Any] | None = None,
        checkpoint_config: "CheckpointConfig | None" = None,
        validate_graph: bool = True,
    ) -> ExecutionResult:
        """
        Execute a graph for a goal.

        Args:
            graph: The graph specification
            goal: The goal driving execution
            input_data: Initial input data
            session_state: Optional session state to resume from (with paused_at, data_buffer, etc.)
            validate_graph: If False, skip graph validation (for test graphs that
                intentionally break rules)

        Returns:
            ExecutionResult with output and metrics
        """
        # Add agent_id to trace context for correlation
        set_trace_context(agent_id=graph.id)

        # Validate graph
        if validate_graph:
            result = graph.validate()
            if result["errors"]:
                return ExecutionResult(
                    success=False,
                    error=f"Invalid graph: {result['errors']}",
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
        buffer = DataBuffer()

        # Continuous conversation mode state
        is_continuous = getattr(graph, "conversation_mode", "isolated") == "continuous"
        continuous_conversation = None  # NodeConversation threaded across nodes  # noqa: F841
        cumulative_tools: list = []  # Tools accumulate, never removed  # noqa: F841
        cumulative_tool_names: set[str] = set()  # noqa: F841
        cumulative_output_keys: list[str] = []  # noqa: F841

        # Build node registry for subagent lookup
        node_registry: dict[str, NodeSpec] = {  # noqa: F841
            node.id: node for node in graph.nodes
        }

        # Initialize checkpoint store if checkpointing is enabled
        checkpoint_store: CheckpointStore | None = None
        if checkpoint_config and checkpoint_config.enabled and self._storage_path:
            checkpoint_store = CheckpointStore(self._storage_path)
            self.logger.info("✓ Checkpointing enabled")

        # Restore session state if provided
        if session_state and ("data_buffer" in session_state or "memory" in session_state):
            buffer_data = session_state.get("data_buffer", session_state.get("memory"))
            # [RESTORED] Type safety check
            if not isinstance(buffer_data, dict):
                self.logger.warning(
                    f"⚠️ Invalid data buffer type in session state: "
                    f"{type(buffer_data).__name__}, expected dict"
                )
            else:
                # Restore buffer from previous session.
                # Skip validation — this data was already validated when
                # originally written, and research text triggers false
                # positives on the code-indicator heuristic.
                for key, value in buffer_data.items():
                    buffer.write(key, value, validate=False)
                self.logger.info(f"📥 Restored session state with {len(buffer_data)} buffer keys")

        # Logical worker run boundary:
        # - fresh triggers use the ExecutionStream-provided run_id
        # - checkpoint resumes may pin a prior run_id in session_state/checkpoint
        active_run_id = session_state.get("run_id") if session_state else None
        if not active_run_id:
            active_run_id = self._run_id
        self._run_id = active_run_id or ""

        # Write new input data to buffer (each key individually).
        # Skip when resuming from a paused session — restored buffer already
        # contains all state including the original input, and re-writing
        # input_data would overwrite intermediate results with stale values.
        _is_resuming = bool(
            session_state
            and (session_state.get("paused_at") or session_state.get("resume_from_checkpoint"))
        )
        if input_data and not _is_resuming:
            for key, value in input_data.items():
                buffer.write(key, value)

        # Detect event-triggered execution (timer/webhook) — no interactive user.
        _event_triggered = bool(input_data and isinstance(input_data.get("event"), dict))

        path: list[str] = []
        total_tokens = 0  # noqa: F841
        total_latency = 0  # noqa: F841
        node_retry_counts: dict[str, int] = {}  # noqa: F841
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
                    checkpoint_run_id = checkpoint.run_id or LEGACY_RUN_ID
                    self._run_id = checkpoint_run_id

                    # Restore buffer from checkpoint
                    for key, value in checkpoint.data_buffer.items():
                        buffer.write(key, value, validate=False)

                    # Start from checkpoint's next node or current node
                    current_node_id = (
                        checkpoint.next_node or checkpoint.current_node or graph.entry_node
                    )

                    # Restore execution path
                    path.extend(checkpoint.execution_path)

                    self.logger.info(
                        f"📥 Restored buffer with {len(checkpoint.data_buffer)} keys, "
                        f"resuming at node: {current_node_id}"
                    )
                else:
                    self.logger.warning(
                        f"Checkpoint {checkpoint_id} not found, resuming from normal entry point"
                    )
                    current_node_id = graph.get_entry_point(session_state)

            except Exception as e:
                self.logger.error(
                    f"Failed to load checkpoint {checkpoint_id}: {e}, "
                    f"resuming from normal entry point"
                )
                current_node_id = graph.get_entry_point(session_state)
        else:
            current_node_id = graph.get_entry_point(session_state)

        steps = 0  # noqa: F841

        if session_state and current_node_id != graph.entry_node:
            self.logger.info(f"🔄 Resuming from: {current_node_id}")

            # Emit resume event
            if self._event_bus:
                await self._event_bus.emit_execution_resumed(
                    stream_id=self._stream_id,
                    node_id=current_node_id,
                    execution_id=self._execution_id,
                )

        # Start run
        _run_id = self.runtime.start_run(
            goal_id=goal.id,
            goal_description=goal.description,
            input_data=input_data or {},
        )

        if self.runtime_logger:
            session_id = self._get_runtime_log_session_id()
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
            return await self._execute_with_workers(
                graph=graph,
                goal=goal,
                buffer=buffer,
                input_data=input_data or {},
                session_state=session_state,
                node_visit_counts=node_visit_counts,
                is_continuous=is_continuous,
                checkpoint_store=checkpoint_store,
                checkpoint_config=checkpoint_config,
                _ctx_token=_ctx_token,
            )

        finally:
            if _ctx_token is not None:
                from framework.runner.tool_registry import ToolRegistry

                ToolRegistry.reset_execution_context(_ctx_token)

    VALID_NODE_TYPES = {
        "event_loop",
        "gcu",
    }
    # Node types removed in v0.5 — provide migration guidance
    REMOVED_NODE_TYPES = {
        "function": "event_loop",
        "llm_tool_use": "event_loop",
        "llm_generate": "event_loop",
        "router": "event_loop",  # Unused theoretical infrastructure
        "human_input": "event_loop",  # Use queen interaction / escalation instead
    }

    def _get_node_implementation(
        self, node_spec: NodeSpec, cleanup_llm_model: str | None = None
    ) -> NodeProtocol:
        """Get or create a node implementation."""
        # Check registry first
        if node_spec.id in self.node_registry:
            logger.debug(
                "[GraphExecutor._get_node_implementation] Found node '%s' in registry", node_spec.id
            )
            return self.node_registry[node_spec.id]
        logger.debug(
            "[GraphExecutor._get_node_implementation]"
            " Node '%s' not in registry (keys: %s),"
            " creating new",
            node_spec.id,
            list(self.node_registry.keys()),
        )

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

        # Create based on type
        if node_spec.node_type in ("event_loop", "gcu"):
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

            from framework.graph.node import warn_if_deprecated_client_facing

            warn_if_deprecated_client_facing(node_spec)

            lc = self._loop_config
            default_max_iter = 100 if node_spec.supports_direct_user_io() else 50
            node = EventLoopNode(
                event_bus=self._event_bus,
                judge=None,  # implicit judge: accept when output_keys are filled
                config=LoopConfig(
                    max_iterations=lc.get("max_iterations", default_max_iter),
                    max_tool_calls_per_turn=lc.get("max_tool_calls_per_turn", 30),
                    tool_call_overflow_margin=lc.get("tool_call_overflow_margin", 0.5),
                    stall_detection_threshold=lc.get("stall_detection_threshold", 3),
                    max_context_tokens=lc.get("max_context_tokens", _default_max_context_tokens()),
                    max_tool_result_chars=lc.get("max_tool_result_chars", 30_000),
                    spillover_dir=spillover,
                    hooks=lc.get("hooks", {}),
                ),
                tool_executor=self.tool_executor,
                conversation_store=conv_store,
            )
            # Cache so inject_event() is reachable for queen interaction and escalation routing
            self.node_registry[node_spec.id] = node
            logger.debug(
                "[GraphExecutor._get_node_implementation]"
                " Cached node '%s' in node_registry,"
                " registry now has keys: %s",
                node_spec.id,
                list(self.node_registry.keys()),
            )
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
        buffer: DataBuffer,
    ) -> str | None:
        """Determine the next node by following edges."""
        edges = graph.get_outgoing_edges(current_node_id)

        for edge in edges:
            target_node_spec = graph.get_node(edge.target)

            if await edge.should_traverse(
                source_success=result.success,
                source_output=result.output,
                buffer_data=buffer.read_all(),
                llm=self.llm,
                goal=goal,
                source_node_name=current_node_spec.name if current_node_spec else current_node_id,
                target_node_name=target_node_spec.name if target_node_spec else edge.target,
            ):
                # Map inputs (skip validation for processed LLM output)
                mapped = edge.map_inputs(result.output, buffer.read_all())
                for key, value in mapped.items():
                    buffer.write(key, value, validate=False)

                return edge.target

        return None

    async def _get_all_traversable_edges(
        self,
        graph: GraphSpec,
        goal: Goal,
        current_node_id: str,
        current_node_spec: Any,
        result: NodeResult,
        buffer: DataBuffer,
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
                buffer_data=buffer.read_all(),
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
        buffer: DataBuffer,
        source_result: NodeResult,
        source_node_spec: Any,
        path: list[str],
        node_registry: dict[str, NodeSpec] | None = None,
    ) -> tuple[dict[str, NodeResult], int, int]:
        """
        Execute multiple branches in parallel using asyncio.gather.

        Args:
            graph: The graph specification
            goal: The execution goal
            edges: List of edges to follow in parallel
            buffer: DataBuffer instance
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

        # Track which branch wrote which key for buffer conflict detection
        fanout_written_keys: dict[str, str] = {}  # key -> branch_id that wrote it
        fanout_keys_lock = asyncio.Lock()

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
                # Map inputs via edge
                mapped = branch.edge.map_inputs(source_result.output, buffer.read_all())
                for key, value in mapped.items():
                    await buffer.write_async(key, value)

                # Execute with retries
                last_result = None
                for attempt in range(effective_max_retries):
                    branch.retry_count = attempt

                    # Build context for this branch
                    ctx = build_node_context(
                        runtime=self.runtime,
                        node_spec=node_spec,
                        buffer=buffer,
                        goal=goal,
                        llm=self.llm,
                        tools=self.tools,
                        max_tokens=graph.max_tokens,
                        input_data=mapped,
                        runtime_logger=self.runtime_logger,
                        pause_event=self._pause_requested,
                        accounts_prompt=self.accounts_prompt,
                        accounts_data=self.accounts_data,
                        tool_provider_map=self.tool_provider_map,
                        identity_prompt=getattr(graph, "identity_prompt", "") or "",
                        narrative="",
                        execution_id=self._execution_id,
                        run_id=self._run_id,
                        stream_id=self._stream_id,
                        node_registry=node_registry,
                        all_tools=self.tools,
                        shared_node_registry=self.node_registry,
                        dynamic_tools_provider=self.dynamic_tools_provider,
                        dynamic_prompt_provider=self.dynamic_prompt_provider,
                        dynamic_memory_provider=self.dynamic_memory_provider,
                        iteration_metadata_provider=self.iteration_metadata_provider,
                        skills_catalog_prompt=self.skills_catalog_prompt,
                        protocols_prompt=self.protocols_prompt,
                        skill_dirs=self.skill_dirs,
                        default_skill_warn_ratio=self.context_warn_ratio,
                        default_skill_batch_nudge=self.batch_init_nudge,
                    )
                    node_impl = self._get_node_implementation(node_spec, graph.cleanup_llm_model)

                    # Emit node-started event (skip event_loop nodes)
                    if self._event_bus and node_spec.node_type != "event_loop":
                        await self._event_bus.emit_node_loop_started(
                            stream_id=self._stream_id,
                            node_id=branch.node_id,
                            execution_id=self._execution_id,
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
                            stream_id=self._stream_id,
                            node_id=branch.node_id,
                            iterations=1,
                            execution_id=self._execution_id,
                        )

                    if result.success:
                        # Write outputs to shared buffer with conflict detection
                        conflict_strategy = self._parallel_config.buffer_conflict_strategy
                        for key, value in result.output.items():
                            async with fanout_keys_lock:
                                prior_branch = fanout_written_keys.get(key)
                                if prior_branch and prior_branch != branch.branch_id:
                                    if conflict_strategy == "error":
                                        raise RuntimeError(
                                            f"Buffer conflict: key '{key}' already written "
                                            f"by branch '{prior_branch}', "
                                            f"conflicting write from '{branch.branch_id}'"
                                        )
                                    elif conflict_strategy == "first_wins":
                                        self.logger.debug(
                                            f"      ⚠ Skipping write to '{key}' "
                                            f"(first_wins: already set by {prior_branch})"
                                        )
                                        continue
                                    else:
                                        # last_wins (default): write and log
                                        self.logger.debug(
                                            f"      ⚠ Key '{key}' overwritten "
                                            f"(last_wins: {prior_branch} -> {branch.branch_id})"
                                        )
                                fanout_written_keys[key] = branch.branch_id
                            await buffer.write_async(key, value)

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

        # Execute all branches concurrently with per-branch timeout
        timeout = self._parallel_config.branch_timeout_seconds
        branch_list = list(branches.values())
        tasks = [asyncio.wait_for(execute_single_branch(b), timeout=timeout) for b in branch_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        total_tokens = 0
        total_latency = 0
        branch_results: dict[str, NodeResult] = {}
        failed_branches: list[ParallelBranch] = []

        for i, result in enumerate(results):
            branch = branch_list[i]

            if isinstance(result, asyncio.TimeoutError):
                # Branch timed out
                branch.status = "timed_out"
                branch.error = f"Branch timed out after {timeout}s"
                self.logger.warning(
                    f"      ⏱ Branch {graph.get_node(branch.node_id).name}: "
                    f"timed out after {timeout}s"
                )
                path.append(branch.node_id)
                failed_branches.append(branch)
            elif isinstance(result, Exception):
                path.append(branch.node_id)
                failed_branches.append(branch)
            else:
                returned_branch, node_result = result
                path.append(returned_branch.node_id)
                if node_result is None or isinstance(node_result, Exception):
                    failed_branches.append(returned_branch)
                elif not node_result.success:
                    failed_branches.append(returned_branch)
                else:
                    total_tokens += node_result.tokens_used
                    total_latency += node_result.latency_ms
                    branch_results[returned_branch.branch_id] = node_result

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
        buffer: DataBuffer,
        next_node: str | None = None,
        is_clean: bool = True,
    ) -> Checkpoint:
        """
        Create a checkpoint from current execution state.

        Args:
            checkpoint_type: Type of checkpoint (node_start, node_complete)
            current_node: Current node ID
            execution_path: Nodes executed so far
            buffer: DataBuffer instance
            next_node: Next node to execute (for node_complete checkpoints)
            is_clean: Whether execution was clean up to this point

        Returns:
            New Checkpoint instance
        """

        return Checkpoint.create(
            checkpoint_type=checkpoint_type,
            session_id=self._storage_path.name if self._storage_path else "unknown",
            run_id=self._run_id or None,
            current_node=current_node,
            execution_path=execution_path,
            data_buffer=buffer.read_all(),
            next_node=next_node,
            is_clean=is_clean,
        )

    # ------------------------------------------------------------------
    # Worker-based execution
    # ------------------------------------------------------------------

    async def _execute_with_workers(
        self,
        graph: GraphSpec,
        goal: Goal,
        buffer: DataBuffer,
        input_data: dict[str, Any],
        session_state: dict[str, Any] | None,
        node_visit_counts: dict[str, int],
        is_continuous: bool,
        checkpoint_store: CheckpointStore | None,
        checkpoint_config: CheckpointConfig | None,
        _ctx_token: Any,
    ) -> ExecutionResult:
        """Execute a graph using event-driven WorkerAgents.

        Replaces the imperative while-loop with autonomous workers that
        self-activate based on edge conditions and fan-out tracking.
        """
        from framework.graph.worker_agent import (
            Activation,
            FanOutTag,
            WorkerAgent,
            WorkerCompletion,
            WorkerLifecycle,
        )
        from framework.runtime.event_bus import AgentEvent, EventType

        # Build shared graph context
        gc = GraphContext(
            graph=graph,
            goal=goal,
            buffer=buffer,
            runtime=self.runtime,
            llm=self.llm,
            tools=self.tools,
            tool_executor=self.tool_executor,
            event_bus=self._event_bus,
            execution_id=self._execution_id,
            stream_id=self._stream_id,
            run_id=self._run_id,
            storage_path=self._storage_path,
            runtime_logger=self.runtime_logger,
            node_registry=self.node_registry,
            node_spec_registry={node.id: node for node in graph.nodes},
            parallel_config=self._parallel_config,
            enable_parallel_execution=self.enable_parallel_execution,
            is_continuous=is_continuous,
            accounts_prompt=self.accounts_prompt,
            accounts_data=self.accounts_data,
            tool_provider_map=self.tool_provider_map,
            skills_catalog_prompt=self.skills_catalog_prompt,
            protocols_prompt=self.protocols_prompt,
            skill_dirs=self.skill_dirs,
            context_warn_ratio=self.context_warn_ratio,
            batch_init_nudge=self.batch_init_nudge,
            dynamic_tools_provider=self.dynamic_tools_provider,
            dynamic_prompt_provider=self.dynamic_prompt_provider,
            dynamic_memory_provider=self.dynamic_memory_provider,
            iteration_metadata_provider=self.iteration_metadata_provider,
            loop_config=self._loop_config,
            node_visit_counts=dict(node_visit_counts),
            colony_memory_dir=self.colony_memory_dir,
            worker_sessions_dir=self.colony_worker_sessions_dir,
            colony_recall_cache=self.colony_recall_cache,
            colony_reflect_llm=self.colony_reflect_llm,
        )

        # Create one WorkerAgent per node
        workers: dict[str, WorkerAgent] = {}
        for node_spec in graph.nodes:
            workers[node_spec.id] = WorkerAgent(node_spec=node_spec, graph_context=gc)

        # Identify entry workers (graph entry node, not based on edge count)
        # A node can be the entry point AND have incoming feedback edges.
        entry_worker_ids = [graph.entry_node]
        terminal_worker_ids = set(graph.terminal_nodes or [])

        self.logger.info(
            f"🚀 Worker execution: {len(workers)} workers, "
            f"{len(entry_worker_ids)} entry, {len(terminal_worker_ids)} terminal"
        )

        # Completion tracking
        completed_terminals: set[str] = set()
        failed_workers: dict[str, str] = {}  # worker_id -> error
        all_completions: dict[str, WorkerCompletion] = {}
        completion_event = asyncio.Event()
        execution_error: str | None = None

        # Total metrics
        total_tokens = 0
        total_latency = 0

        def _deserialize_activations(data_list: list[dict]) -> list[Activation]:
            """Reconstruct Activation objects from event data."""
            activations = []
            for act_data in data_list:
                edge_id = act_data["edge_id"]
                edge = None
                for e in graph.edges:
                    if e.id == edge_id:
                        edge = e
                        break
                if not edge:
                    continue

                fan_out_tags = []
                for tag_data in act_data.get("fan_out_tags", []):
                    fan_out_tags.append(
                        FanOutTag(
                            fan_out_id=tag_data["fan_out_id"],
                            fan_out_source=tag_data["fan_out_source"],
                            branches=frozenset(tag_data["branches"]),
                            via_branch=tag_data["via_branch"],
                        )
                    )

                activations.append(
                    Activation(
                        source_id=act_data["source_id"],
                        target_id=act_data["target_id"],
                        edge_id=edge_id,
                        edge=edge,
                        mapped_inputs=act_data.get("mapped_inputs", {}),
                        fan_out_tags=fan_out_tags,
                    )
                )
            return activations

        def _check_graph_done() -> bool:
            """Check whether active graph work has reached a terminal state."""
            # Step-limit guard (equivalent to old while-loop's max_steps)
            if len(gc.path) >= graph.max_steps:
                return True
            if not terminal_worker_ids:
                # No terminals: check if all workers are done
                return all(
                    w.lifecycle in (WorkerLifecycle.COMPLETED, WorkerLifecycle.FAILED)
                    for w in workers.values()
                )
            if any(w.lifecycle == WorkerLifecycle.RUNNING for w in workers.values()):
                return False
            return any(
                tid in completed_terminals or tid in failed_workers for tid in terminal_worker_ids
            )

        def _mark_quiescent_terminal_failure() -> bool:
            nonlocal execution_error
            if execution_error is not None or not terminal_worker_ids:
                return False
            if any(w.lifecycle == WorkerLifecycle.RUNNING for w in workers.values()):
                return False
            if any(
                tid in completed_terminals or tid in failed_workers for tid in terminal_worker_ids
            ):
                return False
            execution_error = (
                "Worker execution ended before terminal nodes completed: "
                f"{sorted(terminal_worker_ids)}"
            )
            self.logger.error(execution_error)
            return True

        # Track fan-out branch workers for per-branch timeout enforcement
        _fanout_branch_tasks: dict[str, asyncio.Task] = {}  # worker_id → timeout-wrapper task
        branch_timeout = (
            self._parallel_config.branch_timeout_seconds if self._parallel_config else 300.0
        )

        def _route_activation(
            activation: Activation,
            workers_map: dict[str, WorkerAgent],
            pending_tasks_map: dict[str, asyncio.Task],
            *,
            has_event_subscription: bool,
        ) -> None:
            """Route an activation to its target worker.

            Handles re-visiting completed workers (feedback loops) by
            resetting them to PENDING before activation.
            """
            target_worker = workers_map.get(activation.target_id)
            if not target_worker:
                return

            # If target is already running, skip
            if target_worker.lifecycle == WorkerLifecycle.RUNNING:
                return

            # If target completed (feedback loop), reset for re-visit
            if target_worker.lifecycle in (WorkerLifecycle.COMPLETED, WorkerLifecycle.FAILED):
                target_worker.reset_for_revisit()

            if target_worker.lifecycle != WorkerLifecycle.PENDING:
                return

            target_worker.receive_activation(activation)

            if target_worker.check_readiness():
                target_worker.activate(inherited_tags=activation.fan_out_tags)
                if target_worker._task is not None:
                    # Fan-out branch: wrap with timeout
                    is_fanout_branch = any(
                        tag.via_branch == activation.target_id for tag in activation.fan_out_tags
                    )
                    if is_fanout_branch and branch_timeout > 0:
                        timed_task = asyncio.ensure_future(
                            asyncio.wait_for(target_worker._task, timeout=branch_timeout)
                        )
                        _fanout_branch_tasks[activation.target_id] = timed_task
                        pending_tasks_map[activation.target_id] = timed_task
                    else:
                        pending_tasks_map[activation.target_id] = target_worker._task

        # Subscribe to worker events
        sub_completed = None
        sub_failed = None

        async def _on_worker_completed(event: AgentEvent) -> None:
            nonlocal total_tokens, total_latency

            data = event.data
            worker_id = data["worker_id"]

            # Accumulate metrics
            total_tokens += data.get("tokens_used", 0)
            total_latency += data.get("latency_ms", 0)

            # Deserialize activations
            activations = _deserialize_activations(data.get("activations", []))

            completion = WorkerCompletion(
                worker_id=worker_id,
                success=data.get("success", True),
                output=data.get("output", {}),
                tokens_used=data.get("tokens_used", 0),
                latency_ms=data.get("latency_ms", 0),
                conversation=data.get("conversation"),
                activations=activations,
            )
            all_completions[worker_id] = completion

            # Update cumulative tools/keys for continuous mode
            if is_continuous:
                src_spec = graph.get_node(worker_id)
                if src_spec and src_spec.tools:
                    for t in self.tools:
                        if t.name in src_spec.tools and t.name not in gc.cumulative_tool_names:
                            gc.cumulative_tools.append(t)
                            gc.cumulative_tool_names.add(t.name)
                if src_spec and src_spec.output_keys:
                    for k in src_spec.output_keys:
                        if k not in gc.cumulative_output_keys:
                            gc.cumulative_output_keys.append(k)

                # Thread conversation
                if completion.conversation is not None:
                    gc.continuous_conversation = completion.conversation

            self.logger.info(
                f"  ✓ Worker completed: {worker_id} ({len(activations)} outgoing activation(s))"
            )

            # Route activations to target workers
            for activation in activations:
                _route_activation(
                    activation,
                    workers,
                    {},
                    has_event_subscription=True,
                )

            # Track terminal completion
            if worker_id in terminal_worker_ids:
                completed_terminals.add(worker_id)

            # Write progress
            self._write_progress(
                current_node=worker_id,
                path=gc.path,
                buffer=buffer,
                node_visit_counts=gc.node_visit_counts,
            )

            if _check_graph_done() or _mark_quiescent_terminal_failure():
                completion_event.set()

        async def _on_worker_failed(event: AgentEvent) -> None:
            data = event.data
            worker_id = data["worker_id"]
            error = data.get("error", "Unknown error")

            failed_workers[worker_id] = error
            self.logger.error(f"  ✗ Worker failed: {worker_id} - {error}")

            if worker_id in terminal_worker_ids:
                completed_terminals.add(worker_id)

            if _check_graph_done() or _mark_quiescent_terminal_failure():
                completion_event.set()

        # Subscribe to events (only if event bus has subscribe capability)
        has_event_subscription = self._event_bus is not None and hasattr(
            self._event_bus, "subscribe"
        )
        if has_event_subscription:
            sub_completed = self._event_bus.subscribe(
                event_types=[EventType.WORKER_COMPLETED],
                handler=_on_worker_completed,
                filter_stream=self._stream_id,
                filter_execution=self._execution_id,
            )
            sub_failed = self._event_bus.subscribe(
                event_types=[EventType.WORKER_FAILED],
                handler=_on_worker_failed,
                filter_stream=self._stream_id,
                filter_execution=self._execution_id,
            )

        try:
            # Activate entry workers
            for wid in entry_worker_ids:
                workers[wid].activate(inherited_tags=[])
                self.logger.info(f"  → Activated entry worker: {wid}")

            # Wait for completion — two strategies depending on event bus availability
            if has_event_subscription and sub_completed is not None:
                # Event-driven: wait for completion events
                await completion_event.wait()
            else:
                # No event bus: wait on worker tasks directly and route completions inline.
                pending_tasks: dict[str, asyncio.Task] = {
                    wid: w._task for wid, w in workers.items() if w._task is not None
                }
                while True:
                    if _check_graph_done():
                        break

                    if not pending_tasks:
                        unresolved_terminals = sorted(
                            tid
                            for tid in terminal_worker_ids
                            if tid not in completed_terminals and tid not in failed_workers
                        )
                        if unresolved_terminals:
                            execution_error = (
                                "Worker execution ended before terminal nodes completed: "
                                f"{unresolved_terminals}"
                            )
                            self.logger.error(execution_error)
                        else:
                            execution_error = (
                                "Worker execution ended before all workers reached "
                                "a terminal lifecycle state"
                            )
                            self.logger.error(execution_error)
                        break

                    task_to_worker = {task: wid for wid, task in pending_tasks.items()}
                    done, _pending = await asyncio.wait(
                        set(task_to_worker.keys()),
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    for task in done:
                        wid = task_to_worker[task]
                        pending_tasks.pop(wid, None)
                        worker = workers[wid]

                        if task.cancelled():
                            error = "Worker task was cancelled unexpectedly"
                            failed_workers[wid] = error
                            self.logger.error(f"  ✗ Worker failed: {wid} - {error}")
                            if wid in terminal_worker_ids:
                                completed_terminals.add(wid)
                            continue

                        task_error = None
                        try:
                            task_error = task.exception()
                        except Exception as exc:
                            task_error = exc

                        # Check for fan-out branch timeout
                        if (
                            isinstance(task_error, asyncio.TimeoutError)
                            and wid in _fanout_branch_tasks
                        ):
                            error = f"Branch failed (timed out after {branch_timeout}s)"
                            failed_workers[wid] = error
                            worker.lifecycle = WorkerLifecycle.FAILED
                            self.logger.warning(f"  ⏱ Branch {wid}: {error}")
                            if wid in terminal_worker_ids:
                                completed_terminals.add(wid)
                            _fanout_branch_tasks.pop(wid, None)
                            continue

                        if worker.lifecycle == WorkerLifecycle.COMPLETED and task_error is None:
                            # Read result directly from the worker
                            last_result = worker._last_result
                            outgoing_activations = worker._last_activations

                            if last_result:
                                completion_output = last_result.output or {}
                                completion_tokens = getattr(last_result, "tokens_used", 0) or 0
                                completion_latency = getattr(last_result, "latency_ms", 0) or 0
                                completion_conversation = getattr(last_result, "conversation", None)
                            else:
                                completion_output = {}
                                completion_tokens = 0
                                completion_latency = 0
                                completion_conversation = None

                            total_tokens += completion_tokens
                            total_latency += completion_latency

                            all_completions[wid] = WorkerCompletion(
                                worker_id=wid,
                                success=True,
                                output=completion_output,
                                tokens_used=completion_tokens,
                                latency_ms=completion_latency,
                                conversation=completion_conversation,
                                activations=outgoing_activations,
                            )

                            # Continuous mode accumulation
                            if is_continuous:
                                src_spec = graph.get_node(wid)
                                if src_spec and src_spec.tools:
                                    for t in self.tools:
                                        if (
                                            t.name in src_spec.tools
                                            and t.name not in gc.cumulative_tool_names
                                        ):
                                            gc.cumulative_tools.append(t)
                                            gc.cumulative_tool_names.add(t.name)
                                if src_spec and src_spec.output_keys:
                                    for k in src_spec.output_keys:
                                        if k not in gc.cumulative_output_keys:
                                            gc.cumulative_output_keys.append(k)
                                if completion_conversation is not None:
                                    gc.continuous_conversation = completion_conversation

                            self.logger.info(
                                f"  ✓ Worker completed: {wid} "
                                f"({len(outgoing_activations)} outgoing activation(s))"
                            )

                            # Route activations
                            for activation in outgoing_activations:
                                _route_activation(
                                    activation,
                                    workers,
                                    pending_tasks,
                                    has_event_subscription=False,
                                )

                            if wid in terminal_worker_ids:
                                completed_terminals.add(wid)

                            self._write_progress(
                                current_node=wid,
                                path=gc.path,
                                buffer=buffer,
                                node_visit_counts=gc.node_visit_counts,
                            )
                            continue

                        if worker.lifecycle == WorkerLifecycle.FAILED:
                            error = "Worker failed"
                            last_result = worker._last_result
                            if last_result and last_result.error:
                                error = last_result.error
                            elif task_error is not None:
                                error = str(task_error)

                            # Route ON_FAILURE activations
                            outgoing_activations = worker._last_activations
                            if outgoing_activations:
                                for activation in outgoing_activations:
                                    _route_activation(
                                        activation,
                                        workers,
                                        pending_tasks,
                                        has_event_subscription=False,
                                    )
                        elif task_error is not None:
                            error = str(task_error)
                        else:
                            error = (
                                "Worker task completed without publishing a completion "
                                f"(lifecycle={worker.lifecycle})"
                            )

                        failed_workers[wid] = error
                        self.logger.error(f"  ✗ Worker failed: {wid} - {error}")
                        if wid in terminal_worker_ids:
                            completed_terminals.add(wid)

            # Assemble result
            terminal_output: dict[str, Any] = {}
            for tid in terminal_worker_ids:
                if tid in all_completions:
                    terminal_output.update(all_completions[tid].output)

            if not terminal_output and all_completions:
                last_id = gc.path[-1] if gc.path else None
                if last_id and last_id in all_completions:
                    terminal_output = all_completions[last_id].output

            # Quality assessment
            has_failures = bool(failed_workers) or execution_error is not None
            # If all terminal workers completed successfully, intermediate failures
            # (handled by ON_FAILURE edges) don't count against overall success.
            if terminal_worker_ids and completed_terminals >= terminal_worker_ids:
                terminal_failures = terminal_worker_ids & set(failed_workers.keys())
                has_failures = bool(terminal_failures) or execution_error is not None
            has_retries = bool(gc.nodes_with_retries)
            if has_failures:
                exec_quality = "failed"
            elif has_retries:
                exec_quality = "degraded"
            else:
                exec_quality = "clean"

            saved_buffer = buffer.read_all()
            session_state_out = {
                "data_buffer": saved_buffer,
                "execution_path": list(gc.path),
                "node_visit_counts": dict(gc.node_visit_counts),
                "run_id": self._run_id,
            }

            success = not has_failures
            self.runtime.end_run(
                success=success,
                narrative=f"Completed {len(gc.path)} steps via {len(workers)} workers",
            )

            if self.runtime_logger:
                await self.runtime_logger.end_run(
                    status="success" if success else "failure",
                    duration_ms=total_latency,
                    node_path=gc.path,
                    execution_quality=exec_quality,
                )

            return ExecutionResult(
                success=success,
                output=terminal_output or saved_buffer,
                error=(
                    "; ".join(
                        part
                        for part in [
                            *[f"{k}: {v}" for k, v in failed_workers.items()],
                            execution_error,
                        ]
                        if part
                    )
                    or None
                ),
                steps_executed=len(gc.path),
                total_tokens=total_tokens,
                total_latency_ms=total_latency,
                path=gc.path,
                session_state=session_state_out,
                total_retries=sum(gc.retry_counts.values()),
                nodes_with_failures=list(set(failed_workers.keys()) | gc.nodes_with_retries),
                retry_details=dict(gc.retry_counts),
                had_partial_failures=has_failures or has_retries,
                execution_quality=exec_quality,
                node_visit_counts=dict(gc.node_visit_counts),
            )

        finally:
            if has_event_subscription and self._event_bus:
                if sub_completed:
                    self._event_bus.unsubscribe(sub_completed)
                if sub_failed:
                    self._event_bus.unsubscribe(sub_failed)
