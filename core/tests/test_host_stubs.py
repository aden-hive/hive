"""Test coverage stubs for the host module.

Tests the public API of ``framework.host`` without spinning up real workers,
event buses, or network connections.  All async tests use mock agent loops
so no LLM calls are made.

Coverage targets:
- WorkerStatus enum members
- WorkerResult and WorkerInfo dataclass construction / defaults
- Worker construction, property access (info, is_active, is_persistent)
- EventType enum completeness (spot-check key members)
- AgentEvent construction
- EventBus subscribe/publish / unsubscribe lifecycle
- SharedBufferManager create_buffer isolation
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from framework.host.worker import Worker, WorkerInfo, WorkerResult, WorkerStatus
from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.host.shared_state import IsolationLevel, SharedBufferManager


# ---------------------------------------------------------------------------
# WorkerStatus
# ---------------------------------------------------------------------------


class TestWorkerStatus:
    """Tests for the WorkerStatus StrEnum."""

    def test_all_expected_statuses_exist(self):
        """All documented worker statuses are present."""
        assert WorkerStatus.PENDING == "pending"
        assert WorkerStatus.RUNNING == "running"
        assert WorkerStatus.COMPLETED == "completed"
        assert WorkerStatus.FAILED == "failed"
        assert WorkerStatus.STOPPED == "stopped"

    def test_status_is_string(self):
        """WorkerStatus values compare equal to plain strings."""
        assert WorkerStatus.RUNNING == "running"
        assert str(WorkerStatus.COMPLETED) == "completed"

    def test_membership(self):
        """WorkerStatus members can be iterated."""
        statuses = list(WorkerStatus)
        assert len(statuses) == 5


# ---------------------------------------------------------------------------
# WorkerResult
# ---------------------------------------------------------------------------


class TestWorkerResult:
    """Tests for the WorkerResult dataclass."""

    def test_default_construction(self):
        """WorkerResult uses correct defaults."""
        result = WorkerResult()
        assert result.output == {}
        assert result.error is None
        assert result.tokens_used == 0
        assert result.duration_seconds == 0.0
        assert result.status == "success"
        assert result.summary == ""
        assert result.data == {}

    def test_explicit_fields(self):
        """WorkerResult stores explicitly-provided fields."""
        result = WorkerResult(
            output={"answer": "42"},
            error=None,
            tokens_used=500,
            duration_seconds=1.5,
            status="partial",
            summary="Completed step 1 of 3",
            data={"step": 1},
        )
        assert result.output["answer"] == "42"
        assert result.tokens_used == 500
        assert result.duration_seconds == 1.5
        assert result.status == "partial"
        assert result.summary == "Completed step 1 of 3"
        assert result.data["step"] == 1

    def test_failure_result(self):
        """A failed WorkerResult captures the error message."""
        result = WorkerResult(status="failed", error="Tool call exceeded budget")
        assert result.status == "failed"
        assert result.error == "Tool call exceeded budget"


# ---------------------------------------------------------------------------
# WorkerInfo
# ---------------------------------------------------------------------------


class TestWorkerInfo:
    """Tests for the WorkerInfo dataclass."""

    def test_default_construction(self):
        """WorkerInfo stores required fields and defaults optional ones."""
        info = WorkerInfo(id="w_1", task="analyse data", status=WorkerStatus.PENDING)
        assert info.id == "w_1"
        assert info.task == "analyse data"
        assert info.status == WorkerStatus.PENDING
        assert info.started_at == 0.0
        assert info.result is None
        assert info.profile_name == ""

    def test_with_result(self):
        """WorkerInfo can hold a WorkerResult."""
        result = WorkerResult(status="success", summary="done")
        info = WorkerInfo(
            id="w_2",
            task="task",
            status=WorkerStatus.COMPLETED,
            started_at=1000.0,
            result=result,
            profile_name="slack-work",
        )
        assert info.result is result
        assert info.profile_name == "slack-work"
        assert info.started_at == 1000.0


# ---------------------------------------------------------------------------
# Worker (construction / property access only — no async execution)
# ---------------------------------------------------------------------------


class TestWorkerConstruction:
    """Tests for Worker construction and lightweight property access."""

    def _make_worker(
        self,
        worker_id: str = "w_test",
        task: str = "do something",
        persistent: bool = False,
        profile_name: str = "",
    ) -> Worker:
        agent_loop = MagicMock()
        agent_loop._owner_worker = None
        context = MagicMock()
        return Worker(
            worker_id=worker_id,
            task=task,
            agent_loop=agent_loop,
            context=context,
            persistent=persistent,
            profile_name=profile_name,
        )

    def test_initial_status_is_pending(self):
        """A freshly constructed Worker has PENDING status."""
        w = self._make_worker()
        assert w.status == WorkerStatus.PENDING

    def test_info_reflects_initial_state(self):
        """Worker.info returns a WorkerInfo with correct initial fields."""
        w = self._make_worker(worker_id="w_42", task="scrape linkedin")
        info = w.info
        assert info.id == "w_42"
        assert info.task == "scrape linkedin"
        assert info.status == WorkerStatus.PENDING
        assert info.result is None

    def test_is_active_true_when_pending(self):
        """is_active is True in PENDING state."""
        w = self._make_worker()
        assert w.is_active is True

    def test_is_active_true_when_running(self):
        """is_active is True in RUNNING state."""
        w = self._make_worker()
        w.status = WorkerStatus.RUNNING
        assert w.is_active is True

    def test_is_active_false_when_completed(self):
        """is_active is False once COMPLETED."""
        w = self._make_worker()
        w.status = WorkerStatus.COMPLETED
        assert w.is_active is False

    def test_is_active_false_when_failed(self):
        """is_active is False when FAILED."""
        w = self._make_worker()
        w.status = WorkerStatus.FAILED
        assert w.is_active is False

    def test_is_active_false_when_stopped(self):
        """is_active is False when STOPPED."""
        w = self._make_worker()
        w.status = WorkerStatus.STOPPED
        assert w.is_active is False

    def test_is_persistent_false_by_default(self):
        """Ephemeral workers have is_persistent == False."""
        w = self._make_worker(persistent=False)
        assert w.is_persistent is False

    def test_is_persistent_true_for_persistent_worker(self):
        """Persistent workers have is_persistent == True."""
        w = self._make_worker(persistent=True)
        assert w.is_persistent is True

    def test_agent_loop_property(self):
        """Worker.agent_loop returns the wrapped agent loop."""
        agent_loop = MagicMock()
        agent_loop._owner_worker = None
        w = Worker(
            worker_id="w",
            task="t",
            agent_loop=agent_loop,
            context=MagicMock(),
        )
        assert w.agent_loop is agent_loop

    def test_profile_name_in_info(self):
        """Worker with a profile binding exposes it via info.profile_name."""
        w = self._make_worker(profile_name="salesforce-prod")
        assert w.info.profile_name == "salesforce-prod"

    def test_id_attribute(self):
        """Worker.id matches the constructor argument."""
        w = self._make_worker(worker_id="w_99")
        assert w.id == "w_99"


# ---------------------------------------------------------------------------
# EventType
# ---------------------------------------------------------------------------


class TestEventType:
    """Spot-check that key EventType members exist and are strings."""

    def test_execution_lifecycle_events(self):
        """Core execution lifecycle events are defined."""
        assert EventType.EXECUTION_STARTED == "execution_started"
        assert EventType.EXECUTION_COMPLETED == "execution_completed"
        assert EventType.EXECUTION_FAILED == "execution_failed"

    def test_state_change_events(self):
        """State-change events are defined."""
        assert EventType.STATE_CHANGED == "state_changed"

    def test_goal_events(self):
        """Goal-tracking events are defined."""
        assert EventType.GOAL_PROGRESS == "goal_progress"
        assert EventType.GOAL_ACHIEVED == "goal_achieved"

    def test_event_type_is_string_comparable(self):
        """EventType members compare equal to plain strings."""
        assert str(EventType.EXECUTION_STARTED) == "execution_started"


# ---------------------------------------------------------------------------
# AgentEvent
# ---------------------------------------------------------------------------


class TestAgentEvent:
    """Tests for AgentEvent construction."""

    def _make_event(self, event_type=EventType.EXECUTION_STARTED, stream_id="s_1", **kwargs):
        from datetime import datetime
        return AgentEvent(
            type=event_type,
            stream_id=stream_id,
            data=kwargs.get("data", {}),
            timestamp=kwargs.get("timestamp", datetime.now()),
            **{k: v for k, v in kwargs.items() if k not in ("data", "timestamp")},
        )

    def test_minimal_construction(self):
        """AgentEvent can be built with required fields only."""
        from datetime import datetime
        event = AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id="s_1",
            data={"session_id": "s_1"},
            timestamp=datetime.now(),
        )
        assert event.type == EventType.EXECUTION_STARTED
        assert event.stream_id == "s_1"
        assert event.data["session_id"] == "s_1"

    def test_optional_fields_default_to_none(self):
        """node_id, execution_id, colony_id, run_id default to None."""
        event = self._make_event()
        assert event.node_id is None
        assert event.execution_id is None
        assert event.colony_id is None
        assert event.run_id is None

    def test_optional_fields_can_be_set(self):
        """Optional fields can be provided at construction."""
        event = self._make_event(
            node_id="n_1",
            execution_id="exec_42",
            colony_id="col_1",
        )
        assert event.node_id == "n_1"
        assert event.execution_id == "exec_42"
        assert event.colony_id == "col_1"


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


class TestEventBus:
    """Tests for EventBus subscribe / publish / unsubscribe."""

    def _make_event(self, event_type=EventType.EXECUTION_STARTED):
        from datetime import datetime
        return AgentEvent(
            type=event_type,
            stream_id="test_stream",
            data={},
            timestamp=datetime.now(),
        )

    @pytest.mark.asyncio
    async def test_subscriber_receives_matching_event(self):
        """A subscriber gets called when a matching event is published."""
        bus = EventBus()
        received: list[AgentEvent] = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe([EventType.EXECUTION_STARTED], handler)
        await bus.publish(self._make_event(EventType.EXECUTION_STARTED))

        assert len(received) == 1
        assert received[0].type == EventType.EXECUTION_STARTED

    @pytest.mark.asyncio
    async def test_subscriber_does_not_receive_different_event(self):
        """A subscriber registered for one type does not receive others."""
        bus = EventBus()
        received: list[AgentEvent] = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe([EventType.EXECUTION_STARTED], handler)
        await bus.publish(self._make_event(EventType.EXECUTION_COMPLETED))

        assert received == []

    @pytest.mark.asyncio
    async def test_unsubscribed_handler_not_called(self):
        """After unsubscribing by ID, the handler is no longer invoked."""
        bus = EventBus()
        received: list[AgentEvent] = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        sub_id = bus.subscribe([EventType.EXECUTION_STARTED], handler)
        bus.unsubscribe(sub_id)
        await bus.publish(self._make_event(EventType.EXECUTION_STARTED))

        assert received == []

    @pytest.mark.asyncio
    async def test_multiple_subscribers_all_called(self):
        """All subscribers for a given event type are called."""
        bus = EventBus()
        calls: list[int] = []

        async def h1(event: AgentEvent) -> None:
            calls.append(1)

        async def h2(event: AgentEvent) -> None:
            calls.append(2)

        bus.subscribe([EventType.STATE_CHANGED], h1)
        bus.subscribe([EventType.STATE_CHANGED], h2)
        await bus.publish(self._make_event(EventType.STATE_CHANGED))

        assert sorted(calls) == [1, 2]

    @pytest.mark.asyncio
    async def test_publish_with_no_subscribers_does_not_raise(self):
        """Publishing an event with no subscribers is a no-op."""
        bus = EventBus()
        # Must not raise
        await bus.publish(self._make_event(EventType.GOAL_ACHIEVED))


# ---------------------------------------------------------------------------
# SharedBufferManager
# ---------------------------------------------------------------------------


class TestSharedBufferManager:
    """Tests for SharedBufferManager buffer creation."""

    def test_create_buffer_returns_dict(self):
        """create_buffer returns a dict-like object."""
        mgr = SharedBufferManager()
        buf = mgr.create_buffer("exec_1", stream_id="stream_1")
        assert isinstance(buf, dict)

    def test_two_buffers_different_executions_are_isolated(self):
        """Buffers for different execution IDs are independent."""
        mgr = SharedBufferManager()
        buf_a = mgr.create_buffer("exec_a", stream_id="s")
        buf_b = mgr.create_buffer("exec_b", stream_id="s")
        buf_a["x"] = 1
        assert "x" not in buf_b

    def test_same_execution_returns_same_buffer(self):
        """Calling create_buffer twice for the same execution returns the same dict."""
        mgr = SharedBufferManager()
        buf1 = mgr.create_buffer("exec_1", stream_id="s")
        buf1["key"] = "value"
        buf2 = mgr.create_buffer("exec_1", stream_id="s")
        # Same buffer object — mutation in buf1 is visible via buf2
        assert buf2.get("key") == "value"
