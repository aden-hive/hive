"""Tests for the Sentinel manager's inbound routing + resume.

The outbound listeners and network I/O are not exercised here (see the plan's
test strategy); we drive ``on_inbound`` directly with fakes and assert the
reply reaches the parked queen via ``inject_event`` and the record resolves.
"""

from __future__ import annotations

import json

import pytest

import framework.sentinel.store as store_mod
from framework.sentinel import token
from framework.sentinel.manager import SentinelManager

# ----- fakes --------------------------------------------------------------


class _FakeNode:
    def __init__(self):
        self.injected: list[tuple[str, bool]] = []

    async def inject_event(self, content, *, is_client_input=False, **kwargs):
        self.injected.append((content, is_client_input))


class _FakeSession:
    def __init__(self, node, sse=0):
        self.queen_executor = type("Ex", (), {"node_registry": {"queen": node}})()
        self.sse_client_count = sse


class _FakeSM:
    def __init__(self, sessions):
        self._map = sessions
        self.created: list[dict] = []

    def get_live_session(self, sid):
        return self._map.get(sid)

    async def create_session(self, **kwargs):
        self.created.append(kwargs)
        return None


# ----- fixtures -----------------------------------------------------------


@pytest.fixture
def colonies(tmp_path, monkeypatch):
    root = tmp_path / "colonies"
    root.mkdir()
    monkeypatch.setattr(store_mod, "COLONIES_DIR", root)
    monkeypatch.setattr(store_mod, "get_hive_config", lambda: {"sentinel": {}})
    monkeypatch.setattr(token, "_cached_secret", b"0" * 32)
    return root


def _write_notifications(root, colony, allowlist):
    d = root / colony
    d.mkdir(parents=True, exist_ok=True)
    (d / "notifications.json").write_text(
        json.dumps({"sentinel_enabled": True, "channel": "telegram", "target": {"chat_id": "9"}, "allowlist": allowlist}),
        encoding="utf-8",
    )


def _open_record(colony="c1", esc="esc_1", session="s1"):
    tok = token.make_token(esc)
    rec = store_mod.EscalationRecord(
        escalation_id=esc,
        colony_id=colony,
        session_id=session,
        correlation_token=tok,
        park_reason="ask_user",
        question_text="continue?",
        channel="telegram",
        thread_ref={"message_id": 5},
    )
    store_mod.write_escalation(rec)
    return rec


# ----- tests --------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorized_reply_resumes_and_resolves(colonies):
    _write_notifications(colonies, "c1", allowlist=["42"])
    rec = _open_record()
    node = _FakeNode()
    mgr = SentinelManager(_FakeSM({"s1": _FakeSession(node)}))
    mgr._by_token[rec.correlation_token] = ("c1", "esc_1")

    text = f"yes go ahead {token.format_ref(rec.correlation_token)}"
    await mgr.on_inbound("telegram", "42", text, {"message_id": 5})

    assert node.injected == [("yes go ahead", True)]
    assert store_mod.load_escalation("c1", "esc_1").status == store_mod.STATUS_RESOLVED


@pytest.mark.asyncio
async def test_unauthorized_sender_ignored(colonies):
    _write_notifications(colonies, "c1", allowlist=["42"])
    rec = _open_record()
    node = _FakeNode()
    mgr = SentinelManager(_FakeSM({"s1": _FakeSession(node)}))
    mgr._by_token[rec.correlation_token] = ("c1", "esc_1")

    await mgr.on_inbound("telegram", "999", f"hi {token.format_ref(rec.correlation_token)}", {})

    assert node.injected == []
    assert store_mod.load_escalation("c1", "esc_1").status == store_mod.STATUS_OPEN


@pytest.mark.asyncio
async def test_ambiguous_reply_without_token_ignored(colonies):
    _write_notifications(colonies, "c1", allowlist=[])
    _open_record(colony="c1", esc="esc_1", session="s1")
    _open_record(colony="c2", esc="esc_2", session="s2")
    node = _FakeNode()
    mgr = SentinelManager(_FakeSM({"s1": _FakeSession(node), "s2": _FakeSession(node)}))

    await mgr.on_inbound("telegram", "42", "just continue", {})

    assert node.injected == []  # two open telegram escalations → can't disambiguate


@pytest.mark.asyncio
async def test_fallback_single_open_resolves(colonies):
    _write_notifications(colonies, "c1", allowlist=[])
    _open_record()
    node = _FakeNode()
    mgr = SentinelManager(_FakeSM({"s1": _FakeSession(node)}))

    await mgr.on_inbound("telegram", "42", "go", {"message_id": 5})

    assert node.injected == [("go", True)]


@pytest.mark.asyncio
async def test_resolved_record_not_reprocessed(colonies):
    _write_notifications(colonies, "c1", allowlist=[])
    rec = _open_record()
    store_mod.resolve_escalation("c1", "esc_1")
    node = _FakeNode()
    mgr = SentinelManager(_FakeSM({"s1": _FakeSession(node)}))
    mgr._by_token[rec.correlation_token] = ("c1", "esc_1")

    await mgr.on_inbound("telegram", "42", f"go {token.format_ref(rec.correlation_token)}", {})
    assert node.injected == []


@pytest.mark.asyncio
async def test_cold_restore_when_session_not_live(colonies):
    _write_notifications(colonies, "c1", allowlist=[])
    rec = _open_record()
    sm = _FakeSM({})  # session not in memory
    mgr = SentinelManager(sm)
    mgr._by_token[rec.correlation_token] = ("c1", "esc_1")

    await mgr.on_inbound("telegram", "42", f"go {token.format_ref(rec.correlation_token)}", {})
    # Cold-restore was attempted with the right resume target.
    assert sm.created == [{"colony_id": "c1", "queen_resume_from": "s1"}]


def test_has_attached_ui(colonies):
    node = _FakeNode()
    mgr = SentinelManager(_FakeSM({"s1": _FakeSession(node, sse=2), "s2": _FakeSession(node, sse=0)}))
    assert mgr.has_attached_ui("s1") is True
    assert mgr.has_attached_ui("s2") is False
    assert mgr.has_attached_ui("missing") is False


def test_enqueue_escalation_accepts(colonies):
    mgr = SentinelManager(_FakeSM({}))
    assert mgr.enqueue_escalation({"escalation_id": "e"}) is True


def test_format_message_blocker_vs_heartbeat_and_mrkdwn():
    mgr = SentinelManager(_FakeSM({}))
    base = {
        "colony_id": "c1",
        "correlation_token": token.make_token("esc_1"),
        "question_text": "Hit **5000** engagers?",
    }

    blocker = mgr._format_message({**base, "kind": "blocker"})
    assert "needs you" in blocker
    # **bold** → *bold* so Slack/Telegram render it instead of literal asterisks.
    assert "*5000*" in blocker and "**5000**" not in blocker

    heartbeat = mgr._format_message({**base, "kind": "heartbeat"})
    assert "still working" in heartbeat
    assert "redirect" in heartbeat.lower()
    assert "needs you" not in heartbeat


@pytest.mark.asyncio
async def test_on_local_resume_closes_open(colonies):
    _open_record(colony="c1", esc="esc_1", session="s1")
    mgr = SentinelManager(_FakeSM({}))
    await mgr.on_local_resume("s1")
    assert store_mod.load_escalation("c1", "esc_1").status == store_mod.STATUS_RESOLVED


@pytest.mark.asyncio
async def test_report_supersedes_prior_open_for_session(colonies, monkeypatch):
    # A new report for a session resolves any prior open one for that session,
    # so the inbox stays a live status rather than a pile of "open" rows.
    import framework.sentinel.notifier as notifier_mod

    _open_record(colony="c1", esc="esc_old", session="s1")  # e.g. a stale progress

    async def fake_send(*a, **k):
        return notifier_mod.NotifierResult(ok=True, message_id="m1")

    monkeypatch.setattr(notifier_mod, "send", fake_send)
    mgr = SentinelManager(_FakeSM({}))
    await mgr._handle_escalation(
        {
            "escalation_id": "esc_new",
            "colony_id": "c1",
            "session_id": "s1",
            "correlation_token": token.make_token("esc_new"),
            "kind": "progress",
            "question_text": "working on Y",
            "channel": "telegram",
            "target": {"chat_id": "1"},
            "thread": {},
        }
    )
    assert store_mod.load_escalation("c1", "esc_old").status == store_mod.STATUS_RESOLVED
    assert store_mod.load_escalation("c1", "esc_new").status == store_mod.STATUS_OPEN
    # A different session is untouched.
    _open_record(colony="c1", esc="esc_other", session="s2")
    assert store_mod.load_escalation("c1", "esc_other").status == store_mod.STATUS_OPEN
