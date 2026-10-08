"""Tests for ``compute_missed`` and ``resolve_missed``.

These two functions support the missed-trigger handshake: on session
load, if any persisted trigger's ``last_fired_at`` is older than its
schedule expects, the UI is told (``MISSED_TRIGGERS`` event) and lets
the user pick what to do per trigger via the ``resolve_missed`` HTTP
endpoint.

``compute_missed`` is pure. ``resolve_missed`` is exercised here with
a hand-rolled session double instead of a real Session — the real
class needs an LLM/runner this test doesn't want to stand up.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import framework.config as _cfg
from framework.host.event_bus import EventBus
from framework.host.triggers import MissedTrigger, TriggerDefinition, compute_missed
from framework.tools.queen_lifecycle_tools import resolve_missed


def _trig(
    *,
    tid: str = "t",
    ttype: str = "timer",
    config: dict | None = None,
    enabled: bool = True,
    last_fired_at: str | None = None,
) -> dict:
    return {
        "id": tid,
        "name": tid,
        "trigger_type": ttype,
        "trigger_config": config or {},
        "task": "do it",
        "enabled": enabled,
        "last_fired_at": last_fired_at,
        "next_due_at": None,
    }


# ---------------------------------------------------------------------------
# compute_missed: cron triggers
# ---------------------------------------------------------------------------


def test_compute_missed_cron_counts_ticks_between_last_fired_and_now() -> None:
    """Cron '0 9 * * 1-5' (9am weekdays UTC). Fired Mon 9am, now Thu 10am.
    Missed: Tue 9am, Wed 9am, Thu 9am = 3."""
    triggers = [
        _trig(
            ttype="timer",
            config={"cron": "0 9 * * 1-5"},
            last_fired_at="2026-05-18T09:00:00+00:00",  # Mon
        )
    ]
    now = datetime(2026, 5, 21, 10, 0, tzinfo=UTC)  # Thu 10am
    missed = compute_missed(triggers, now=now)
    assert len(missed) == 1
    assert missed[0].count == 3
    assert missed[0].ticks == [
        "2026-05-19T09:00:00+00:00",
        "2026-05-20T09:00:00+00:00",
        "2026-05-21T09:00:00+00:00",
    ]
    # next_due is the first cron match strictly after now → Fri 9am
    assert missed[0].next_due_at == "2026-05-22T09:00:00+00:00"


def test_compute_missed_cron_zero_when_no_full_tick_elapsed() -> None:
    """If now is mid-period between fires, count is 0 and trigger is
    omitted from the result entirely (no point bothering the user)."""
    triggers = [
        _trig(
            ttype="timer",
            config={"cron": "0 9 * * *"},
            last_fired_at="2026-05-21T09:00:00+00:00",
        )
    ]
    now = datetime(2026, 5, 21, 15, 0, tzinfo=UTC)  # same day afternoon
    missed = compute_missed(triggers, now=now)
    assert missed == []


# ---------------------------------------------------------------------------
# compute_missed: interval triggers
# ---------------------------------------------------------------------------


def test_compute_missed_interval_floors_division() -> None:
    """interval_minutes=60 with 3h25m gap → 3 missed ticks."""
    triggers = [
        _trig(
            ttype="timer",
            config={"interval_minutes": 60},
            last_fired_at="2026-05-21T09:00:00+00:00",
        )
    ]
    now = datetime(2026, 5, 21, 12, 25, tzinfo=UTC)
    missed = compute_missed(triggers, now=now)
    assert len(missed) == 1
    assert missed[0].count == 3
    # next_due = since + step * (count + 1) = 09:00 + 4h = 13:00
    assert missed[0].next_due_at == "2026-05-21T13:00:00+00:00"


def test_compute_missed_interval_zero_when_under_one_step() -> None:
    triggers = [
        _trig(
            ttype="timer",
            config={"interval_minutes": 60},
            last_fired_at="2026-05-21T09:00:00+00:00",
        )
    ]
    now = datetime(2026, 5, 21, 9, 30, tzinfo=UTC)
    assert compute_missed(triggers, now=now) == []


# ---------------------------------------------------------------------------
# compute_missed: edge cases
# ---------------------------------------------------------------------------


def test_compute_missed_skips_disabled_triggers() -> None:
    triggers = [
        _trig(
            ttype="timer",
            config={"interval_minutes": 5},
            enabled=False,
            last_fired_at="2026-05-01T00:00:00+00:00",
        )
    ]
    now = datetime(2026, 5, 21, 0, 0, tzinfo=UTC)
    assert compute_missed(triggers, now=now) == []


def test_compute_missed_skips_webhook_triggers() -> None:
    """Webhook triggers are event-driven; missed events can't be
    reconstructed from a schedule. Always omit from the handshake."""
    triggers = [
        _trig(
            ttype="webhook",
            config={"path": "/hooks/x"},
            last_fired_at="2026-05-01T00:00:00+00:00",
        )
    ]
    now = datetime(2026, 5, 21, 0, 0, tzinfo=UTC)
    assert compute_missed(triggers, now=now) == []


def test_compute_missed_skips_never_fired_triggers() -> None:
    """A trigger with last_fired_at=None has no anchor — we don't
    retroactively fire for the period before it was set up."""
    triggers = [
        _trig(
            ttype="timer",
            config={"interval_minutes": 5},
            last_fired_at=None,
        )
    ]
    now = datetime(2026, 5, 21, 0, 0, tzinfo=UTC)
    assert compute_missed(triggers, now=now) == []


def test_compute_missed_handles_invalid_cron_gracefully() -> None:
    triggers = [
        _trig(
            ttype="timer",
            config={"cron": "not-a-cron"},
            last_fired_at="2026-05-01T00:00:00+00:00",
        )
    ]
    now = datetime(2026, 5, 21, 0, 0, tzinfo=UTC)
    assert compute_missed(triggers, now=now) == []


def test_compute_missed_caps_reported_ticks_at_100() -> None:
    """Very tight cron over a long gap could enumerate thousands of
    ticks. ``count`` stays accurate; ``ticks`` list is bounded so the
    SSE event payload doesn't balloon."""
    triggers = [
        _trig(
            ttype="timer",
            config={"cron": "* * * * *"},
            last_fired_at="2026-05-01T00:00:00+00:00",
        )
    ]
    now = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)
    missed = compute_missed(triggers, now=now)
    assert len(missed) == 1
    assert missed[0].count == 14400
    assert len(missed[0].ticks) == 100  # capped


def test_missed_trigger_to_dict_shape() -> None:
    m = MissedTrigger(trigger_id="x", trigger_type="timer", count=2, ticks=["a", "b"], next_due_at="c")
    assert m.to_dict() == {
        "trigger_id": "x",
        "trigger_type": "timer",
        "count": 2,
        "ticks": ["a", "b"],
        "next_due_at": "c",
    }


# ---------------------------------------------------------------------------
# resolve_missed: handshake decision handlers
# ---------------------------------------------------------------------------


def _seed_colony(colony_id: str, triggers: list[dict]) -> Path:
    """Create a colony directory with metadata.json + triggers.json."""
    colony_dir = _cfg.COLONIES_DIR / colony_id
    colony_dir.mkdir(parents=True, exist_ok=True)
    (colony_dir / "metadata.json").write_text(
        json.dumps({"name": colony_id}),
        encoding="utf-8",
    )
    (colony_dir / "triggers.json").write_text(json.dumps(triggers, indent=2), encoding="utf-8")
    return colony_dir


def _make_session(colony_id: str, colony_dir: Path):
    """Hand-rolled session double exposing the surface ``resolve_missed`` reads."""
    queen_node = SimpleNamespace(inject_trigger=AsyncMock())
    executor = SimpleNamespace(node_registry={"queen": queen_node})
    return SimpleNamespace(
        id="sess1",
        colony_id=colony_id,
        worker_path=colony_dir,
        event_bus=EventBus(),
        available_triggers={},
        active_trigger_ids=set(),
        active_timer_tasks={},
        active_webhook_subs={},
        trigger_next_fire={},
        trigger_fire_stats={},
        queen_executor=executor,
    )


@pytest.mark.asyncio
async def test_resolve_missed_fire_latest_injects_catch_up(tmp_path) -> None:
    colony_dir = _seed_colony(
        "colD",
        triggers=[
            {
                "id": "z",
                "name": "z",
                "trigger_type": "timer",
                "trigger_config": {"cron": "0 9 * * *"},
                "task": "send invites",
                "enabled": True,
                "last_fired_at": "2026-05-18T09:00:00+00:00",
                "next_due_at": None,
            }
        ],
    )
    session = _make_session("colD", colony_dir)
    session.available_triggers["z"] = TriggerDefinition(
        id="z",
        trigger_type="timer",
        trigger_config={"cron": "0 9 * * *"},
        task="send invites",
        enabled=True,
        last_fired_at="2026-05-18T09:00:00+00:00",
    )

    results = await resolve_missed(session, {"z": "fire_latest"})

    assert results == {"z": "fired"}
    queen_node = session.queen_executor.node_registry["queen"]
    assert queen_node.inject_trigger.await_count == 1
    payload = queen_node.inject_trigger.await_args_list[0].args[0].payload
    assert payload.get("catch_up") is True
    assert session.available_triggers["z"].last_fired_at != "2026-05-18T09:00:00+00:00"


@pytest.mark.asyncio
async def test_resolve_missed_skip_advances_anchor_without_firing(tmp_path) -> None:
    colony_dir = _seed_colony(
        "colE",
        triggers=[
            {
                "id": "z",
                "name": "z",
                "trigger_type": "timer",
                "trigger_config": {"interval_minutes": 60},
                "task": "go",
                "enabled": True,
                "last_fired_at": "2026-01-01T00:00:00+00:00",
                "next_due_at": None,
            }
        ],
    )
    session = _make_session("colE", colony_dir)
    session.available_triggers["z"] = TriggerDefinition(
        id="z",
        trigger_type="timer",
        trigger_config={"interval_minutes": 60},
        task="go",
        enabled=True,
        last_fired_at="2026-01-01T00:00:00+00:00",
    )

    results = await resolve_missed(session, {"z": "skip"})

    assert results == {"z": "skipped"}
    queen_node = session.queen_executor.node_registry["queen"]
    assert queen_node.inject_trigger.await_count == 0
    assert session.available_triggers["z"].last_fired_at != "2026-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_resolve_missed_reschedule_sets_future_next_due(tmp_path) -> None:
    colony_dir = _seed_colony(
        "colF",
        triggers=[
            {
                "id": "z",
                "name": "z",
                "trigger_type": "timer",
                "trigger_config": {"cron": "0 9 * * *"},
                "task": "go",
                "enabled": True,
                "last_fired_at": "2026-01-01T00:00:00+00:00",
                "next_due_at": None,
            }
        ],
    )
    session = _make_session("colF", colony_dir)
    session.available_triggers["z"] = TriggerDefinition(
        id="z",
        trigger_type="timer",
        trigger_config={"cron": "0 9 * * *"},
        task="go",
        enabled=True,
        last_fired_at="2026-01-01T00:00:00+00:00",
    )

    results = await resolve_missed(session, {"z": "reschedule"})
    assert results == {"z": "rescheduled"}
    queen_node = session.queen_executor.node_registry["queen"]
    assert queen_node.inject_trigger.await_count == 0
    next_due = session.available_triggers["z"].next_due_at
    assert next_due is not None
    parsed = datetime.fromisoformat(next_due.replace("Z", "+00:00"))
    assert parsed > datetime.now(tz=UTC)


@pytest.mark.asyncio
async def test_resolve_missed_unknown_trigger_returns_marker(tmp_path) -> None:
    _seed_colony("colG", triggers=[])
    session = _make_session("colG", _cfg.COLONIES_DIR / "colG")
    results = await resolve_missed(session, {"ghost": "fire_latest"})
    assert results == {"ghost": "unknown_trigger"}


@pytest.mark.asyncio
async def test_resolve_missed_invalid_decision_returns_marker(tmp_path) -> None:
    colony_dir = _seed_colony(
        "colH",
        triggers=[
            {
                "id": "z",
                "name": "z",
                "trigger_type": "timer",
                "trigger_config": {"interval_minutes": 5},
                "task": "go",
                "enabled": True,
                "last_fired_at": "2026-01-01T00:00:00+00:00",
                "next_due_at": None,
            }
        ],
    )
    session = _make_session("colH", colony_dir)
    session.available_triggers["z"] = TriggerDefinition(
        id="z",
        trigger_type="timer",
        trigger_config={"interval_minutes": 5},
        last_fired_at="2026-01-01T00:00:00+00:00",
    )
    results = await resolve_missed(session, {"z": "explode"})
    assert results["z"].startswith("invalid_decision")
