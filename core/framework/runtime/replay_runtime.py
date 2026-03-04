"""Deterministic replay infrastructure for Hive agent sessions (issue #4669).

Loads cached LLM responses and tool results from a prior session's L3
tool_logs.jsonl and injects them into a new execution in place of live
LLM/tool calls, enabling root-cause analysis of failed runs.

Architecture
------------
ReplayCache
    Parses L3 NodeStepLog records into two lookup dicts keyed by
    (node_id, step_index) and (node_id, step_index, tool_call_position).

ReplayInterceptor
    Single stateful object shared by both wrapper surfaces. Tracks
    which node is executing and which step/tool-call we are at so that
    both wrappers stay in sync without external coordination.

ReplayLLMProvider
    Wraps LLMProvider. On each stream()/acomplete() call, asks the
    interceptor for a cached response. On hit, returns synthetic events /
    LLMResponse from cache. On miss, delegates to the inner provider.

make_replay_tool_executor
    Returns a closure with the same signature as EventLoopNode's
    tool_executor. On each call, asks the interceptor for a cached
    ToolResult. On miss, delegates to the inner callable.

Usage (by GraphExecutor)::

    interceptor = ReplayInterceptor(cache, freeze_llm=True, freeze_tools=True)
    effective_llm = ReplayLLMProvider(self.llm, interceptor)
    effective_tool_executor = make_replay_tool_executor(self.tool_executor, interceptor)
    # Before each node_impl.execute():
    interceptor.set_node(current_node_id)
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import (
    FinishEvent,
    StreamEvent,
    TextDeltaEvent,
    TextEndEvent,
    ToolCallEvent,
)
from framework.runtime.runtime_log_schemas import NodeStepLog
from framework.runtime.runtime_log_store import RuntimeLogStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cached response container
# ---------------------------------------------------------------------------


@dataclass
class CachedLLMResponse:
    """LLM response reconstructed from an L3 NodeStepLog entry."""

    llm_text: str
    """The assistant text the LLM produced in the original run."""

    tool_call_suggestions: list[dict[str, Any]] = field(default_factory=list)
    """Ordered list of tool calls the LLM requested, each a dict with
    keys ``tool_name`` and ``tool_input``.  Replayed as ToolCallEvents
    so EventLoopNode executes the same tools in the same order."""

    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# Cache — built from L3 tool_logs.jsonl
# ---------------------------------------------------------------------------


class ReplayCache:
    """Lookup tables built from a session's L3 NodeStepLog records.

    Two indices are constructed at init time:

    ``llm_cache``
        ``(node_id, step_index)`` → :class:`CachedLLMResponse`

    ``tool_cache``
        ``(node_id, step_index, tool_call_position)`` → cached result str

    Tool calls within a step are disambiguated by *position* (index within
    ``NodeStepLog.tool_calls``), not by name, so multiple calls to the same
    tool within one step are handled correctly.
    """

    def __init__(self, steps: list[NodeStepLog]) -> None:
        self._llm_cache: dict[tuple[str, int], CachedLLMResponse] = {}
        self._tool_cache: dict[tuple[str, int, int], str] = {}
        self._steps_by_node: dict[str, list[NodeStepLog]] = defaultdict(list)

        for step in steps:
            node_id = step.node_id
            idx = step.step_index
            self._steps_by_node[node_id].append(step)

            # LLM cache entry
            suggestions = [
                {"tool_name": tc.tool_name, "tool_input": tc.tool_input}
                for tc in step.tool_calls
            ]
            self._llm_cache[(node_id, idx)] = CachedLLMResponse(
                llm_text=step.llm_text,
                tool_call_suggestions=suggestions,
                input_tokens=step.input_tokens,
                output_tokens=step.output_tokens,
            )

            # Tool cache entries — keyed by position within this step
            for pos, tc in enumerate(step.tool_calls):
                self._tool_cache[(node_id, idx, pos)] = tc.result

    @classmethod
    async def from_session(
        cls,
        session_id: str,
        log_store: RuntimeLogStore,
    ) -> "ReplayCache":
        """Load L3 logs for *session_id* and build the cache.

        Raises :class:`ValueError` if no tool logs are found for the session.
        """
        run_tool_logs = await log_store.load_tool_logs(session_id)
        if run_tool_logs is None or not run_tool_logs.steps:
            raise ValueError(
                f"No L3 tool logs found for session '{session_id}'. "
                "Cannot build replay cache — ensure the session ran at least one node."
            )
        logger.debug(
            "ReplayCache: loaded %d steps from session '%s'",
            len(run_tool_logs.steps),
            session_id,
        )
        return cls(run_tool_logs.steps)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_llm_response(
        self, node_id: str, step_index: int
    ) -> CachedLLMResponse | None:
        """Return cached LLM response or ``None`` on miss."""
        return self._llm_cache.get((node_id, step_index))

    def get_tool_result(
        self, node_id: str, step_index: int, tool_call_position: int
    ) -> str | None:
        """Return cached tool result string or ``None`` on miss."""
        return self._tool_cache.get((node_id, step_index, tool_call_position))

    def get_node_steps(self, node_id: str) -> list[NodeStepLog]:
        """Return all original steps recorded for *node_id*."""
        return list(self._steps_by_node.get(node_id, []))

    @property
    def node_ids(self) -> list[str]:
        """Node IDs present in the cache."""
        return list(self._steps_by_node.keys())

    @property
    def total_llm_entries(self) -> int:
        return len(self._llm_cache)

    @property
    def total_tool_entries(self) -> int:
        return len(self._tool_cache)


# ---------------------------------------------------------------------------
# Interceptor — shared mutable state between the two wrapper surfaces
# ---------------------------------------------------------------------------


class ReplayInterceptor:
    """Single stateful object shared by :class:`ReplayLLMProvider` and the
    tool executor closure produced by :func:`make_replay_tool_executor`.

    GraphExecutor calls :meth:`set_node` before each ``node_impl.execute()``
    call so counters reset correctly at node boundaries.

    Counter protocol
    ~~~~~~~~~~~~~~~~
    * :meth:`on_llm_call` — called once per LLM invocation; increments
      ``_step_index`` and resets ``_tool_call_position``.
    * :meth:`on_tool_call` — called once per tool invocation within the
      current step; increments ``_tool_call_position``.
    """

    def __init__(
        self,
        cache: ReplayCache,
        freeze_llm: bool = True,
        freeze_tools: bool = True,
    ) -> None:
        self._cache = cache
        self._freeze_llm = freeze_llm
        self._freeze_tools = freeze_tools

        self._current_node: str = ""
        self._step_index: int = 0
        self._tool_call_position: int = 0

        # Telemetry counters
        self.llm_hits: int = 0
        self.llm_misses: int = 0
        self.tool_hits: int = 0
        self.tool_misses: int = 0

    def set_node(self, node_id: str) -> None:
        """Reset all per-node counters. Must be called before each node execution."""
        self._current_node = node_id
        self._step_index = 0
        self._tool_call_position = 0
        logger.debug("ReplayInterceptor: entering node '%s'", node_id)

    def on_llm_call(self) -> CachedLLMResponse | None:
        """Query cache for the current (node, step). Advance step counter.

        Returns cached response if ``freeze_llm=True`` and a cache entry
        exists, otherwise ``None`` (signals caller to use the live LLM).
        Side-effect: always increments step_index and resets tool_call_position.
        """
        cached: CachedLLMResponse | None = None
        if self._freeze_llm:
            cached = self._cache.get_llm_response(
                self._current_node, self._step_index
            )
            if cached is not None:
                self.llm_hits += 1
                logger.debug(
                    "ReplayInterceptor: LLM HIT node='%s' step=%d",
                    self._current_node,
                    self._step_index,
                )
            else:
                self.llm_misses += 1
                logger.warning(
                    "ReplayInterceptor: LLM MISS node='%s' step=%d — calling live LLM",
                    self._current_node,
                    self._step_index,
                )
        # Always advance counters regardless of freeze flag / hit-or-miss
        self._step_index += 1
        self._tool_call_position = 0
        return cached

    def on_tool_call(self) -> str | None:
        """Query cache for the current (node, step-1, position). Advance position counter.

        Returns cached result string if ``freeze_tools=True`` and a cache
        entry exists, otherwise ``None`` (signals caller to execute live).
        Side-effect: always increments tool_call_position.
        """
        cached_result: str | None = None
        if self._freeze_tools:
            # step_index was already incremented by on_llm_call, so the
            # current step's cache key uses step_index - 1.
            cached_result = self._cache.get_tool_result(
                self._current_node,
                self._step_index - 1,
                self._tool_call_position,
            )
            if cached_result is not None:
                self.tool_hits += 1
                logger.debug(
                    "ReplayInterceptor: TOOL HIT node='%s' step=%d pos=%d",
                    self._current_node,
                    self._step_index - 1,
                    self._tool_call_position,
                )
            else:
                self.tool_misses += 1
                logger.warning(
                    "ReplayInterceptor: TOOL MISS node='%s' step=%d pos=%d — executing live",
                    self._current_node,
                    self._step_index - 1,
                    self._tool_call_position,
                )
        self._tool_call_position += 1
        return cached_result

    @property
    def total_misses(self) -> int:
        return self.llm_misses + self.tool_misses

    @property
    def total_hits(self) -> int:
        return self.llm_hits + self.tool_hits


# ---------------------------------------------------------------------------
# LLM provider wrapper
# ---------------------------------------------------------------------------


class ReplayLLMProvider(LLMProvider):
    """Wraps an :class:`LLMProvider`; returns cached responses when available.

    All interface methods delegate to ``inner`` except the primary
    generation path (``stream`` / ``acomplete`` / ``complete``), which
    first checks the :class:`ReplayInterceptor`.

    On a cache **hit** the provider synthesises the appropriate response:
    * ``stream()``    — yields TextDeltaEvent → ToolCallEvents → TextEndEvent → FinishEvent
    * ``acomplete()`` — returns LLMResponse with cached content
    * ``complete()``  — returns LLMResponse with cached content (sync)

    On a cache **miss** every call is forwarded to the inner provider.
    """

    def __init__(self, inner: LLMProvider, interceptor: ReplayInterceptor) -> None:
        self._inner = inner
        self._interceptor = interceptor

    # ------------------------------------------------------------------
    # Primary streaming path (used by EventLoopNode._run_single_turn)
    # ------------------------------------------------------------------

    async def stream(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Async generator — must be iterable directly with ``async for``.

        EventLoopNode calls ``async for event in ctx.llm.stream(...)`` without
        awaiting the call first, so this method MUST be an async generator
        (i.e. contain ``yield``).  On a cache hit we yield synthetic events;
        on a miss we delegate to the inner provider's generator.
        """
        cached = self._interceptor.on_llm_call()
        if cached is not None:
            # Yield synthetic events reconstructed from the cached response.
            # Text portion first, then tool call suggestions, then finish.
            yield TextDeltaEvent(content=cached.llm_text, snapshot=cached.llm_text)
            yield TextEndEvent(full_text=cached.llm_text)

            # Tool call suggestions — each emitted as a ToolCallEvent so that
            # EventLoopNode calls the same tools as the original run in order.
            for suggestion in cached.tool_call_suggestions:
                yield ToolCallEvent(
                    tool_use_id=str(uuid.uuid4()),
                    tool_name=suggestion["tool_name"],
                    tool_input=suggestion.get("tool_input", {}),
                )

            yield FinishEvent(
                stop_reason="end_turn" if not cached.tool_call_suggestions else "tool_use",
                input_tokens=cached.input_tokens,
                output_tokens=cached.output_tokens,
                model="replay-cache",
            )
        else:
            # Miss — re-yield every event from the inner (live) provider.
            async for event in self._inner.stream(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
            ):
                yield event

    # ------------------------------------------------------------------
    # Async completion (used for compaction path in EventLoopNode)
    # ------------------------------------------------------------------

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> LLMResponse:
        cached = self._interceptor.on_llm_call()
        if cached is not None:
            return LLMResponse(
                content=cached.llm_text,
                model="replay-cache",
                input_tokens=cached.input_tokens,
                output_tokens=cached.output_tokens,
                stop_reason="end_turn",
            )
        return await self._inner.acomplete(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            response_format=response_format,
            json_mode=json_mode,
            max_retries=max_retries,
        )

    # ------------------------------------------------------------------
    # Sync completion (abstract method — wraps acomplete via executor)
    # ------------------------------------------------------------------

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> LLMResponse:
        # EventLoopNode never calls complete() directly; it uses stream() or acomplete().
        # We implement it for interface completeness by delegating to inner.
        cached = self._interceptor.on_llm_call()
        if cached is not None:
            return LLMResponse(
                content=cached.llm_text,
                model="replay-cache",
                input_tokens=cached.input_tokens,
                output_tokens=cached.output_tokens,
                stop_reason="end_turn",
            )
        return self._inner.complete(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            response_format=response_format,
            json_mode=json_mode,
            max_retries=max_retries,
        )


# ---------------------------------------------------------------------------
# Tool executor closure
# ---------------------------------------------------------------------------


def make_replay_tool_executor(
    inner: Callable[[ToolUse], ToolResult | Awaitable[ToolResult]] | None,
    interceptor: ReplayInterceptor,
) -> Callable[[ToolUse], Awaitable[ToolResult]]:
    """Return an async tool executor closure that intercepts calls with cached results.

    The returned callable has the same signature as EventLoopNode's
    ``tool_executor`` parameter: ``(ToolUse) -> ToolResult | Awaitable[ToolResult]``.

    On a cache **hit** it returns a :class:`ToolResult` built from the cached
    result string, without calling *inner*.  On a miss it delegates to *inner*
    (which may be sync or async).  If *inner* is ``None`` and there is a miss,
    the returned ToolResult signals an error.

    Implementation note: a closure is used instead of a class because
    ``tool_executor`` is typed as a plain ``Callable``, not an interface.
    """

    import asyncio

    async def _replay_tool_executor(tool_use: ToolUse) -> ToolResult:
        cached_result = interceptor.on_tool_call()
        if cached_result is not None:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=cached_result,
                is_error=False,
            )

        # Cache miss — delegate to live tool executor
        if inner is None:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=(
                    f"Replay cache miss for tool '{tool_use.name}' "
                    "and no live tool executor configured."
                ),
                is_error=True,
            )

        result = inner(tool_use)
        if asyncio.iscoroutine(result) or asyncio.isfuture(result):
            result = await result
        return result  # type: ignore[return-value]

    return _replay_tool_executor


# ---------------------------------------------------------------------------
# Diff helpers (used by runner/cli.py to build ReplayResult)
# ---------------------------------------------------------------------------


def build_improvement_hypothesis(
    source_success: bool,
    replay_success: bool,
    diverged_nodes: list[str],
    from_node: str | None,
    from_node_original_status: str,
    from_node_replay_status: str,
    total_misses: int,
) -> str:
    """Return a rule-based improvement hypothesis string.

    Rules are evaluated in priority order — first matching rule wins.
    No LLM calls are made.
    """
    if total_misses > 0:
        return (
            f"Partial replay ({total_misses} cache miss(es)) — "
            "results are indicative, not exact. Re-run with --no-freeze-llm "
            "/ --no-freeze-tools to confirm."
        )

    if (
        from_node is not None
        and from_node_original_status not in ("success", "")
        and from_node_replay_status == "success"
    ):
        return (
            f"Node '{from_node}' recovered in replay; "
            "downstream path unblocked. Investigate inputs to this node."
        )

    if not source_success and replay_success:
        return (
            "Full recovery achieved in replay — compare node diffs "
            "for the root cause of the original failure."
        )

    if source_success == replay_success and not diverged_nodes:
        if not source_success:
            return (
                "Failure reproduced deterministically — "
                "root cause confirmed in original session logs."
            )
        return "Replay matched original execution exactly — no divergence detected."

    if diverged_nodes:
        return (
            f"Divergence detected in {len(diverged_nodes)} node(s): "
            f"{', '.join(diverged_nodes[:5])}. Review node diffs for details."
        )

    return "Mixed results — review node diffs for details."
