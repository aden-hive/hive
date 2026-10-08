"""Tests for Sentinel on-disk config + escalation records (framework.sentinel.store)."""

from __future__ import annotations

import json

import pytest

from framework.sentinel import store


@pytest.fixture
def colonies(tmp_path, monkeypatch):
    """Point COLONIES_DIR at a temp dir and reset the global sentinel config."""
    root = tmp_path / "colonies"
    root.mkdir()
    monkeypatch.setattr(store, "COLONIES_DIR", root)
    monkeypatch.setattr(store, "get_hive_config", lambda: {"sentinel": {}})
    return root


def _write_notifications(root, colony_id: str, data: dict) -> None:
    d = root / colony_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "notifications.json").write_text(json.dumps(data), encoding="utf-8")


# ----- global config ------------------------------------------------------


def test_classify_after_seconds_default_and_override(monkeypatch):
    monkeypatch.setattr(store, "get_hive_config", lambda: {})
    assert store.classify_after_seconds() == 300.0
    monkeypatch.setattr(store, "get_hive_config", lambda: {"sentinel": {"classify_after_seconds": 60}})
    assert store.classify_after_seconds() == 60.0


# ----- per-colony notifications config -------------------------------------


def test_notifications_enabled_by_default_via_hive(colonies):
    # A colony with no config defaults to the built-in Hive Inbox channel,
    # enabled: Hive is always connected for a signed-in account, so Sentinel is
    # on by default and every colony has somewhere to escalate. (Telegram/Slack
    # remain explicit opt-ins that need a token.)
    cfg = store.load_notifications_config("c1")
    assert cfg.sentinel_enabled is True
    assert cfg.channel == "hive"


def test_notifications_enabled_reads_per_colony_opt_in(colonies):
    _write_notifications(colonies, "c1", {"sentinel_enabled": True, "channel": "telegram", "target": {"chat_id": "9"}, "allowlist": ["42"]})
    cfg = store.load_notifications_config("c1")
    assert cfg.sentinel_enabled is True
    assert cfg.channel == "telegram"
    assert cfg.target == {"chat_id": "9"}
    assert cfg.allowlist == ["42"]


def test_update_notifications_config_writes_and_merges(colonies):
    (colonies / "c1").mkdir()
    store.update_notifications_config(
        "c1",
        sentinel_enabled=True,
        channel="telegram",
        target={"chat_id": "9"},
        allowlist=["42", 7],
    )
    cfg = store.load_notifications_config("c1")
    assert cfg.sentinel_enabled is True
    assert cfg.channel == "telegram"
    assert cfg.target == {"chat_id": "9"}
    assert cfg.allowlist == ["42", "7"]  # coerced to strings

    # A later thread update must preserve the saved settings.
    store.update_notifications_thread("c1", {"message_id": 5})
    cfg = store.load_notifications_config("c1")
    assert cfg.thread == {"message_id": 5}
    assert cfg.sentinel_enabled is True
    assert cfg.channel == "telegram"


def test_per_colony_classify_after_seconds_round_trip(colonies):
    (colonies / "c1").mkdir()
    # Unset by default → inherit global (None).
    store.update_notifications_config(
        "c1",
        sentinel_enabled=True,
        channel="slack",
        target={"channel": "C1"},
        allowlist=["U1"],
    )
    assert store.load_notifications_config("c1").classify_after_seconds is None

    # Set a per-colony override; persisted and clamped to the >=1s floor.
    store.update_notifications_config(
        "c1",
        sentinel_enabled=True,
        channel="slack",
        target={"channel": "C1"},
        allowlist=["U1"],
        classify_after_seconds=300.0,
    )
    assert store.load_notifications_config("c1").classify_after_seconds == 300.0

    # Passing None again clears the override back to inherit-global.
    store.update_notifications_config(
        "c1",
        sentinel_enabled=True,
        channel="slack",
        target={"channel": "C1"},
        allowlist=["U1"],
        classify_after_seconds=None,
    )
    assert store.load_notifications_config("c1").classify_after_seconds is None


def test_update_notifications_config_missing_colony(colonies):
    import pytest as _pytest

    with _pytest.raises(FileNotFoundError):
        store.update_notifications_config("ghost", sentinel_enabled=True, channel="telegram", target={}, allowlist=[])


def test_update_thread_preserves_settings(colonies):
    _write_notifications(colonies, "c1", {"sentinel_enabled": True, "channel": "slack", "target": {"channel": "C1"}, "allowlist": ["U1"]})
    store.update_notifications_thread("c1", {"ts": "123.456"})
    cfg = store.load_notifications_config("c1")
    assert cfg.thread == {"ts": "123.456"}
    assert cfg.sentinel_enabled is True
    assert cfg.allowlist == ["U1"]


# ----- escalation records -------------------------------------------------


def _record(colony="c1", esc="esc_1") -> store.EscalationRecord:
    return store.EscalationRecord(
        escalation_id=esc,
        colony_id=colony,
        session_id="s1",
        correlation_token="tok",
        park_reason="ask_user",
        question_text="shall I continue?",
        channel="telegram",
        thread_ref={"message_id": 5},
    )


def test_write_load_round_trip(colonies):
    rec = _record()
    store.write_escalation(rec)
    loaded = store.load_escalation("c1", "esc_1")
    assert loaded is not None
    assert loaded.escalation_id == "esc_1"
    assert loaded.question_text == "shall I continue?"
    assert loaded.thread_ref == {"message_id": 5}
    assert loaded.status == store.STATUS_OPEN


def test_list_open_only_returns_open(colonies):
    store.write_escalation(_record(esc="esc_1"))
    store.write_escalation(_record(esc="esc_2"))
    store.resolve_escalation("c1", "esc_2")
    open_ids = {r.escalation_id for r in store.list_open("c1")}
    assert open_ids == {"esc_1"}


def test_list_all_open_across_colonies(colonies):
    store.write_escalation(_record(colony="c1", esc="esc_1"))
    store.write_escalation(_record(colony="c2", esc="esc_2"))
    ids = {r.escalation_id for r in store.list_all_open()}
    assert ids == {"esc_1", "esc_2"}


def test_resolve_is_idempotent(colonies):
    store.write_escalation(_record())
    assert store.resolve_escalation("c1", "esc_1", resolved_by="42") is True
    assert store.resolve_escalation("c1", "esc_1") is False  # already resolved
    rec = store.load_escalation("c1", "esc_1")
    assert rec.status == store.STATUS_RESOLVED
    assert rec.resolved_by == "42"


def test_resolve_missing_returns_false(colonies):
    assert store.resolve_escalation("c1", "nope") is False
