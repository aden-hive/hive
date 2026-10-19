"""The judge slot answers yes/no questions with a probability, or not at all."""

from __future__ import annotations

import pytest

import framework.config as hive_config
from framework.server import judge
from framework.server.channels import ChannelHost

SLOT = {"protocol": "fake", "api_base": "https://judge.invalid/v1", "model": "judge-1", "api_key": "k"}


@pytest.fixture
def asked(monkeypatch):
    calls: list[tuple] = []

    async def fake(slot, question, state, criteria):
        calls.append((slot["model"], question, state, criteria))
        if state.get("fail"):
            raise TimeoutError("judge took too long")
        return 0.8

    monkeypatch.setattr(judge, "PROTOCOLS", {"fake": fake})
    monkeypatch.setattr(hive_config, "get_hive_config", lambda: {"judge": SLOT})
    return calls


@pytest.mark.asyncio
async def test_a_channel_asks_the_configured_judge(asked):
    host = ChannelHost("onebot", manager=_NoSessions(), config={})
    criteria = {"true": "someone talks to her", "false": "others chat among themselves"}

    p = await host.judge("Is now a good moment for her to speak?", {"new_messages": ["Cy: anyone draw?"]}, criteria=criteria)

    assert p == 0.8
    assert asked == [("judge-1", "Is now a good moment for her to speak?", {"new_messages": ["Cy: anyone draw?"]}, criteria)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config",
    [{}, {"judge": {**SLOT, "api_key": ""}}, {"judge": {**SLOT, "protocol": "unknown"}}],
    ids=["no slot", "no key", "unsupported protocol"],
)
async def test_no_answer_without_a_usable_judge(asked, monkeypatch, config):
    monkeypatch.setattr(hive_config, "get_hive_config", lambda: config)

    assert await judge.ask("Is it raining?", {}) is None
    assert asked == []


@pytest.mark.asyncio
async def test_no_answer_when_the_judge_fails(asked):
    assert await judge.ask("Is it raining?", {"fail": True}) is None


class _NoSessions:
    def add_session_listener(self, listener):
        return lambda: None
