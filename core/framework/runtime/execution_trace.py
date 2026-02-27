"""Structured execution tracing for runtime-level observability.

Execution Intelligence (Phase 1) captures runtime behavior as hierarchical spans
that can be serialized and later replayed (Phase 2).

Key guarantees:
- Ordered span capture with deterministic serialization
- Explicit parent-child relationships
- Exception-aware status transitions
- Provider-agnostic instrumentation (LLM + tools)
"""

from __future__ import annotations

import inspect
import threading
import datetime as dt
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from framework.llm.provider import LLMProvider


SpanStatus = Literal["success", "error", "running"]


def _utcnow() -> datetime:
    return datetime.now(dt.UTC)


@dataclass(slots=True)
class ExecutionSpan:
    """A single execution unit within an :class:`ExecutionTrace`.

    Purpose:
        Represent one observable runtime operation (for example, graph execution,
        node execution, LLM call, or tool call).

    Lifecycle:
        1. Created with ``status="running"`` and ``start_time``.
        2. Closed by the trace context manager with ``end_time``.
        3. Finalized as ``"success"`` or ``"error"``.

    Status semantics:
        - ``running``: span has started but not finished.
        - ``success``: span completed without exception.
        - ``error``: span completed with exception or explicit error marking.
    """

    id: UUID = field(default_factory=uuid4)
    parent_id: UUID | None = None
    name: str = ""
    start_time: datetime = field(default_factory=_utcnow)
    end_time: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: SpanStatus = "running"
    _order_index: int = field(default=0, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "name": self.name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "metadata": dict(self.metadata),
            "status": self.status,
        }


class _SpanContext:
    """Sync/async context manager that records a span lifecycle."""

    __slots__ = ("_trace", "_name", "_metadata", "_token", "_span")

    def __init__(
        self,
        trace: ExecutionTrace,
        name: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        self._trace = trace
        self._name = name
        self._metadata = metadata or {}
        self._token: Token[tuple[UUID, ...]] | None = None
        self._span: ExecutionSpan | None = None

    def __enter__(self) -> ExecutionSpan:
        self._span, self._token = self._trace._start_span(self._name, self._metadata)
        return self._span

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if self._span is not None:
            self._trace._finish_span(self._span, self._token, exc)
        return False

    async def __aenter__(self) -> ExecutionSpan:
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return self.__exit__(exc_type, exc, tb)


class ExecutionTrace:
    """In-memory execution trace with deterministic ordering.

    Purpose:
        Collect structured span data for observability, debugging, and replay
        preparation without relying on global mutable state.

    Lifecycle:
        1. Create one trace per runtime execution.
        2. Open nested spans via ``trace.span(...)``.
        3. Serialize via :meth:`to_dict` and persist as execution artifact.

    Deterministic ordering guarantee:
        Spans are assigned a monotonic insertion index at creation time under
        lock. ``to_dict()`` serializes spans by this index, producing stable,
        deterministic output ordering independent of dictionary iteration order.
    """

    def __init__(self, metadata: dict[str, Any] | None = None) -> None:
        self.id: UUID = uuid4()
        self.created_at: datetime = _utcnow()
        self.metadata: dict[str, Any] = metadata or {}
        self._lock = threading.Lock()
        self._spans: dict[UUID, ExecutionSpan] = {}
        self._ordered_span_ids: list[UUID] = []
        self._children: dict[UUID | None, list[UUID]] = {None: []}
        self._next_order = 0
        self._span_stack: ContextVar[tuple[UUID, ...]] = ContextVar(
            "execution_trace_stack",
            default=(),
        )

    def span(self, name: str, metadata: dict[str, Any] | None = None) -> _SpanContext:
        return _SpanContext(self, name=name, metadata=metadata)

    def _start_span(
        self,
        name: str,
        metadata: dict[str, Any],
    ) -> tuple[ExecutionSpan, Token[tuple[UUID, ...]]]:
        parent_stack = self._span_stack.get()
        parent_id = parent_stack[-1] if parent_stack else None
        span = ExecutionSpan(
            parent_id=parent_id,
            name=name,
            metadata=dict(metadata),
        )

        with self._lock:
            span._order_index = self._next_order
            self._next_order += 1
            self._spans[span.id] = span
            self._ordered_span_ids.append(span.id)
            self._children.setdefault(parent_id, []).append(span.id)
            self._children.setdefault(span.id, [])

        token = self._span_stack.set((*parent_stack, span.id))
        return span, token

    def _finish_span(
        self,
        span: ExecutionSpan,
        token: Token[tuple[UUID, ...]] | None,
        exc: BaseException | None,
    ) -> None:
        if exc is not None:
            span.status = "error"
            span.metadata.setdefault("exception_type", type(exc).__name__)
            span.metadata.setdefault("exception_message", str(exc))
        elif span.status == "running":
            span.status = "success"

        end_time = _utcnow()
        if end_time <= span.start_time:
            end_time = span.start_time + timedelta(microseconds=1)
        span.end_time = end_time
        if token is not None:
            self._span_stack.reset(token)

    @property
    def spans(self) -> list[ExecutionSpan]:
        with self._lock:
            return [self._spans[span_id] for span_id in self._ordered_span_ids]

    def children(self, span_id: UUID | None) -> list[ExecutionSpan]:
        with self._lock:
            child_ids = list(self._children.get(span_id, []))
            return [self._spans[cid] for cid in child_ids]

    def to_dict(self) -> dict[str, Any]:
        ordered_spans = sorted(self.spans, key=lambda span: span._order_index)
        return {
            "id": str(self.id),
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
            "spans": [span.to_dict() for span in ordered_spans],
        }

    def replay(self, *_: Any, **__: Any) -> None:
        """Phase 2 will replay traces against runtime state transitions."""
        raise NotImplementedError("Execution trace replay is planned for Phase 2.")


class TracingLLMProvider(LLMProvider):
    """Provider-agnostic LLM wrapper that emits execution spans."""

    def __init__(self, provider: LLMProvider, trace: ExecutionTrace) -> None:
        self._provider = provider
        self._trace = trace

    def __getattr__(self, item: str) -> Any:
        return getattr(self._provider, item)

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Any] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> Any:
        with self._trace.span(
            "llm_call",
            {
                "method": "complete",
                "message_count": len(messages),
                "tool_count": len(tools or []),
                "max_tokens": max_tokens,
                "json_mode": json_mode,
            },
        ):
            return self._provider.complete(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                response_format=response_format,
                json_mode=json_mode,
                max_retries=max_retries,
            )

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Any],
        tool_executor: Any,
        max_iterations: int = 10,
    ) -> Any:
        with self._trace.span(
            "llm_call",
            {
                "method": "complete_with_tools",
                "message_count": len(messages),
                "tool_count": len(tools),
                "max_iterations": max_iterations,
            },
        ):
            return self._provider.complete_with_tools(
                messages=messages,
                system=system,
                tools=tools,
                tool_executor=tool_executor,
                max_iterations=max_iterations,
            )

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Any] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> Any:
        with self._trace.span(
            "llm_call",
            {
                "method": "acomplete",
                "message_count": len(messages),
                "tool_count": len(tools or []),
                "max_tokens": max_tokens,
                "json_mode": json_mode,
            },
        ):
            return await self._provider.acomplete(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                response_format=response_format,
                json_mode=json_mode,
                max_retries=max_retries,
            )

    async def acomplete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Any],
        tool_executor: Any,
        max_iterations: int = 10,
    ) -> Any:
        with self._trace.span(
            "llm_call",
            {
                "method": "acomplete_with_tools",
                "message_count": len(messages),
                "tool_count": len(tools),
                "max_iterations": max_iterations,
            },
        ):
            return await self._provider.acomplete_with_tools(
                messages=messages,
                system=system,
                tools=tools,
                tool_executor=tool_executor,
                max_iterations=max_iterations,
            )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Any] | None = None,
        max_tokens: int = 4096,
    ):
        async with self._trace.span(
            "llm_call",
            {
                "method": "stream",
                "message_count": len(messages),
                "tool_count": len(tools or []),
                "max_tokens": max_tokens,
            },
        ):
            async for event in self._provider.stream(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
            ):
                yield event


def wrap_llm_provider(llm: LLMProvider | None, trace: ExecutionTrace | None) -> LLMProvider | None:
    if llm is None or trace is None:
        return llm
    if isinstance(llm, TracingLLMProvider):
        return llm
    return TracingLLMProvider(provider=llm, trace=trace)


def wrap_tool_executor(tool_executor: Any, trace: ExecutionTrace | None):
    if tool_executor is None or trace is None:
        return tool_executor

    async def _traced_tool_executor(tool_use: Any):
        with trace.span(
            "tool_execution",
            {
                "tool_name": getattr(tool_use, "name", "unknown"),
                "tool_use_id": getattr(tool_use, "id", ""),
            },
        ) as tool_span:
            result = tool_executor(tool_use)
            if inspect.isawaitable(result):
                result = await result

            if getattr(result, "is_error", False):
                tool_span.status = "error"
                tool_span.metadata["tool_error"] = getattr(result, "content", "")

            return result

    return _traced_tool_executor
