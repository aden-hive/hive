"""The stall check: a judge catches queen turns that announce work and stop."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

import framework.config as hive_config
from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.server.stall_check import REMINDER, subscribe_stall_check

JUDGE = {"protocol": "fake", "api_base": "https://judge.invalid/v1", "model": "judge-1", "api_key": "k", "threshold": 0.5}


@pytest.fixture
def config(monkeypatch):
    cfg = {"stall_check": True, "judge": dict(JUDGE)}
    monkeypatch.delenv("HIVE_STALL_CHECK", raising=False)
    monkeypatch.setattr(hive_config, "get_hive_config", lambda: cfg)
    return cfg


class FakeJudge:
    def __init__(self, p: float) -> None:
        self.p, self.states = p, []

    async def __call__(self, slot, question, state, criteria):
        self.states.append(state)
        return self.p


def _watch(p: float):
    bus, node, judge = EventBus(), MagicMock(), FakeJudge(p)
    node.inject_event = AsyncMock()
    subscribe_stall_check(bus, lambda: node, judges={"fake": judge})
    return bus, node, judge


async def _turn(bus, *events: tuple[EventType, dict]) -> None:
    for type_, data in events:
        await bus.publish(AgentEvent(type=type_, stream_id="queen", data=data))
    for _ in range(20):
        await asyncio.sleep(0)


STALLED = (
    (EventType.CLIENT_INPUT_RECEIVED, {"content": "[Owner(1)]: draw something nice"}),
    (EventType.CLIENT_REASONING, {"reasoning": "I'll curl the image API, then attach_file. Let me run it."}),
    (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": "On it, drawing one now."}),
    (EventType.CLIENT_INPUT_REQUESTED, {"park_reason": "turn_done"}),
)


@pytest.mark.asyncio
async def test_a_turn_that_announces_work_and_stops_gets_one_reminder(config):
    bus, node, judge = _watch(0.95)

    await _turn(bus, *STALLED)
    # She replies again after the reminder, without a new user message: no second judgment.
    await _turn(bus, (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": "Still on it."}), (EventType.CLIENT_INPUT_REQUESTED, {"park_reason": "turn_done"}))

    node.inject_event.assert_awaited_once_with(REMINDER, is_client_input=False)
    assert judge.states == [
        {
            "user_message": "[Owner(1)]: draw something nice",
            "assistant_reasoning_tail": "I'll curl the image API, then attach_file. Let me run it.",
            "assistant_reply": "On it, drawing one now.",
            "tools_called_this_turn": [],
        }
    ]


@pytest.mark.asyncio
async def test_a_turn_the_judge_finds_fine_is_left_alone(config):
    bus, node, judge = _watch(0.05)

    await _turn(bus, *STALLED)

    assert len(judge.states) == 1
    node.inject_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_model_call_is_not_judged(config):
    bus, node, judge = _watch(0.95)

    await _turn(
        bus,
        (EventType.CLIENT_INPUT_RECEIVED, {"content": "[Cy(7)]: （戳了戳你）"}),
        # A gateway returned the failure as an ordinary reply.
        (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": "[Error: LLM call failed: Stream error: Authentication Fails. Please try again.]"}),
        (EventType.CLIENT_INPUT_REQUESTED, {"park_reason": "turn_done"}),
    )

    assert judge.states == []
    node.inject_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_nothing_is_judged_while_the_option_is_off(config):
    config["stall_check"] = False
    bus, node, judge = _watch(0.95)

    await _turn(bus, *STALLED)

    assert judge.states == []
    node.inject_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_judge_reads_the_last_model_call(config):
    bus, _, judge = _watch(0.05)

    await _turn(
        bus,
        (EventType.CLIENT_INPUT_RECEIVED, {"content": "draw"}),
        (EventType.CLIENT_REASONING, {"reasoning": "first, read the skill"}),
        (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": "Reading up."}),
        (EventType.TOOL_CALL_STARTED, {"tool_name": "terminal_exec"}),
        (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": "Here it is."}),
        (EventType.CLIENT_INPUT_REQUESTED, {"park_reason": "turn_done"}),
    )

    assert judge.states[0]["assistant_reasoning_tail"] == ""
    assert judge.states[0]["assistant_reply"] == "Here it is."
    assert judge.states[0]["tools_called_this_turn"] == ["terminal_exec"]


@pytest.mark.asyncio
async def test_the_judge_slot_saves_without_the_chat_key_check_and_the_option_toggles(monkeypatch, tmp_path):
    from framework.server import routes_config
    from framework.server.app import create_app

    cfg_file = tmp_path / "configuration.json"
    cfg_file.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("HIVE_STALL_CHECK", raising=False)
    monkeypatch.setattr(routes_config, "HIVE_CONFIG_FILE", cfg_file)
    read = lambda: json.loads(cfg_file.read_text(encoding="utf-8"))  # noqa: E731
    monkeypatch.setattr(hive_config, "get_hive_config", read)
    monkeypatch.setattr(routes_config, "get_hive_config", read)
    checked = AsyncMock(return_value={"valid": False, "message": "not a chat model"})
    monkeypatch.setattr(routes_config, "_validate_provider_key", checked)

    async with TestClient(TestServer(create_app())) as client:
        saved = await client.put("/api/config/llm-sections", json={"role": "judge", "section": JUDGE})
        sections = await (await client.get("/api/config/llm-sections")).json()
        await client.put("/api/config/features", json={"features": {"stall_check": True}})
        features = await (await client.get("/api/config/features")).json()

    assert saved.status == 200
    checked.assert_not_awaited()
    assert sections["judge"] == JUDGE
    assert features["features"]["stall_check"] is True
