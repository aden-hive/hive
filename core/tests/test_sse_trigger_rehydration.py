"""Regression test for the "only one trigger shows up" bug.

Trigger cards in the UI are rebuilt only from trigger_available/activated SSE
events, replayed from the EventBus history ring buffer on connect. On a chatty
colony that buffer overflows, so a trigger's activation (published once at load)
ages out before the client (re)connects — and only the most-recently-activated
trigger survives the replay. ``_authoritative_trigger_events`` rebuilds the full
set from ``session.available_triggers`` (the source of truth) so every connect
rehydrates ALL triggers regardless of history retention.
"""

from __future__ import annotations

from types import SimpleNamespace

from framework.host.triggers import TriggerDefinition, build_trigger_view
from framework.server.routes_events import _authoritative_trigger_events


def _session(triggers, active):
    return SimpleNamespace(
        available_triggers={t.id: t for t in triggers},
        active_trigger_ids=set(active),
        trigger_next_fire={},
        trigger_fire_stats={},
    )


def test_rehydrates_every_trigger_not_just_the_latest():
    # The exact bug shape: two active timers in one colony.
    slow = TriggerDefinition(id="li_slow_invite", trigger_type="timer", trigger_config={"interval_minutes": 5}, description="slow invite")
    poll = TriggerDefinition(id="li_followup_poll", trigger_type="timer", trigger_config={"interval_minutes": 120}, description="poll")
    session = _session([slow, poll], active={"li_slow_invite", "li_followup_poll"})

    events = _authoritative_trigger_events(session)

    ids = sorted(e["data"]["trigger_id"] for e in events)
    assert ids == ["li_followup_poll", "li_slow_invite"], "both triggers must rehydrate, not just one"
    assert all(e["type"] == "trigger_activated" for e in events), "active triggers render as running"
    # Each card carries its own name + config so the UI renders distinct cards.
    by_id = {e["data"]["trigger_id"]: e for e in events}
    assert by_id["li_slow_invite"]["data"]["name"] == "slow invite"
    assert by_id["li_followup_poll"]["data"]["trigger_config"]["interval_minutes"] == 120


def test_inactive_trigger_emitted_as_available():
    a = TriggerDefinition(id="a", trigger_type="timer", trigger_config={"interval_minutes": 5})
    b = TriggerDefinition(id="b", trigger_type="webhook", trigger_config={"path": "/x"})
    session = _session([a, b], active={"a"})

    by_id = {e["data"]["trigger_id"]: e for e in _authoritative_trigger_events(session)}

    assert by_id["a"]["type"] == "trigger_activated"  # active -> running
    assert by_id["b"]["type"] == "trigger_available"  # inactive -> pending


def test_fire_stats_and_next_fire_merged_into_config():
    t = TriggerDefinition(id="t", trigger_type="timer", trigger_config={"interval_minutes": 10})
    session = _session([t], active={"t"})
    session.trigger_next_fire = {"t": __import__("time").monotonic() + 30}
    session.trigger_fire_stats = {"t": {"fire_count": 7, "last_fired_at": 1700000000000}}

    cfg = _authoritative_trigger_events(session)[0]["data"]["trigger_config"]

    assert cfg["fire_count"] == 7
    assert cfg["last_fired_at"] == 1700000000000
    assert cfg["next_fire_at"] > 0 and cfg["next_fire_in"] > 0


def test_empty_when_no_triggers():
    assert _authoritative_trigger_events(_session([], active=set())) == []


# --- build_trigger_view: the REST trigger API projection -------------------


def test_view_lists_every_trigger_with_enabled_status():
    active = TriggerDefinition(
        id="li_followup_poll",
        trigger_type="timer",
        trigger_config={"interval_minutes": 120},
        description="poll",
        task="run li_poll",
    )
    inactive = TriggerDefinition(
        id="li_slow_invite",
        trigger_type="timer",
        trigger_config={"interval_minutes": 5},
        description="slow invite",
        task="run li_invite",
    )
    session = _session([active, inactive], active={"li_followup_poll"})

    view = {t["trigger_id"]: t for t in build_trigger_view(session)}

    assert set(view) == {"li_followup_poll", "li_slow_invite"}  # both, regardless of SSE history
    assert view["li_followup_poll"]["enabled"] is True
    assert view["li_slow_invite"]["enabled"] is False  # deactivated, still listed
    assert view["li_followup_poll"]["task"] == "run li_poll"
    assert view["li_followup_poll"]["name"] == "poll"


def test_view_merges_next_fire_and_stats():
    t = TriggerDefinition(id="t", trigger_type="timer", trigger_config={"interval_minutes": 10})
    session = _session([t], active={"t"})
    session.trigger_next_fire = {"t": __import__("time").monotonic() + 30}
    session.trigger_fire_stats = {"t": {"fire_count": 4, "last_fired_at": 1700000000000}}

    cfg = build_trigger_view(session)[0]["trigger_config"]

    assert cfg["fire_count"] == 4
    assert cfg["last_fired_at"] == 1700000000000
    assert cfg["next_fire_at"] > 0 and cfg["next_fire_in"] > 0


def test_view_empty_when_no_triggers():
    assert build_trigger_view(_session([], active=set())) == []
