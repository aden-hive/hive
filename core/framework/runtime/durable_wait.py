"""
Durable wait / signal / timer runtime substrate.

Provides first-class primitives for:
- Wait: durable suspension without holding compute
- Signals: external events delivered to a run with deterministic matching
- Timers: time-based wake-ups (synthetic timeout signals)

Guarantees: run isolation, exactly-once resume per wait, deterministic (FIFO) matching.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.runtime.event_bus import EventBus

logger = logging.getLogger(__name__)

# Synthetic signal type emitted when a wait times out (node logic can branch uniformly)
WAIT_TIMEOUT_SIGNAL_TYPE = "wait.timeout"


@dataclass(frozen=True)
class WaitRequest:
    """
    Durable suspension point created by a specific node attempt.

    Unique within a run. When persisted, execution suspends until a matching
    signal is delivered or timeout_at is reached.
    """

    wait_id: str
    run_id: str
    node_id: str
    attempt: int
    signal_type: str  # e.g. "email.reply", "approval"
    match: dict[str, Any] | None  # optional structured filter
    timeout_at: datetime | None


@dataclass(frozen=True)
class SignalEnvelope:
    """
    Externally delivered event.

    Delivered at least once; runtime guarantees exactly-once resume per wait,
    not exactly-once delivery.
    """

    signal_type: str
    payload: dict[str, Any]
    correlation_id: str | None
    causation_id: str | None
    received_at: datetime


@dataclass
class ExecutionPaused:
    """
    Result of runtime.wait(): execution suspended on a durable wait.

    Caller should persist this and resume when signal or tick delivers
    a matching resume for this wait_id/run_id.
    """

    wait_id: str
    run_id: str
    node_id: str
    attempt: int
    session_state: dict[str, Any]
    wait_request: WaitRequest = field(repr=False)


@dataclass
class WaitResumed:
    """
    Result of signal() or tick(): one wait was resumed (matched or timed out).

    Used by the runner to know which run/wait to resume and whether
    it was due to signal (timed_out=False) or timeout (timed_out=True).
    """

    run_id: str
    wait_id: str
    timed_out: bool
    matched_signal_type: str | None = None  # set when resumed by signal


class WaitStoreIfce(ABC):
    """
    Interface for persisting and querying pending waits.

    Implementations must guarantee run isolation and exactly-once
    resume per (run_id, wait_id).
    """

    @abstractmethod
    async def add(self, wait: WaitRequest) -> None:
        """Persist a wait. Idempotent for same wait_id within run."""
        ...

    @abstractmethod
    async def get_pending(self, run_id: str) -> list[WaitRequest]:
        """Return pending waits for the run, in creation order (FIFO)."""
        ...

    @abstractmethod
    async def match_signal(self, run_id: str, envelope: SignalEnvelope) -> str | None:
        """
        Find one pending wait matching the signal (type + optional match filter).

        Deterministic: FIFO by creation order. Removes the matched wait
        (exactly-once resume). Returns wait_id or None.
        """
        ...

    @abstractmethod
    async def mark_resumed(self, run_id: str, wait_id: str) -> None:
        """Mark a wait as resumed (e.g. after timeout). Removes from pending."""
        ...

    @abstractmethod
    async def get_expired(self, now: datetime) -> list[tuple[str, str]]:
        """Return (run_id, wait_id) pairs for waits with timeout_at <= now."""
        ...


def _match_filter(wait_match: dict[str, Any] | None, payload: dict[str, Any]) -> bool:
    """True if payload satisfies wait_match (all keys in wait_match equal in payload)."""
    if wait_match is None:
        return True
    for k, v in wait_match.items():
        if payload.get(k) != v:
            return False
    return True


class InMemoryWaitStore(WaitStoreIfce):
    """
    In-memory wait store: pending waits per run, FIFO order.

    Run-isolated; exactly-once resume via removal on match/mark_resumed.
    """

    def __init__(self) -> None:
        # run_id -> list of WaitRequest (append-only, match removes)
        self._pending: dict[str, list[WaitRequest]] = {}
        self._lock = asyncio.Lock()

    async def add(self, wait: WaitRequest) -> None:
        async with self._lock:
            if wait.run_id not in self._pending:
                self._pending[wait.run_id] = []
            # Avoid duplicate wait_id
            existing_ids = {w.wait_id for w in self._pending[wait.run_id]}
            if wait.wait_id not in existing_ids:
                self._pending[wait.run_id].append(wait)

    async def get_pending(self, run_id: str) -> list[WaitRequest]:
        async with self._lock:
            return list(self._pending.get(run_id, []))

    async def match_signal(self, run_id: str, envelope: SignalEnvelope) -> str | None:
        async with self._lock:
            pending = self._pending.get(run_id, [])
            for i, w in enumerate(pending):
                if w.signal_type != envelope.signal_type:
                    continue
                if not _match_filter(w.match, envelope.payload):
                    continue
                # Match: remove and return
                wait_id = w.wait_id
                self._pending[run_id] = pending[:i] + pending[i + 1 :]
                return wait_id
        return None

    async def mark_resumed(self, run_id: str, wait_id: str) -> None:
        async with self._lock:
            pending = self._pending.get(run_id, [])
            self._pending[run_id] = [w for w in pending if w.wait_id != wait_id]

    async def get_expired(self, now: datetime) -> list[tuple[str, str]]:
        async with self._lock:
            result: list[tuple[str, str]] = []
            for rid, pending in list(self._pending.items()):
                remaining: list[WaitRequest] = []
                for w in pending:
                    if w.timeout_at is not None and w.timeout_at <= now:
                        result.append((rid, w.wait_id))
                    else:
                        remaining.append(w)
                self._pending[rid] = remaining
            return result


class DurableWaitRuntime:
    """
    Runtime surface for durable wait / signal / tick.

    Additive API: wait() suspends and returns ExecutionPaused;
    signal() and tick() drive deterministic resume. Emits lifecycle
    events (wait.created, wait.matched, wait.timed_out) for auditing.
    """

    def __init__(
        self,
        wait_store: WaitStoreIfce,
        event_bus: EventBus | None = None,
        stream_id: str = "default",
    ) -> None:
        self._store = wait_store
        self._event_bus = event_bus
        self._stream_id = stream_id

    async def wait(
        self,
        wait_request: WaitRequest,
        session_state: dict[str, Any] | None = None,
    ) -> ExecutionPaused:
        """
        Persist the wait and suspend execution.

        Returns ExecutionPaused so the caller can persist and later
        resume when signal or tick fires for this wait.
        """
        await self._store.add(wait_request)
        state = session_state or {}

        if self._event_bus:
            from framework.runtime.event_bus import AgentEvent, EventType

            await self._event_bus.publish(
                AgentEvent(
                    type=EventType.WAIT_CREATED,
                    stream_id=self._stream_id,
                    execution_id=wait_request.run_id,
                    data={
                        "wait_id": wait_request.wait_id,
                        "run_id": wait_request.run_id,
                        "node_id": wait_request.node_id,
                        "attempt": wait_request.attempt,
                        "signal_type": wait_request.signal_type,
                        "timeout_at": (
                            wait_request.timeout_at.isoformat()
                            if wait_request.timeout_at
                            else None
                        ),
                    },
                )
            )

        return ExecutionPaused(
            wait_id=wait_request.wait_id,
            run_id=wait_request.run_id,
            node_id=wait_request.node_id,
            attempt=wait_request.attempt,
            session_state=state,
            wait_request=wait_request,
        )

    async def signal(
        self,
        run_id: str,
        envelope: SignalEnvelope,
    ) -> WaitResumed | None:
        """
        Match the signal against pending waits for the run; resume at most one.

        Deterministic (FIFO). Returns WaitResumed for the matched wait, or None.
        """
        from framework.runtime.event_bus import AgentEvent, EventType

        wait_id = await self._store.match_signal(run_id, envelope)
        if wait_id is None:
            return None

        if self._event_bus:
            await self._event_bus.publish(
                AgentEvent(
                    type=EventType.WAIT_MATCHED,
                    stream_id=self._stream_id,
                    execution_id=run_id,
                    data={
                        "wait_id": wait_id,
                        "run_id": run_id,
                        "signal_type": envelope.signal_type,
                    },
                )
            )

        return WaitResumed(
            run_id=run_id,
            wait_id=wait_id,
            timed_out=False,
            matched_signal_type=envelope.signal_type,
        )

    async def tick(self, now: datetime | None = None) -> list[WaitResumed]:
        """
        Emit timeout events for expired waits and return resumed list.

        Each expired wait is marked resumed and yields a WaitResumed
        with timed_out=True (synthetic wait.timeout signal semantics).
        """
        from framework.runtime.event_bus import AgentEvent, EventType

        if now is None:
            now = datetime.now(timezone.utc)
        expired = await self._store.get_expired(now)
        resumed: list[WaitResumed] = []
        for run_id, wait_id in expired:
            await self._store.mark_resumed(run_id, wait_id)
            if self._event_bus:
                await self._event_bus.publish(
                    AgentEvent(
                        type=EventType.WAIT_TIMED_OUT,
                        stream_id=self._stream_id,
                        execution_id=run_id,
                        data={
                            "wait_id": wait_id,
                            "run_id": run_id,
                            "signal_type": WAIT_TIMEOUT_SIGNAL_TYPE,
                        },
                    )
                )
            resumed.append(
                WaitResumed(
                    run_id=run_id,
                    wait_id=wait_id,
                    timed_out=True,
                    matched_signal_type=WAIT_TIMEOUT_SIGNAL_TYPE,
                )
            )
        return resumed
