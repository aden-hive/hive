"""
Tests for AuditLogger.
"""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from framework.runtime.audit import AuditLogger
from framework.runtime.event_bus import AgentEvent, EventBus, EventType


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for logs."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.mark.asyncio
async def test_audit_logger_writes_events(temp_log_dir):
    """Should write events to a JSONL file."""
    bus = EventBus()
    audit = AuditLogger(bus, log_dir=temp_log_dir)

    await audit.start()

    # Publish an event
    event = AgentEvent(
        type=EventType.EXECUTION_STARTED,
        stream_id="test_stream",
        execution_id="exec_1",
        data={"test": "data"},
    )

    await bus.publish(event)

    # Allow some time for async writing (aiofiles is awaited in the handler,
    # but we need to ensure it ran)
    # Since bus.publish awaits handlers, it should be done by now.

    await audit.stop()

    # Check file content
    log_files = list(Path(temp_log_dir).glob("audit_*.jsonl"))
    assert len(log_files) == 1

    content = log_files[0].read_text()
    lines = content.strip().split("\n")
    assert len(lines) == 1

    saved_event = json.loads(lines[0])
    assert saved_event["type"] == "execution_started"
    assert saved_event["stream_id"] == "test_stream"
    assert saved_event["data"] == {"test": "data"}


@pytest.mark.asyncio
async def test_audit_logger_rotates_files(temp_log_dir):
    """Should write to different files based on date."""
    # We'll mock datetime to simulate day change if needed,
    # but for simple test, just verifying the filename format is enough
    # or we can patch _get_log_file to return different paths

    bus = EventBus()
    audit = AuditLogger(bus, log_dir=temp_log_dir)
    await audit.start()

    # Mock date or filename
    path1 = Path(temp_log_dir) / "audit_2023-01-01.jsonl"
    path2 = Path(temp_log_dir) / "audit_2023-01-02.jsonl"

    with patch.object(audit, "_get_log_file", return_value=path1):
        await bus.publish(AgentEvent(EventType.CUSTOM, "s1", data={"id": 1}))

    with patch.object(audit, "_get_log_file", return_value=path2):
        await bus.publish(AgentEvent(EventType.CUSTOM, "s1", data={"id": 2}))

    await audit.stop()

    assert path1.exists()
    assert path2.exists()

    assert '"id": 1' in path1.read_text()
    assert '"id": 2' in path2.read_text()


@pytest.mark.asyncio
async def test_audit_logger_resilience(temp_log_dir):
    """Should not crash if writing fails."""
    bus = EventBus()
    audit = AuditLogger(bus, log_dir=temp_log_dir)
    await audit.start()

    # Mock aiofiles.open to raise exception
    with patch("aiofiles.open", side_effect=OSError("Disk full")):
        # Should not raise exception
        await bus.publish(AgentEvent(EventType.CUSTOM, "s1"))

    await audit.stop()
