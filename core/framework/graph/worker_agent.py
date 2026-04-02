"""
WorkerAgent — First-class autonomous worker for event-driven graph execution.

Each node in a graph becomes a WorkerAgent that:
- Owns its lifecycle, retry logic, memory scope, and LLM config
- Receives activations from upstream workers (via GraphExecutor routing)
- Self-checks readiness (fan-out group tracking)
- Self-triggers when ready
- Evaluates outgoing edges and publishes activations for downstream workers
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import (
    DataBuffer,
    NodeContext,
    NodeProtocol,
    NodeResult,
    NodeSpec,
)
from framework.graph.validator import OutputValidator
from framework.runtime.core import Runtime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & data types
# ---------------------------------------------------------------------------


class WorkerLifecycle(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class FanOutTag:
    """Carried in activations, propagated through the worker chain.

    When a source activates multiple targets (fan-out), each activation
    receives a FanOutTag.  Downstream convergence workers track these tags
    to determine when all parallel branches have reached them.
    """

    fan_out_id: str  # Unique ID for this fan-out event
    fan_out_source: str  # Node that performed the fan-out
    branches: frozenset[str]  # All target node IDs in this fan-out
    via_branch: str  # Which branch this activation passed through


@dataclass
class FanOutTracker:
    """Per fan-out group, tracked by the target worker."""

    fan_out_id: str
    branches: frozenset[str]
    reached: set[str] = field(default_factory=set)

    @property
    def is_complete(self) -> bool:
        return self.reached == self.branches


@dataclass
class Activation:
    """Payload sent from a completed source to a target worker."""

    source_id: str
    target_id: str
    edge_id: str
    edge: EdgeSpec
    mapped_inputs: dict[str, Any]
    fan_out_tags: list[FanOutTag] = field(default_factory=list)


@dataclass
class WorkerCompletion:
    """Payload in WORKER_COMPLETED event."""

    worker_id: str
    success: bool
    output: dict[str, Any]
    tokens_used: int = 0
    latency_ms: int = 0
    conversation: Any = None  # NodeConversation for continuous mode
    activations: list[Activation] = field(default_factory=list)


@dataclass
class RetryState:
    attempt: int = 0
    max_retries: int = 3
    is_event_loop: bool = False


@dataclass
class GraphContext:
    """Shared state for one graph execution run.

    Consolidates the 20+ constructor params on ``GraphExecutor.__init__``
    into a single object shared by reference across all workers.
    """

    graph: GraphSpec
    goal: Goal
    buffer: DataBuffer
    runtime: Runtime
    llm: Any  # LLMProvider
    tools: list[Any]  # list[Tool]
    tool_executor: Any  # Callable
    event_bus: Any  # GraphScopedEventBus
    execution_id: str
    stream_id: str
    run_id: str
    storage_path: Any  # Path | None
    runtime_logger: Any = None
    node_registry: dict[str, NodeProtocol] = field(default_factory=dict)
    node_spec_registry: dict[str, NodeSpec] = field(default_factory=dict)
    # Parallel execution config
    parallel_config: Any = None  # ParallelExecutionConfig | None
    # Continuous mode
    is_continuous: bool = False
    continuous_conversation: Any = None
    cumulative_tools: list[Any] = field(default_factory=list)
    cumulative_tool_names: set[str] = field(default_factory=set)
    cumulative_output_keys: list[str] = field(default_factory=list)
    # Accounts / skills / dynamic providers
    accounts_prompt: str = ""
    accounts_data: list[dict] | None = None
    tool_provider_map: dict[str, str] | None = None
    skills_catalog_prompt: str = ""
    protocols_prompt: str = ""
    skill_dirs: list[str] = field(default_factory=list)
    context_warn_ratio: float | None = None
    batch_init_nudge: str | None = None
    dynamic_tools_provider: Any = None
    dynamic_prompt_provider: Any = None
    iteration_metadata_provider: Any = None
    # Loop config for EventLoopNode creation
    loop_config: dict[str, Any] = field(default_factory=dict)
    # Thread-safe execution state
    path: list[str] = field(default_factory=list)
    node_visit_counts: dict[str, int] = field(default_factory=dict)
    _path_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _visits_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# ---------------------------------------------------------------------------
# WorkerAgent
# ---------------------------------------------------------------------------


class WorkerAgent:
    """First-class autonomous worker for one node in the graph.

    Lifecycle:
        PENDING  – waiting for activations
        RUNNING  – executing the node
        COMPLETED – finished successfully, activations published
        FAILED   – failed after retries exhausted
    """

    def __init__(
        self,
        node_spec: NodeSpec,
        graph_context: GraphContext,
    ) -> None:
        self.node_spec = node_spec
        self._gc = graph_context

        # Edge topology (resolved at construction, immutable)
        self.incoming_edges: list[EdgeSpec] = graph_context.graph.get_incoming_edges(node_spec.id)
        self.outgoing_edges: list[EdgeSpec] = graph_context.graph.get_outgoing_edges(node_spec.id)

        # Lifecycle
        self.lifecycle: WorkerLifecycle = WorkerLifecycle.PENDING
        self._task: asyncio.Task | None = None

        # Retry state
        self.retry_state = RetryState(
            max_retries=node_spec.max_retries,
            is_event_loop=node_spec.node_type == "event_loop",
        )

        # Activation tracking
        self._inherited_fan_out_tags: list[FanOutTag] = []
        self._active_fan_outs: dict[str, FanOutTracker] = {}
        self._received_activations: list[Activation] = []
        self._has_been_activated = False

        # Pause support
        self._pause_event: asyncio.Event = asyncio.Event()
        self._pause_event.set()  # Not paused by default

        # Validator
        self._validator = OutputValidator()

        # Node implementation (lazy)
        self._node_impl: NodeProtocol | None = None

        # Metrics for this worker
        self._tokens_used: int = 0
        self._latency_ms: int = 0

    # ------------------------------------------------------------------
    # Public activation interface
    # ------------------------------------------------------------------

    def activate(self, inherited_tags: list[FanOutTag] | None = None) -> None:
        """Activate this worker — launch execution as an asyncio.Task."""
        if self.lifecycle != WorkerLifecycle.PENDING:
            return

        self._inherited_fan_out_tags = inherited_tags or []
        self._has_been_activated = True
        self.lifecycle = WorkerLifecycle.RUNNING
        self._task = asyncio.ensure_future(self._execute_self())

    def receive_activation(self, activation: Activation) -> None:
        """Receive an activation from an upstream worker.

        Called by GraphExecutor when routing a WORKER_COMPLETED event's
        activations to their target workers.
        """
        if self.lifecycle != WorkerLifecycle.PENDING:
            return

        self._received_activations.append(activation)

        # Update fan-out trackers from this activation's tags
        for tag in activation.fan_out_tags:
            if tag.fan_out_id not in self._active_fan_outs:
                self._active_fan_outs[tag.fan_out_id] = FanOutTracker(
                    fan_out_id=tag.fan_out_id,
                    branches=tag.branches,
                )
            self._active_fan_outs[tag.fan_out_id].reached.add(tag.via_branch)

    def check_readiness(self) -> bool:
        """Check if all fan-out groups have been satisfied."""
        if self._has_been_activated:
            return True
        if not self._active_fan_outs:
            # No fan-out tracking — ready on first activation
            return bool(self._received_activations)
        return all(t.is_complete for t in self._active_fan_outs.values())

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute_self(self) -> None:
        """Main execution loop: run node, handle retries, publish result."""
        gc = self._gc
        node_spec = self.node_spec

        # Write all mapped inputs from received activations to buffer
        for activation in self._received_activations:
            for key, value in activation.mapped_inputs.items():
                gc.buffer.write(key, value, validate=False)

        # Clear stale nullable outputs on re-visit
        async with gc._visits_lock:
            visit_count = gc.node_visit_counts.get(node_spec.id, 0) + 1
            gc.node_visit_counts[node_spec.id] = visit_count

        if visit_count > 1:
            nullable_keys = getattr(node_spec, "nullable_output_keys", None) or []
            for key in nullable_keys:
                if gc.buffer.read(key) is not None:
                    gc.buffer.write(key, None, validate=False)

        # Continuous mode: accumulate tools and output keys
        if gc.is_continuous and node_spec.tools:
            for t in gc.tools:
                if t.name in node_spec.tools and t.name not in gc.cumulative_tool_names:
                    gc.cumulative_tools.append(t)
                    gc.cumulative_tool_names.add(t.name)
        if gc.is_continuous and node_spec.output_keys:
            for k in node_spec.output_keys:
                if k not in gc.cumulative_output_keys:
                    gc.cumulative_output_keys.append(k)

        # Append to execution path
        async with gc._path_lock:
            gc.path.append(node_spec.id)

        # Get node implementation
        node_impl = self._get_node_implementation()

        # Build context
        ctx = self._build_node_context()

        # Execute with retry
        result = await self._execute_with_retries(node_impl, ctx)

        # Handle result
        if result.success:
            # Validate and write outputs
            self._write_outputs(result)

            # Evaluate outgoing edges
            activations = await self._evaluate_outgoing_edges(result)

            # Publish completion
            self.lifecycle = WorkerLifecycle.COMPLETED
            completion = WorkerCompletion(
                worker_id=node_spec.id,
                success=True,
                output=result.output,
                tokens_used=result.tokens_used,
                latency_ms=result.latency_ms,
                conversation=result.conversation,
                activations=activations,
            )
            await self._publish_completion(completion)
        else:
            self.lifecycle = WorkerLifecycle.FAILED
            await self._publish_failure(result.error or "Unknown error")

    async def _execute_with_retries(
        self, node_impl: NodeProtocol, ctx: NodeContext
    ) -> NodeResult:
        """Execute node with exponential backoff retry."""
        gc = self._gc
        max_retries = 0 if self.retry_state.is_event_loop else self.retry_state.max_retries

        for attempt in range(max_retries + 1):
            # Check pause
            await self._pause_event.wait()

            ctx.attempt = attempt + 1
            start = time.monotonic()

            try:
                result = await node_impl.execute(ctx)
                result.latency_ms = int((time.monotonic() - start) * 1000)

                if result.success:
                    return result

                # Failure
                if attempt < max_retries:
                    delay = 1.0 * (2**attempt)
                    logger.warning(
                        "Worker %s failed (attempt %d/%d), retrying in %.1fs: %s",
                        self.node_spec.id,
                        attempt + 1,
                        max_retries + 1,
                        delay,
                        result.error,
                    )
                    # Emit retry event
                    if gc.event_bus:
                        await gc.event_bus.emit_node_retry(
                            stream_id=gc.stream_id,
                            node_id=self.node_spec.id,
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            execution_id=gc.execution_id,
                        )
                    await asyncio.sleep(delay)
                    continue
                else:
                    return result

            except Exception as exc:
                if attempt < max_retries:
                    delay = 1.0 * (2**attempt)
                    logger.warning(
                        "Worker %s raised %s (attempt %d/%d), retrying in %.1fs",
                        self.node_spec.id,
                        type(exc).__name__,
                        attempt + 1,
                        max_retries + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                return NodeResult(success=False, error=str(exc))

        return NodeResult(success=False, error="Max retries exceeded")

    # ------------------------------------------------------------------
    # Edge evaluation (source-side)
    # ------------------------------------------------------------------

    async def _evaluate_outgoing_edges(
        self, result: NodeResult
    ) -> list[Activation]:
        """Evaluate outgoing edges and create activations for downstream.

        Same logic as current _get_all_traversable_edges() plus
        priority filtering for CONDITIONAL edges.
        """
        gc = self._gc
        edges = gc.graph.get_outgoing_edges(self.node_spec.id)

        traversable: list[EdgeSpec] = []
        for edge in edges:
            target_spec = gc.graph.get_node(edge.target)
            if await edge.should_traverse(
                source_success=result.success,
                source_output=result.output,
                buffer_data=gc.buffer.read_all(),
                llm=gc.llm,
                goal=gc.goal,
                source_node_name=self.node_spec.name,
                target_node_name=target_spec.name if target_spec else edge.target,
            ):
                traversable.append(edge)

        # Priority filtering for CONDITIONAL edges
        if len(traversable) > 1:
            conditionals = [e for e in traversable if e.condition == EdgeCondition.CONDITIONAL]
            if len(conditionals) > 1:
                max_prio = max(e.priority for e in conditionals)
                traversable = [
                    e
                    for e in traversable
                    if e.condition != EdgeCondition.CONDITIONAL or e.priority == max_prio
                ]

        # Build activations
        is_fan_out = len(traversable) > 1
        fan_out_id = f"{self.node_spec.id}_{uuid.uuid4().hex[:8]}" if is_fan_out else None

        activations: list[Activation] = []
        for edge in traversable:
            mapped = edge.map_inputs(result.output, gc.buffer.read_all())

            # Build fan-out tags: inherited + new
            tags = list(self._inherited_fan_out_tags)
            if is_fan_out:
                tags.append(
                    FanOutTag(
                        fan_out_id=fan_out_id,
                        fan_out_source=self.node_spec.id,
                        branches=frozenset(e.target for e in traversable),
                        via_branch=edge.target,
                    )
                )

            activations.append(
                Activation(
                    source_id=self.node_spec.id,
                    target_id=edge.target,
                    edge_id=edge.id,
                    edge=edge,
                    mapped_inputs=mapped,
                    fan_out_tags=tags,
                )
            )

        if traversable:
            logger.info(
                "Worker %s → %d outgoing activation(s)%s",
                self.node_spec.id,
                len(activations),
                f" (fan-out: {[a.target_id for a in activations]})" if is_fan_out else "",
            )

        return activations

    # ------------------------------------------------------------------
    # Output handling
    # ------------------------------------------------------------------

    def _write_outputs(self, result: NodeResult) -> None:
        """Validate and write node outputs to buffer."""
        gc = self._gc
        node_spec = self.node_spec

        # Event loop nodes skip executor-level validation (judge is the authority)
        if node_spec.node_type != "event_loop":
            errors = self._validator.validate_all(
                output=result.output,
                output_keys=node_spec.output_keys,
                nullable_keys=getattr(node_spec, "nullable_output_keys", []) or [],
                output_schema=getattr(node_spec, "output_schema", None),
                output_model=getattr(node_spec, "output_model", None),
            )
            if errors:
                logger.warning("Worker %s output validation warnings: %s", node_spec.id, errors)

        # Write all output keys to buffer
        for key in node_spec.output_keys:
            value = result.output.get(key)
            if value is not None:
                gc.buffer.write(key, value, validate=False)

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    def _get_node_implementation(self) -> NodeProtocol:
        """Get or create node implementation."""
        gc = self._gc
        if self._node_impl is not None:
            return self._node_impl

        # Check shared registry first
        if self.node_spec.id in gc.node_registry:
            self._node_impl = gc.node_registry[self.node_spec.id]
            return self._node_impl

        # Auto-create EventLoopNode
        if self.node_spec.node_type in ("event_loop", "gcu"):
            from framework.graph.event_loop_node import EventLoopNode
            from framework.graph.event_loop.types import LoopConfig

            conv_store = None
            if gc.storage_path:
                from framework.storage.conversation_store import FileConversationStore

                conv_store = FileConversationStore(base_path=gc.storage_path / "conversations")

            spillover = str(gc.storage_path / "data") if gc.storage_path else None
            lc = gc.loop_config
            default_max_iter = 100 if self.node_spec.client_facing else 50

            node = EventLoopNode(
                event_bus=gc.event_bus,
                judge=None,
                config=LoopConfig(
                    max_iterations=lc.get("max_iterations", default_max_iter),
                    max_tool_calls_per_turn=lc.get("max_tool_calls_per_turn", 30),
                    tool_call_overflow_margin=lc.get("tool_call_overflow_margin", 0.5),
                    stall_detection_threshold=lc.get("stall_detection_threshold", 3),
                    max_context_tokens=lc.get(
                        "max_context_tokens",
                        _default_max_context_tokens(),
                    ),
                    max_tool_result_chars=lc.get("max_tool_result_chars", 30_000),
                    spillover_dir=spillover,
                    hooks=lc.get("hooks", {}),
                ),
                tool_executor=gc.tool_executor,
                conversation_store=conv_store,
            )
            gc.node_registry[self.node_spec.id] = node
            self._node_impl = node
            return node

        raise RuntimeError(
            f"No implementation for node '{self.node_spec.id}' "
            f"(type: {self.node_spec.node_type})"
        )

    def _build_node_context(self) -> NodeContext:
        """Build NodeContext for this worker's execution."""
        gc = self._gc
        node_spec = self.node_spec

        # Filter tools
        if gc.is_continuous and gc.cumulative_tools:
            available_tools = list(gc.cumulative_tools)
        else:
            available_tools = []
            if node_spec.tools:
                available_tools = [t for t in gc.tools if t.name in node_spec.tools]

        # Scoped buffer
        read_keys = list(node_spec.input_keys)
        write_keys = list(node_spec.output_keys)
        if read_keys or write_keys:
            from framework.skills.defaults import DATA_BUFFER_KEYS as _skill_keys

            existing_underscore = [k for k in gc.buffer._data if k.startswith("_")]
            extra_keys = set(_skill_keys) | set(existing_underscore)
            for k in extra_keys:
                if read_keys and k not in read_keys:
                    read_keys.append(k)
                if write_keys and k not in write_keys:
                    write_keys.append(k)

        scoped_buffer = gc.buffer.with_permissions(read_keys=read_keys, write_keys=write_keys)

        # Per-node accounts prompt
        node_accounts_prompt = gc.accounts_prompt
        if gc.accounts_data and gc.tool_provider_map:
            from framework.graph.prompt_composer import build_accounts_prompt

            node_accounts_prompt = build_accounts_prompt(
                gc.accounts_data,
                gc.tool_provider_map,
                node_tool_names=node_spec.tools,
            ) or gc.accounts_prompt

        # Input data from buffer
        input_data: dict[str, Any] = {}
        for key in node_spec.input_keys:
            val = gc.buffer.read(key)
            if val is not None:
                input_data[key] = val

        # Continuous mode: thread conversation
        inherited_conversation = None
        if gc.is_continuous and gc.continuous_conversation:
            inherited_conversation = gc.continuous_conversation

        return NodeContext(
            runtime=gc.runtime,
            node_id=node_spec.id,
            node_spec=node_spec,
            buffer=scoped_buffer,
            input_data=input_data,
            llm=gc.llm,
            available_tools=available_tools,
            goal_context=gc.goal.to_prompt_context(),
            goal=gc.goal,
            max_tokens=gc.graph.max_tokens,
            runtime_logger=gc.runtime_logger,
            pause_event=self._pause_event,
            continuous_mode=gc.is_continuous,
            inherited_conversation=inherited_conversation,
            cumulative_output_keys=list(gc.cumulative_output_keys) if gc.is_continuous else [],
            accounts_prompt=node_accounts_prompt,
            identity_prompt=getattr(gc.graph, "identity_prompt", "") or "",
            execution_id=gc.execution_id,
            run_id=gc.run_id,
            stream_id=gc.stream_id,
            node_registry=gc.node_spec_registry,
            all_tools=list(gc.tools),
            shared_node_registry=gc.node_registry,
            dynamic_tools_provider=gc.dynamic_tools_provider,
            dynamic_prompt_provider=gc.dynamic_prompt_provider,
            iteration_metadata_provider=gc.iteration_metadata_provider,
            skills_catalog_prompt=gc.skills_catalog_prompt,
            protocols_prompt=gc.protocols_prompt,
            skill_dirs=list(gc.skill_dirs),
            default_skill_warn_ratio=gc.context_warn_ratio,
            default_skill_batch_nudge=gc.batch_init_nudge,
        )

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    async def _publish_completion(self, completion: WorkerCompletion) -> None:
        """Publish WORKER_COMPLETED event via the graph-scoped event bus."""
        gc = self._gc
        if not gc.event_bus:
            return

        # Serialize activations to dicts for event data
        activations_data = []
        for act in completion.activations:
            activations_data.append({
                "source_id": act.source_id,
                "target_id": act.target_id,
                "edge_id": act.edge_id,
                "mapped_inputs": act.mapped_inputs,
                "fan_out_tags": [
                    {
                        "fan_out_id": t.fan_out_id,
                        "fan_out_source": t.fan_out_source,
                        "branches": list(t.branches),
                        "via_branch": t.via_branch,
                    }
                    for t in act.fan_out_tags
                ],
            })

        await gc.event_bus.emit_worker_completed(
            stream_id=gc.stream_id,
            node_id=self.node_spec.id,
            worker_id=self.node_spec.id,
            success=completion.success,
            output=completion.output,
            activations=activations_data,
            execution_id=gc.execution_id,
            tokens_used=completion.tokens_used,
            latency_ms=completion.latency_ms,
            conversation=completion.conversation,
        )

        # Update continuous mode state
        if gc.is_continuous and completion.conversation is not None:
            gc.continuous_conversation = completion.conversation
            self._apply_continuous_transition()

    async def _publish_failure(self, error: str) -> None:
        """Publish WORKER_FAILED event."""
        gc = self._gc
        if not gc.event_bus:
            return

        await gc.event_bus.emit_worker_failed(
            stream_id=gc.stream_id,
            node_id=self.node_spec.id,
            worker_id=self.node_spec.id,
            error=error,
            execution_id=gc.execution_id,
        )

    def _apply_continuous_transition(self) -> None:
        """Apply continuous mode conversation threading for the next node.

        Uses existing prompt_composer functions for onion-model system
        prompt composition, transition markers, and phase-boundary compaction.
        """
        gc = self._gc
        if not gc.is_continuous or not gc.continuous_conversation:
            return

        # Find the next node from outgoing edges (best guess from current state)
        # The actual next node is determined at activation time, but for continuous
        # mode prompt composition we need it now.
        next_node_id = None
        for edge in self.outgoing_edges:
            if edge.condition in (EdgeCondition.ALWAYS, EdgeCondition.ON_SUCCESS):
                next_node_id = edge.target
                break
        if not next_node_id:
            return

        next_spec = gc.graph.get_node(next_node_id)
        if not next_spec or next_spec.node_type != "event_loop":
            return

        from framework.graph.prompt_composer import (
            EXECUTION_SCOPE_PREAMBLE,
            build_accounts_prompt,
            build_narrative,
            build_transition_marker,
            compose_system_prompt,
        )

        # Layer 2: narrative
        narrative = build_narrative(gc.buffer, gc.path, gc.graph)

        # Per-node accounts prompt
        _node_accounts = gc.accounts_prompt or None
        if gc.accounts_data and gc.tool_provider_map:
            _node_accounts = (
                build_accounts_prompt(
                    gc.accounts_data,
                    gc.tool_provider_map,
                    node_tool_names=next_spec.tools,
                )
                or None
            )

        # Compose system prompt (Layer 1 + 2 + 3 + accounts)
        _focus = next_spec.system_prompt
        if next_spec.output_keys and _focus:
            _focus = f"{EXECUTION_SCOPE_PREAMBLE}\n\n{_focus}"
        new_system = compose_system_prompt(
            identity_prompt=getattr(gc.graph, "identity_prompt", None),
            focus_prompt=_focus,
            narrative=narrative,
            accounts_prompt=_node_accounts,
        )
        gc.continuous_conversation.update_system_prompt(new_system)

        # Insert transition marker
        data_dir = str(gc.storage_path / "data") if gc.storage_path else None
        marker = build_transition_marker(
            previous_node=self.node_spec,
            next_node=next_spec,
            buffer=gc.buffer,
            cumulative_tool_names=sorted(gc.cumulative_tool_names),
            data_dir=data_dir,
        )
        # We can't await here (sync method), so schedule it
        # The continuous conversation threading will be done properly in the
        # GraphExecutor's event handler where we have async context.

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    @property
    def is_terminal(self) -> bool:
        return self.node_spec.id in (self._gc.graph.terminal_nodes or [])

    @property
    def is_entry(self) -> bool:
        return len(self.incoming_edges) == 0


def _default_max_context_tokens() -> int:
    """Resolve max_context_tokens from global config, falling back to 32000."""
    try:
        from framework.config import get_max_context_tokens  # type: ignore[import-untyped]

        return get_max_context_tokens()
    except Exception:
        return 32_000
