"""Turn context: installed packages put text in front of a queen before each of her turns."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import framework.config as hive_config
from framework.agent_loop.reminders import ReminderHub, ReminderPoint
from framework.agent_loop.turn_context_reminder import TurnContextReminderSource
from framework.server import turn_context as tc


class FakeContext:
    def __init__(self, host, reply="", *, delay=0.0, error=None, fail_start=False):
        self.host, self.reply, self.delay, self.error, self.fail_start = host, reply, delay, error, fail_start
        self.asked: list[tuple[str, str]] = []
        self.stopped = False

    async def start(self):
        if self.fail_start:
            raise RuntimeError("model missing")

    async def stop(self):
        self.stopped = True

    async def context(self, queen_id, message):
        self.asked.append((queen_id, message))
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.reply


def _entry_point(factory):
    return SimpleNamespace(load=lambda: factory)


@pytest.fixture(autouse=True)
def _nothing_running():
    tc._running.clear()
    yield
    tc._running.clear()


def _install(monkeypatch, settings, **factories):
    built: dict[str, FakeContext] = {}

    def make(name, factory):
        def build(host):
            built[name] = factory(host)
            return built[name]

        return build

    monkeypatch.setattr(tc, "_installed", lambda: {n: _entry_point(make(n, f)) for n, f in factories.items()})
    monkeypatch.setattr(hive_config, "get_hive_config", lambda: {"turn_context": settings})
    return built


def _queen(provider):
    return SimpleNamespace(is_queen_stream=True, turn_context_provider=provider)


@pytest.mark.asyncio
async def test_an_enabled_package_gets_its_settings_and_its_text_reaches_the_queen(monkeypatch):
    built = _install(
        monkeypatch,
        {"voice": {"enabled": True, "k": 3}, "other": {"enabled": False}},
        voice=lambda host: FakeContext(host, "<voice_examples>…</voice_examples>"),
        other=lambda host: FakeContext(host, "never"),
        unconfigured=lambda host: FakeContext(host, "never"),
    )
    await tc.start_turn_context({})

    hub = ReminderHub()
    hub.register(TurnContextReminderSource())
    # What the queen orchestrator wires: the session's queen, not its directory.
    session = SimpleNamespace(queen_name="queen_x", queen_dir="queens/queen_x/sessions/session_20260101_000000_abcd1234")
    block = await hub.fire(ReminderPoint.USER_PROMPT_SUBMIT, _queen(tc.for_session(session)), user_text="今天有点累")
    await tc.stop_turn_context({})

    assert list(built) == ["voice"]
    assert (built["voice"].host.name, built["voice"].host.config) == ("voice", {"enabled": True, "k": 3})
    assert built["voice"].asked == [("queen_x", "今天有点累")]
    assert block is not None and "<voice_examples>…</voice_examples>" in block
    assert built["voice"].stopped and tc._running == {}


@pytest.mark.asyncio
async def test_a_slow_or_failing_package_is_skipped_for_the_turn(monkeypatch):
    _install(
        monkeypatch,
        {"slow": {"enabled": True}, "broken": {"enabled": True}, "good": {"enabled": True}, "quiet": {"enabled": True}},
        slow=lambda host: FakeContext(host, "late", delay=1.0),
        broken=lambda host: FakeContext(host, error=ValueError("index corrupt")),
        good=lambda host: FakeContext(host, "on time"),
        quiet=lambda host: FakeContext(host, None),
    )
    monkeypatch.setattr(tc, "CONTEXT_TIMEOUT_S", 0.05)
    await tc.start_turn_context({})

    assert await tc.context_for("queen_x", "hi") == "on time"


@pytest.mark.asyncio
async def test_a_package_that_fails_to_start_is_left_out(monkeypatch):
    _install(
        monkeypatch,
        {"voice": {"enabled": True}},
        voice=lambda host: FakeContext(host, "never", fail_start=True),
    )
    await tc.start_turn_context({})

    assert tc._running == {}
    assert await tc.context_for("queen_x", "hi") is None


def test_only_queens_with_the_provider_wired_are_asked():
    source = TurnContextReminderSource()

    assert source.applies_to(_queen(lambda text: None))
    assert not source.applies_to(SimpleNamespace(is_queen_stream=False, turn_context_provider=lambda text: None))
    assert not source.applies_to(SimpleNamespace(is_queen_stream=True, turn_context_provider=None))
