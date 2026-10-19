"""Tests for trigger persistence fields (last_fired_at, next_due_at).

The activation-missed-triggers handshake relies on these two fields
surviving a server restart. This test pins the round-trip contract:
fields written by ``_save_trigger_to_agent`` must be readable by
``_read_agent_triggers_json`` and rehydrated into ``TriggerDefinition``
by the session-load path in ``session_manager``.
"""

from __future__ import annotations

from pathlib import Path

from framework.host.triggers import TriggerDefinition
from framework.tools.queen_lifecycle_tools import (
    _read_agent_triggers_json,
    _save_trigger_to_agent,
)


class _FakeSession:
    """Minimal stand-in for the bits ``_save_trigger_to_agent`` reads."""

    def __init__(self, worker_path: Path) -> None:
        self.worker_path = worker_path


def test_trigger_definition_defaults_last_and_next_to_none() -> None:
    tdef = TriggerDefinition(
        id="t1",
        trigger_type="timer",
        trigger_config={"cron": "*/5 * * * *"},
    )
    assert tdef.last_fired_at is None
    assert tdef.next_due_at is None


def test_save_trigger_round_trips_last_and_next(tmp_path: Path) -> None:
    """A TriggerDefinition with last_fired_at and next_due_at must round-trip
    through triggers.json. Without this, the activation-missed-triggers
    handshake cannot reconstruct what would have fired during a gap.
    """
    agent_path = tmp_path / "agent"
    agent_path.mkdir()
    session = _FakeSession(worker_path=agent_path)

    tdef = TriggerDefinition(
        id="daily_outreach",
        trigger_type="timer",
        trigger_config={"cron": "0 9 * * 1-5"},
        description="Daily LinkedIn outreach",
        task="Send today's 10 invites.",
        enabled=True,
        last_fired_at="2026-05-22T16:00:00Z",
        next_due_at="2026-05-25T16:00:00Z",
    )

    _save_trigger_to_agent(session, "daily_outreach", tdef)

    raw = _read_agent_triggers_json(agent_path)
    assert len(raw) == 1
    entry = raw[0]
    assert entry["last_fired_at"] == "2026-05-22T16:00:00Z"
    assert entry["next_due_at"] == "2026-05-25T16:00:00Z"
    # Per-trigger flag is now ``enabled`` (was ``active`` pre-2026-05).
    assert entry["enabled"] is True
    assert entry["task"] == "Send today's 10 invites."


def test_save_trigger_writes_none_for_unset_timestamps(tmp_path: Path) -> None:
    """Newly-created triggers (never fired) persist as null timestamps.
    The session-load path treats null as "no missed math possible yet"."""
    agent_path = tmp_path / "agent"
    agent_path.mkdir()
    session = _FakeSession(worker_path=agent_path)

    tdef = TriggerDefinition(
        id="fresh",
        trigger_type="timer",
        trigger_config={"interval_minutes": 5},
    )

    _save_trigger_to_agent(session, "fresh", tdef)

    raw = _read_agent_triggers_json(agent_path)
    assert raw[0]["last_fired_at"] is None
    assert raw[0]["next_due_at"] is None
