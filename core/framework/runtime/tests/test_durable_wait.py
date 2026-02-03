"""
Tests for durable wait / signal / timer runtime substrate.

Covers:
- WaitRequest, SignalEnvelope, ExecutionPaused models
- WaitStore: run isolation, exactly-once resume, deterministic (FIFO) matching
- DurableWaitRuntime: wait(), signal(), tick() and lifecycle events
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any

import pytest

from framework.runtime.durable_wait import (
    DurableWaitRuntime,
    ExecutionPaused,
    InMemoryWaitStore,
    SignalEnvelope,
    WaitRequest,
    WaitStoreIfce,
)
from framework.runtime.event_bus import AgentEvent, EventBus, EventType

# === Fixtures ===


@pytest.fixture
def run_id() -> str:
    return "run_001"


@pytest.fixture
def wait_request(run_id: str) -> WaitRequest:
    return WaitRequest(
        wait_id="wait_1",
        run_id=run_id,
        node_id="node_a",
        attempt=1,
        signal_type="email.reply",
        match={"thread_id": "t1"},
        timeout_at=datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def signal_envelope() -> SignalEnvelope:
    return SignalEnvelope(
        signal_type="email.reply",
        payload={"thread_id": "t1", "body": "Got it"},
        correlation_id="c1",
        causation_id=None,
        received_at=datetime.now(UTC),
    )


@pytest.fixture
def wait_store() -> WaitStoreIfce:
    return InMemoryWaitStore()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus(max_history=100)


@pytest.fixture
def durable_runtime(wait_store: WaitStoreIfce, event_bus: EventBus) -> DurableWaitRuntime:
    return DurableWaitRuntime(wait_store=wait_store, event_bus=event_bus)


# === Model tests ===


def test_wait_request_creation(wait_request: WaitRequest, run_id: str) -> None:
    assert wait_request.wait_id == "wait_1"
    assert wait_request.run_id == run_id
    assert wait_request.node_id == "node_a"
    assert wait_request.attempt == 1
    assert wait_request.signal_type == "email.reply"
    assert wait_request.match == {"thread_id": "t1"}
    assert wait_request.timeout_at is not None


def test_wait_request_frozen(wait_request: WaitRequest) -> None:
    with pytest.raises(FrozenInstanceError):
        wait_request.wait_id = "other"  # type: ignore[misc]


def test_signal_envelope_creation(signal_envelope: SignalEnvelope) -> None:
    assert signal_envelope.signal_type == "email.reply"
    assert signal_envelope.payload["thread_id"] == "t1"
    assert signal_envelope.correlation_id == "c1"


def test_execution_paused_creation(wait_request: WaitRequest) -> None:
    session_state: dict[str, Any] = {"paused_at": "node_a", "memory": {}}
    paused = ExecutionPaused(
        wait_id=wait_request.wait_id,
        run_id=wait_request.run_id,
        node_id=wait_request.node_id,
        attempt=wait_request.attempt,
        session_state=session_state,
        wait_request=wait_request,
    )
    assert paused.wait_id == "wait_1"
    assert paused.run_id == wait_request.run_id
    assert paused.session_state == session_state
    assert paused.wait_request == wait_request


# === WaitStore tests (run isolation, exactly-once, deterministic) ===


@pytest.mark.asyncio
async def test_wait_store_add_and_get_pending(
    wait_store: WaitStoreIfce,
    wait_request: WaitRequest,
    run_id: str,
) -> None:
    await wait_store.add(wait_request)
    pending = await wait_store.get_pending(run_id)
    assert len(pending) == 1
    assert pending[0].wait_id == wait_request.wait_id

    other_run = "run_002"
    pending_other = await wait_store.get_pending(other_run)
    assert len(pending_other) == 0


@pytest.mark.asyncio
async def test_wait_store_run_isolation(
    wait_store: WaitStoreIfce,
    run_id: str,
) -> None:
    """Events for one run must not match waits for another run."""
    req_a = WaitRequest(
        wait_id="w_a",
        run_id=run_id,
        node_id="n",
        attempt=1,
        signal_type="approval",
        match=None,
        timeout_at=None,
    )
    await wait_store.add(req_a)

    envelope = SignalEnvelope(
        signal_type="approval",
        payload={},
        correlation_id=None,
        causation_id=None,
        received_at=datetime.now(UTC),
    )
    # Signal for different run must not match
    matched = await wait_store.match_signal("run_other", envelope)
    assert matched is None

    pending = await wait_store.get_pending(run_id)
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_wait_store_match_signal_deterministic_fifo(
    wait_store: WaitStoreIfce,
    run_id: str,
) -> None:
    """If multiple waits match, selection is deterministic (FIFO by creation order)."""
    for i in range(3):
        req = WaitRequest(
            wait_id=f"w_{i}",
            run_id=run_id,
            node_id="n",
            attempt=1,
            signal_type="same",
            match=None,
            timeout_at=None,
        )
        await wait_store.add(req)

    envelope = SignalEnvelope(
        signal_type="same",
        payload={},
        correlation_id=None,
        causation_id=None,
        received_at=datetime.now(UTC),
    )
    matched = await wait_store.match_signal(run_id, envelope)
    assert matched == "w_0"
    # Second match returns next
    matched2 = await wait_store.match_signal(run_id, envelope)
    assert matched2 == "w_1"
    matched3 = await wait_store.match_signal(run_id, envelope)
    assert matched3 == "w_2"
    matched_none = await wait_store.match_signal(run_id, envelope)
    assert matched_none is None


@pytest.mark.asyncio
async def test_wait_store_match_signal_type_and_match_filter(
    wait_store: WaitStoreIfce,
    run_id: str,
) -> None:
    """Match requires signal_type equality and optional match dict filter."""
    req1 = WaitRequest(
        wait_id="w1",
        run_id=run_id,
        node_id="n",
        attempt=1,
        signal_type="email.reply",
        match={"thread_id": "t1"},
        timeout_at=None,
    )
    req2 = WaitRequest(
        wait_id="w2",
        run_id=run_id,
        node_id="n",
        attempt=1,
        signal_type="approval",
        match=None,
        timeout_at=None,
    )
    await wait_store.add(req1)
    await wait_store.add(req2)

    # Signal approval: only w2 matches; w1 remains pending
    envelope_approval = SignalEnvelope(
        signal_type="approval",
        payload={"thread_id": "t1"},
        correlation_id=None,
        causation_id=None,
        received_at=datetime.now(UTC),
    )
    matched = await wait_store.match_signal(run_id, envelope_approval)
    assert matched == "w2"
    pending = await wait_store.get_pending(run_id)
    assert len(pending) == 1 and pending[0].wait_id == "w1"

    # Signal email.reply with matching payload: w1 matches
    envelope_reply = SignalEnvelope(
        signal_type="email.reply",
        payload={"thread_id": "t1"},
        correlation_id=None,
        causation_id=None,
        received_at=datetime.now(UTC),
    )
    assert await wait_store.match_signal(run_id, envelope_reply) == "w1"
    pending2 = await wait_store.get_pending(run_id)
    assert len(pending2) == 0


@pytest.mark.asyncio
async def test_wait_store_exactly_once_resume(
    wait_store: WaitStoreIfce,
    wait_request: WaitRequest,
    run_id: str,
    signal_envelope: SignalEnvelope,
) -> None:
    """For a given (run_id, wait_id), at most one resume (match removes wait)."""
    await wait_store.add(wait_request)
    first = await wait_store.match_signal(run_id, signal_envelope)
    assert first == wait_request.wait_id
    second = await wait_store.match_signal(run_id, signal_envelope)
    assert second is None
    pending = await wait_store.get_pending(run_id)
    assert len(pending) == 0


@pytest.mark.asyncio
async def test_wait_store_get_expired(
    wait_store: WaitStoreIfce,
    run_id: str,
) -> None:
    past = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    future = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    req_past = WaitRequest(
        wait_id="expired",
        run_id=run_id,
        node_id="n",
        attempt=1,
        signal_type="x",
        match=None,
        timeout_at=past,
    )
    req_future = WaitRequest(
        wait_id="not_expired",
        run_id=run_id,
        node_id="n",
        attempt=1,
        signal_type="x",
        match=None,
        timeout_at=future,
    )
    await wait_store.add(req_past)
    await wait_store.add(req_future)

    now = datetime(2025, 2, 1, 0, 0, 0, tzinfo=UTC)
    expired = await wait_store.get_expired(now)
    assert len(expired) == 1
    assert expired[0][0] == run_id and expired[0][1] == "expired"

    # get_expired removes expired waits from store; second call returns nothing
    expired2 = await wait_store.get_expired(now)
    assert len(expired2) == 0


@pytest.mark.asyncio
async def test_wait_store_get_expired_none_timeout(
    wait_store: WaitStoreIfce,
    run_id: str,
) -> None:
    req = WaitRequest(
        wait_id="no_timeout",
        run_id=run_id,
        node_id="n",
        attempt=1,
        signal_type="x",
        match=None,
        timeout_at=None,
    )
    await wait_store.add(req)
    expired = await wait_store.get_expired(datetime.now(UTC))
    assert len(expired) == 0


# === DurableWaitRuntime tests ===


@pytest.mark.asyncio
async def test_runtime_wait_returns_execution_paused(
    durable_runtime: DurableWaitRuntime,
    wait_request: WaitRequest,
    run_id: str,
) -> None:
    session_state: dict[str, Any] = {"memory": {}}
    paused = await durable_runtime.wait(wait_request, session_state=session_state)
    assert isinstance(paused, ExecutionPaused)
    assert paused.wait_id == wait_request.wait_id
    assert paused.run_id == run_id
    assert paused.session_state == session_state


@pytest.mark.asyncio
async def test_runtime_wait_emits_wait_created(
    durable_runtime: DurableWaitRuntime,
    wait_request: WaitRequest,
    event_bus: EventBus,
) -> None:
    received: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        received.append(event)

    sub_id = event_bus.subscribe(
        event_types=[EventType.WAIT_CREATED],
        handler=handler,
    )
    await durable_runtime.wait(wait_request, session_state={})
    await asyncio.sleep(0.05)
    event_bus.unsubscribe(sub_id)

    assert len(received) == 1
    assert received[0].type == EventType.WAIT_CREATED
    assert received[0].data.get("wait_id") == wait_request.wait_id
    assert received[0].data.get("run_id") == wait_request.run_id


@pytest.mark.asyncio
async def test_runtime_signal_matches_and_returns_wait_id(
    durable_runtime: DurableWaitRuntime,
    wait_request: WaitRequest,
    signal_envelope: SignalEnvelope,
    run_id: str,
) -> None:
    await durable_runtime.wait(wait_request, session_state={})
    result = await durable_runtime.signal(run_id, signal_envelope)
    assert result is not None
    assert result.wait_id == wait_request.wait_id
    assert result.matched_signal_type == signal_envelope.signal_type


@pytest.mark.asyncio
async def test_runtime_signal_no_match_returns_none(
    durable_runtime: DurableWaitRuntime,
    run_id: str,
    signal_envelope: SignalEnvelope,
) -> None:
    result = await durable_runtime.signal(run_id, signal_envelope)
    assert result is None


@pytest.mark.asyncio
async def test_runtime_signal_emits_wait_matched(
    durable_runtime: DurableWaitRuntime,
    wait_request: WaitRequest,
    signal_envelope: SignalEnvelope,
    event_bus: EventBus,
) -> None:
    received: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        received.append(event)

    await durable_runtime.wait(wait_request, session_state={})
    sub_id = event_bus.subscribe(
        event_types=[EventType.WAIT_MATCHED],
        handler=handler,
    )
    await durable_runtime.signal(wait_request.run_id, signal_envelope)
    await asyncio.sleep(0.05)
    event_bus.unsubscribe(sub_id)

    assert len(received) == 1
    assert received[0].type == EventType.WAIT_MATCHED
    assert received[0].data.get("wait_id") == wait_request.wait_id


@pytest.mark.asyncio
async def test_runtime_tick_returns_expired_waits(
    durable_runtime: DurableWaitRuntime,
    wait_store: WaitStoreIfce,
    run_id: str,
) -> None:
    past = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    req = WaitRequest(
        wait_id="timed_out",
        run_id=run_id,
        node_id="n",
        attempt=1,
        signal_type="x",
        match=None,
        timeout_at=past,
    )
    await wait_store.add(req)
    now = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
    resumed = await durable_runtime.tick(now)
    assert len(resumed) == 1
    assert resumed[0].wait_id == "timed_out"
    assert resumed[0].run_id == run_id
    assert resumed[0].timed_out is True


@pytest.mark.asyncio
async def test_runtime_tick_emits_wait_timed_out(
    durable_runtime: DurableWaitRuntime,
    wait_store: WaitStoreIfce,
    event_bus: EventBus,
    run_id: str,
) -> None:
    past = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    req = WaitRequest(
        wait_id="timed_out",
        run_id=run_id,
        node_id="n",
        attempt=1,
        signal_type="x",
        match=None,
        timeout_at=past,
    )
    await wait_store.add(req)

    received: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        received.append(event)

    sub_id = event_bus.subscribe(
        event_types=[EventType.WAIT_TIMED_OUT],
        handler=handler,
    )
    now = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
    await durable_runtime.tick(now)
    await asyncio.sleep(0.05)
    event_bus.unsubscribe(sub_id)

    assert len(received) == 1
    assert received[0].type == EventType.WAIT_TIMED_OUT
    assert received[0].data.get("wait_id") == "timed_out"


@pytest.mark.asyncio
async def test_runtime_tick_exactly_once_per_wait(
    durable_runtime: DurableWaitRuntime,
    wait_store: WaitStoreIfce,
    run_id: str,
) -> None:
    past = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    req = WaitRequest(
        wait_id="once",
        run_id=run_id,
        node_id="n",
        attempt=1,
        signal_type="x",
        match=None,
        timeout_at=past,
    )
    await wait_store.add(req)
    now = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
    first = await durable_runtime.tick(now)
    assert len(first) == 1
    second = await durable_runtime.tick(now)
    assert len(second) == 0
