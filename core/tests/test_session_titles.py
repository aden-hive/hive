"""Automatic and user-set session titles."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.server.session_titles import clean_title, read_title, subscribe_title_trigger, write_title


@pytest.mark.parametrize(
    ("raw", "title"),
    [
        ('"Launch plan for Notebook."', "Launch plan for Notebook"),
        ("<think>pondering</think>\nTitle: 周末旅行计划。", "周末旅行计划"),
        ("## **Pricing test review**\nextra line", "Pricing test review"),
        ("x" * 80, "x" * 59 + "…"),
    ],
)
def test_clean_title(raw, title):
    assert clean_title(raw) == title


def _session_dir(tmp_path, first_message="Plan a weekend in Kyoto"):
    d = tmp_path / "session_20261017_090000_aaaa1111"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"queen_id": "queen_x"}))
    (d / "events.jsonl").write_text(json.dumps({"type": "client_input_received", "stream_id": "queen", "data": {"content": first_message}}) + "\n")
    return d


class _TitleLLM:
    def __init__(self, reply="Kyoto weekend plan."):
        self.calls = []
        self.reply = reply

    async def acomplete(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=self.reply)


async def _finish_turn(bus, *, stop_reason="stop", reply="Here is a two-day plan."):
    await bus.publish(AgentEvent(type=EventType.CLIENT_OUTPUT_DELTA, stream_id="queen", data={"snapshot": reply}))
    await bus.publish(AgentEvent(type=EventType.LLM_TURN_COMPLETE, stream_id="queen", data={"stop_reason": stop_reason}))
    for _ in range(50):
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_a_finished_turn_titles_the_session_and_announces_it(tmp_path):
    bus, llm, d = EventBus(), _TitleLLM(), _session_dir(tmp_path)
    announced = []

    async def on_title(event):
        announced.append(event.data)

    bus.subscribe([EventType.SESSION_TITLE_UPDATED], on_title)
    subscribe_title_trigger(bus, d, llm)

    await _finish_turn(bus)

    assert read_title(d) == "Kyoto weekend plan"
    assert json.loads((d / "meta.json").read_text())["title_source"] == "auto"
    assert announced == [{"session_id": d.name, "title": "Kyoto weekend plan"}]
    assert "Plan a weekend in Kyoto" in llm.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_a_turn_that_only_calls_tools_does_not_title(tmp_path):
    bus, llm, d = EventBus(), _TitleLLM(), _session_dir(tmp_path)
    subscribe_title_trigger(bus, d, llm)

    await _finish_turn(bus, stop_reason="tool_calls")

    assert llm.calls == []
    assert read_title(d) is None


@pytest.mark.asyncio
async def test_a_title_the_user_set_is_never_replaced(tmp_path):
    bus, llm, d = EventBus(), _TitleLLM(), _session_dir(tmp_path)
    write_title(d, "My Kyoto trip", source="user")
    subscribe_title_trigger(bus, d, llm)

    await _finish_turn(bus)

    assert llm.calls == []
    assert read_title(d) == "My Kyoto trip"


@pytest.mark.asyncio
async def test_title_route_sets_and_clears_a_users_title():
    from framework.server import session_manager
    from framework.server.app import create_app

    d = session_manager.QUEENS_DIR / "queen_x" / "sessions" / "session_20261017_090000_aaaa1111"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"queen_id": "queen_x"}))

    async with TestClient(TestServer(create_app())) as client:
        set_resp = await client.patch(f"/api/sessions/{d.name}/title", json={"title": "  Kyoto trip  "})
        set_body = await set_resp.json()
        cleared = await (await client.patch(f"/api/sessions/{d.name}/title", json={"title": ""})).json()

    assert set_resp.status == 200
    assert set_body["title"] == "Kyoto trip"
    assert cleared["title"] is None
    assert read_title(d) is None
