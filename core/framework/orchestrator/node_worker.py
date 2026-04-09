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

from framework.orchestrator.context import GraphContext, build_node_context_from_graph_context
from framework.orchestrator.edge import EdgeCondition, EdgeSpec
from framework.orchestrator.node import (
    NodeContext,
    NodeProtocol,
    NodeResult,
    NodeSpec,
)
from framework.orchestrator.validator import OutputValidator

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


# ---------------------------------------------------------------------------
# WorkerAgent
# ---------------------------------------------------------------------------


class NodeWorker:
    """First-class autonomous worker for one node in the graph.

    Lifecycle:
        PENDING - waiting for activations
        RUNNING - executing the node
        COMPLETED- finished successfully, activations published
        FAILED  - failed after retries exhausted
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
        # _run_gate controls whether worker execution may proceed.
        # _pause_requested mirrors the pause-request semantics expected by
        # EventLoopNode, where is_set() means "pause requested".
        self._run_gate: asyncio.Event = asyncio.Event()
        self._run_gate.set()  # Not paused by default
        self._pause_requested: asyncio.Event = asyncio.Event()

        # Validator
        self._validator = OutputValidator()

        # Node implementation (lazy)
        self._node_impl: NodeProtocol | None = None

        # Metrics for this worker
        self._tokens_used: int = 0
        self._latency_ms: int = 0

        # Last execution result (accessible by polling executor)
        self._last_result: NodeResult | None = None
        self._last_activations: list[Activation] = []

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

        # Update fan-out trackers from this activation's tags.
        # Skip tags where this worker IS the via_branch — those tags exist
        # for downstream convergence tracking, not for gating this worker.
        for tag in activation.fan_out_tags:
            if tag.via_branch == self.node_spec.id:
                continue
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

    def reset_for_revisit(self) -> None:
        """Reset a completed worker so it can execute again (feedback loops).

        Preserves the node implementation (cached) but clears lifecycle,
        activation, and result state.
        """
        self.lifecycle = WorkerLifecycle.PENDING
        self._inherited_fan_out_tags = []
        self._active_fan_outs = {}
        self._received_activations = []
        self._has_been_activated = False
        self._task = None
        self._last_result = None
        self._last_activations = []
        self._tokens_used = 0
        self._latency_ms = 0

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute_self(self) -> None:
        """Main execution loop: run node, handle retries, publish result."""
        gc = self._gc
        node_spec = self.node_spec
        try:
            # Write all mapped inputs from received activations to buffer
            for activation in self._received_activations:
                for key, value in activation.mapped_inputs.items():
                    gc.buffer.write(key, value, validate=False)

            # Increment visit count (always, even if skipped)
            async with gc._visits_lock:
                visit_count = gc.node_visit_counts.get(node_spec.id, 0) + 1
                gc.node_visit_counts[node_spec.id] = visit_count

            # Check max_node_visits — skip execution but still propagate edges
            if node_spec.max_node_visits > 0 and visit_count > node_spec.max_node_visits:
                logger.info(
                    "Worker %s: visit %d exceeds max_node_visits=%d, skipping",
                    node_spec.id,
                    visit_count,
                    node_spec.max_node_visits,
                )
                # Build a synthetic success result from current buffer state
                existing_output: dict[str, Any] = {}
                for key in node_spec.output_keys:
                    val = gc.buffer.read(key)
                    if val is not None:
                        existing_output[key] = val

                result = NodeResult(success=True, output=existing_output)

                # Evaluate outgoing edges so the cycle continues
                activations = await self._evaluate_outgoing_edges(result)

                self.lifecycle = WorkerLifecycle.COMPLETED
                self._last_result = result
                self._last_activations = activations
                return

            # Clear stale nullable outputs on re-visit
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
                self._last_result = result
                self._last_activations = activations
                completion = WorkerCompletion(
                    worker_id=node_spec.id,
                    success=True,
                    output=result.output,
                    tokens_used=result.tokens_used,
                    latency_ms=result.latency_ms,
                    conversation=result.conversation,
                    activations=activations,
                )
                if gc.is_continuous and completion.conversation is not None:
                    gc.continuous_conversation = completion.conversation
                    await self._apply_continuous_transition(completion.activations)
                await self._publish_completion(completion)
            else:
                # Evaluate outgoing edges even on failure (ON_FAILURE edges)
                activations = await self._evaluate_outgoing_edges(result)

                self.lifecycle = WorkerLifecycle.FAILED
                self._last_result = result
                self._last_activations = activations
                await self._publish_failure(result.error or "Unknown error")
        except Exception as exc:
            error = str(exc) or type(exc).__name__
            logger.exception("Worker %s crashed during execution", node_spec.id)
            self.lifecycle = WorkerLifecycle.FAILED
            self._last_result = NodeResult(success=False, error=error)
            self._last_activations = []
            await self._publish_failure(error)

    async def _execute_with_retries(self, node_impl: NodeProtocol, ctx: NodeContext) -> NodeResult:
        """Execute node with exponential backoff retry."""
        gc = self._gc
        # Only skip retries for actual EventLoopNode instances (they handle
        # retries internally).  Custom NodeProtocol impls registered via
        # register_node should be retried by the executor.
        from framework.agent_loop.agent_loop import AgentLoop as _ELN

        if isinstance(node_impl, _ELN):
            max_retries = 0
        else:
            max_retries = self.retry_state.max_retries

        total_attempts = max(1, max_retries)
        for attempt in range(total_attempts):
            # Check pause
            await self._run_gate.wait()

            ctx.attempt = attempt + 1
            start = time.monotonic()

            try:
                result = await node_impl.execute(ctx)
                result.latency_ms = int((time.monotonic() - start) * 1000)

                if result.success:
                    return result

                # Failure
                if attempt + 1 < total_attempts:
                    gc.retry_counts[self.node_spec.id] = (
                        gc.retry_counts.get(self.node_spec.id, 0) + 1
                    )
                    gc.nodes_with_retries.add(self.node_spec.id)
                    delay = 1.0 * (2**attempt)
                    logger.warning(
                        "Worker %s failed (attempt %d/%d), retrying in %.1fs: %s",
                        self.node_spec.id,
                        attempt + 1,
                        max_retries,
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
                    return NodeResult(
                        success=False,
                        error=f"failed after {attempt + 1} attempts: {result.error}",
                    )

            except Exception as exc:
                if attempt + 1 < total_attempts:
                    gc.retry_counts[self.node_spec.id] = (
                        gc.retry_counts.get(self.node_spec.id, 0) + 1
                    )
                    gc.nodes_with_retries.add(self.node_spec.id)
                    delay = 1.0 * (2**attempt)
                    logger.warning(
                        "Worker %s raised %s (attempt %d/%d), retrying in %.1fs",
                        self.node_spec.id,
                        type(exc).__name__,
                        attempt + 1,
                        max(1, max_retries),
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                return NodeResult(
                    success=False,
                    error=f"failed after {attempt + 1} attempts: {exc}",
                )

        return NodeResult(
            success=False,
            error=f"failed after {max(1, max_retries)} attempts",
        )

    # ------------------------------------------------------------------
    # Edge evaluation (source-side)
    # ------------------------------------------------------------------

    async def _evaluate_outgoing_edges(self, result: NodeResult) -> list[Activation]:
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

        # When parallel execution is disabled, follow first match only (sequential)
        if not gc.enable_parallel_execution and len(traversable) > 1:
            traversable = traversable[:1]

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

        # Determine if this worker is a fan-out branch
        is_fanout_branch = any(
            tag.via_branch == node_spec.id for tag in self._inherited_fan_out_tags
        )

        # Collect keys to write: declared output_keys + any extra output items
        # (for fan-out branches, all output items need conflict checking)
        keys_to_write: set[str] = set(node_spec.output_keys)
        if is_fanout_branch:
            keys_to_write |= set(result.output.keys())

        # Write all keys to buffer
        for key in keys_to_write:
            value = result.output.get(key)
            if value is not None:
                if is_fanout_branch:
                    conflict_strategy = (
                        getattr(gc.parallel_config, "buffer_conflict_strategy", "last_wins")
                        if gc.parallel_config
                        else "last_wins"
                    )
                    prior_worker = gc._fanout_written_keys.get(key)
                    if prior_worker and prior_worker != node_spec.id:
                        if conflict_strategy == "error":
                            raise RuntimeError(
                                f"Buffer write failed (conflict): key '{key}' already written "
                                f"by worker '{prior_worker}', "
                                f"conflicting write from '{node_spec.id}'"
                            )
                        elif conflict_strategy == "first_wins":
                            logger.debug(
                                "Skipping write to '%s' (first_wins: already set by %s)",
                                key,
                                prior_worker,
                            )
                            continue
                        else:
                            # last_wins: log and overwrite
                            logger.debug(
                                "Key '%s' overwritten (last_wins: %s -> %s)",
                                key,
                                prior_worker,
                                node_spec.id,
                            )
                    gc._fanout_written_keys[key] = node_spec.id
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
        if self.node_spec.node_type == "event_loop":
            from framework.agent_loop.internals.types import LoopConfig
            from framework.agent_loop.agent_loop import AgentLoop
            from framework.orchestrator.node import warn_if_deprecated_client_facing

            conv_store = None
            if gc.storage_path:
                from framework.storage.conversation_store import FileConversationStore

                conv_store = FileConversationStore(base_path=gc.storage_path / "conversations")

            spillover = str(gc.storage_path / "data") if gc.storage_path else None
            lc = gc.loop_config
            warn_if_deprecated_client_facing(self.node_spec)
            default_max_iter = 100 if self.node_spec.supports_direct_user_io() else 50

            node = AgentLoop(
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
            f"No implementation for node '{self.node_spec.id}' (type: {self.node_spec.node_type})"
        )

    def _build_node_context(self) -> NodeContext:
        """Build NodeContext for this worker's execution."""
        return build_node_context_from_graph_context(
            self._gc,
            node_spec=self.node_spec,
            pause_event=self._pause_requested,
        )

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    async def _publish_completion(self, completion: WorkerCompletion) -> None:
        """Publish WORKER_COMPLETED event via the graph-scoped event bus."""
        gc = self._gc
        if not gc.event_bus:
            return
        if not hasattr(gc.event_bus, "emit_worker_completed"):
            return

        # Serialize activations to dicts for event data
        activations_data = []
        for act in completion.activations:
            activations_data.append(
                {
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
                }
            )

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

    async def _publish_failure(self, error: str) -> None:
        """Publish WORKER_FAILED event."""
        gc = self._gc
        if not gc.event_bus:
            return
        if not hasattr(gc.event_bus, "emit_worker_failed"):
            return

        await gc.event_bus.emit_worker_failed(
            stream_id=gc.stream_id,
            node_id=self.node_spec.id,
            worker_id=self.node_spec.id,
            error=error,
            execution_id=gc.execution_id,
        )

    async def _apply_continuous_transition(self, activations: list[Activation]) -> None:
        """Apply continuous mode conversation threading for the next node.

        This prepares the inherited conversation before the completion event
        is published so downstream workers receive a fully updated thread.
        """
        gc = self._gc
        if not gc.is_continuous or not gc.continuous_conversation:
            return

        next_node_id = next((activation.target_id for activation in activations), None)
        if not next_node_id:
            return

        next_spec = gc.graph.get_node(next_node_id)
        if not next_spec or next_spec.node_type != "event_loop":
            return

        from framework.orchestrator.prompting import (
            TransitionSpec,
            build_narrative,
            build_system_prompt_for_node_context,
            build_transition_message,
        )

        narrative = build_narrative(gc.buffer, gc.path, gc.graph)
        next_ctx = build_node_context_from_graph_context(
            gc,
            node_spec=next_spec,
            pause_event=self._pause_requested,
            inherited_conversation=gc.continuous_conversation,
            narrative=narrative,
        )
        gc.continuous_conversation.update_system_prompt(
            build_system_prompt_for_node_context(next_ctx)
        )
        gc.continuous_conversation.set_current_phase(next_spec.id)

        buffer_items, data_files = self._prepare_transition_payload()
        marker = build_transition_message(
            TransitionSpec(
                previous_name=self.node_spec.name,
                previous_description=self.node_spec.description,
                next_name=next_spec.name,
                next_description=next_spec.description,
                next_output_keys=tuple(next_spec.output_keys or ()),
                buffer_items=buffer_items,
                cumulative_tool_names=tuple(sorted(gc.cumulative_tool_names)),
                data_files=tuple(data_files),
            )
        )
        await gc.continuous_conversation.add_user_message(
            marker,
            is_transition_marker=True,
        )

    def _prepare_transition_payload(self) -> tuple[dict[str, str], list[str]]:
        """Build transition marker data and spill oversized values when possible."""
        import json
        from pathlib import Path

        gc = self._gc
        data_dir = Path(gc.storage_path / "data") if gc.storage_path else None
        buffer_items: dict[str, str] = {}

        for key, value in gc.buffer.read_all().items():
            if value is None:
                continue
            val_str = str(value)
            if len(val_str) > 300 and data_dir is not None:
                data_dir.mkdir(parents=True, exist_ok=True)
                ext = ".json" if isinstance(value, (dict, list)) else ".txt"
                filename = f"output_{key}{ext}"
                file_path = data_dir / filename
                try:
                    write_content = (
                        json.dumps(value, indent=2, ensure_ascii=False)
                        if isinstance(value, (dict, list))
                        else str(value)
                    )
                    file_path.write_text(write_content, encoding="utf-8")
                    file_size = file_path.stat().st_size
                    buffer_items[key] = (
                        f"[Saved to '{filename}' ({file_size:,} bytes). "
                        f"Use read_file(path='{filename}') to access.]"
                    )
                    continue
                except Exception:
                    pass

            buffer_items[key] = val_str[:300] + "..." if len(val_str) > 300 else val_str

        data_files: list[str] = []
        if data_dir is not None and data_dir.exists():
            data_files = [
                f"{entry.name} ({entry.stat().st_size:,} bytes)"
                for entry in sorted(data_dir.iterdir())
                if entry.is_file()
            ]

        return buffer_items, data_files

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def pause(self) -> None:
        self._pause_requested.set()
        self._run_gate.clear()

    def resume(self) -> None:
        self._pause_requested.clear()
        self._run_gate.set()

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
