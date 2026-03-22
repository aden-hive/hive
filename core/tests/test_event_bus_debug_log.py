"""Tests for EventBus debug log race condition fix.

Validates that the _EventDebugLog singleton initializes exactly once under
concurrent access, properly cleans up file handles, and does not create
files when debug mode is disabled.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from framework.runtime.event_bus import (
    AgentEvent,
    EventBus,
    EventType,
    _EventDebugLog,
)


@pytest.fixture(autouse=True)
def _reset_debug_log():
    """Ensure clean singleton state for each test."""
    _EventDebugLog.reset()
    yield
    _EventDebugLog.reset()


class TestEventDebugLogSingleton:
    """Verify the _EventDebugLog singleton initializes safely."""

    @pytest.mark.asyncio
    async def test_singleton_returns_same_instance(self):
        """Multiple calls to get() must return the same instance."""
        with (
            patch("framework.runtime.event_bus._DEBUG_EVENTS_ENABLED", True),
            patch(
                "framework.runtime.event_bus._open_event_log",
                return_value=None,
            ),
        ):
            inst1 = await _EventDebugLog.get()
            inst2 = await _EventDebugLog.get()
            assert inst1 is inst2

    @pytest.mark.asyncio
    async def test_concurrent_get_initializes_once(self):
        """Concurrent get() calls must only open the log file once."""
        open_count = 0

        def counting_open():
            nonlocal open_count
            open_count += 1
            return None

        with (
            patch("framework.runtime.event_bus._DEBUG_EVENTS_ENABLED", True),
            patch(
                "framework.runtime.event_bus._open_event_log",
                side_effect=counting_open,
            ),
        ):
            # Launch many concurrent get() calls
            tasks = [asyncio.create_task(_EventDebugLog.get()) for _ in range(20)]
            instances = await asyncio.gather(*tasks)

            # All must be the same instance
            assert all(inst is instances[0] for inst in instances)
            # _open_event_log called exactly once
            assert open_count == 1

    @pytest.mark.asyncio
    async def test_reset_allows_reinitialisation(self):
        """After reset(), the next get() creates a fresh instance."""
        with (
            patch("framework.runtime.event_bus._DEBUG_EVENTS_ENABLED", True),
            patch(
                "framework.runtime.event_bus._open_event_log",
                return_value=None,
            ),
        ):
            inst1 = await _EventDebugLog.get()
            _EventDebugLog.reset()
            inst2 = await _EventDebugLog.get()
            assert inst1 is not inst2


class TestEventDebugLogWriteAndClose:
    """Verify write_event and close behaviour."""

    @pytest.mark.asyncio
    async def test_write_event_to_file(self, tmp_path: Path):
        """Events are serialised as JSONL to the underlying file."""
        log_path = tmp_path / "events.jsonl"
        fh = open(log_path, "a", encoding="utf-8")

        with (
            patch("framework.runtime.event_bus._DEBUG_EVENTS_ENABLED", True),
            patch(
                "framework.runtime.event_bus._open_event_log",
                return_value=fh,
            ),
        ):
            debug_log = await _EventDebugLog.get()

            event = AgentEvent(
                type=EventType.EXECUTION_STARTED,
                stream_id="test-stream",
                data={"info": "hello"},
            )
            debug_log.write_event(event)

        fh.close()

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["type"] == "execution_started"
        assert parsed["stream_id"] == "test-stream"

    @pytest.mark.asyncio
    async def test_write_event_noop_when_file_is_none(self):
        """write_event must not raise when file handle is None."""
        with (
            patch("framework.runtime.event_bus._DEBUG_EVENTS_ENABLED", True),
            patch(
                "framework.runtime.event_bus._open_event_log",
                return_value=None,
            ),
        ):
            debug_log = await _EventDebugLog.get()
            event = AgentEvent(
                type=EventType.EXECUTION_STARTED,
                stream_id="s",
                data={},
            )
            # Should not raise
            debug_log.write_event(event)

    @pytest.mark.asyncio
    async def test_close_closes_file_handle(self, tmp_path: Path):
        """close() must close the underlying file handle."""
        log_path = tmp_path / "events.jsonl"
        fh = open(log_path, "a", encoding="utf-8")

        with (
            patch("framework.runtime.event_bus._DEBUG_EVENTS_ENABLED", True),
            patch(
                "framework.runtime.event_bus._open_event_log",
                return_value=fh,
            ),
        ):
            debug_log = await _EventDebugLog.get()
            debug_log.close()
            assert fh.closed


class TestEventBusDebugIntegration:
    """Integration: EventBus.publish() uses the debug log correctly."""

    @pytest.mark.asyncio
    async def test_publish_writes_to_debug_log(self, tmp_path: Path):
        """publish() should write to the debug log when enabled."""
        log_path = tmp_path / "events.jsonl"
        fh = open(log_path, "a", encoding="utf-8")

        with (
            patch("framework.runtime.event_bus._DEBUG_EVENTS_ENABLED", True),
            patch(
                "framework.runtime.event_bus._open_event_log",
                return_value=fh,
            ),
        ):
            bus = EventBus()
            event = AgentEvent(
                type=EventType.EXECUTION_STARTED,
                stream_id="bus-test",
                data={"step": 1},
            )
            await bus.publish(event)

        fh.close()

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        assert "bus-test" in lines[0]

    @pytest.mark.asyncio
    async def test_publish_skips_debug_when_disabled(self):
        """publish() must not touch the debug log when disabled."""
        with patch("framework.runtime.event_bus._DEBUG_EVENTS_ENABLED", False):
            bus = EventBus()
            event = AgentEvent(
                type=EventType.EXECUTION_STARTED,
                stream_id="s",
                data={},
            )
            # Should not raise or create any file
            await bus.publish(event)
            assert _EventDebugLog._instance is None

    @pytest.mark.asyncio
    async def test_close_session_log_resets_debug_log(self, tmp_path: Path):
        """close_session_log() should also reset the debug log singleton."""
        with (
            patch("framework.runtime.event_bus._DEBUG_EVENTS_ENABLED", True),
            patch(
                "framework.runtime.event_bus._open_event_log",
                return_value=None,
            ),
        ):
            bus = EventBus()
            await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="s", data={}))
            assert _EventDebugLog._instance is not None

            bus.close_session_log()
            assert _EventDebugLog._instance is None
