"""A queen's own model (queen_llm): how it is read, set from the dashboard, and kept apart from the main one."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

import framework.config as hive_config
from framework.server import queen_models

OWN = {"provider": "openai", "model": "archivist-1", "api_base": "https://models.invalid/v1", "api_key": "sk-own"}
MAIN = {"provider": "anthropic", "model": "claude-x", "api_key": "sk-main"}


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """configuration.json in a temp dir, read fresh by every getter."""
    from framework.server import routes_config

    path = tmp_path / "configuration.json"
    path.write_text(json.dumps({"llm": MAIN}), encoding="utf-8")
    read = lambda: json.loads(path.read_text(encoding="utf-8"))  # noqa: E731
    monkeypatch.setattr(hive_config, "get_hive_config", read)
    monkeypatch.setattr(routes_config, "get_hive_config", read)
    monkeypatch.setattr(routes_config, "HIVE_CONFIG_FILE", path)
    return path


def _with(path, **extra):
    path.write_text(json.dumps({"llm": MAIN, **extra}), encoding="utf-8")


class FakeLLM:
    def __init__(self, model):
        self.model, self.calls = model, []

    def reconfigure(self, model, api_key=None, api_base=None, *, api_key_resolver=None, extra_body=None):
        self.model = model
        self.calls.append((model, api_key, api_base, api_key_resolver() if api_key_resolver else None))


def test_her_section_decides_her_model_key_endpoint_and_window(config_file, monkeypatch):
    monkeypatch.setenv("ARCHIVE_KEY", "sk-env")
    _with(
        config_file,
        queen_llm={
            "queen_growth": {**OWN, "max_context_tokens": 64000},
            "queen_sales": {"provider": "openrouter", "model": "openrouter/some/model", "api_key_env_var": "ARCHIVE_KEY"},
            "queen_legal": {"provider": "openai"},  # no model: not hers
        },
    )

    assert hive_config.section_model(hive_config.get_queen_llm_section("queen_growth")) == "openai/archivist-1"
    assert (hive_config.get_queen_api_key("queen_growth"), hive_config.get_queen_api_base("queen_growth")) == ("sk-own", OWN["api_base"])
    assert hive_config.get_queen_max_context_tokens("queen_growth") == 64000
    assert hive_config.section_model(hive_config.get_queen_llm_section("queen_sales")) == "openrouter/some/model"
    assert hive_config.get_queen_api_key("queen_sales") == "sk-env"
    assert hive_config.get_queen_api_base("queen_sales") == hive_config.OPENROUTER_API_BASE
    assert hive_config.get_queen_llm_section("queen_legal") is None
    assert hive_config.get_queen_api_key("queen_legal") == hive_config.get_api_key()


def test_her_provider_uses_her_key_on_every_call(config_file):
    _with(config_file, queen_llm={"queen_growth": OWN})

    llm = queen_models.build("queen_growth")
    _with(config_file, queen_llm={"queen_growth": {**OWN, "api_key": "sk-rotated"}})

    assert llm.model == "openai/archivist-1"
    assert llm._api_key_resolver() == "sk-rotated"
    assert queen_models.build("queen_sales") is None


def test_her_extra_body_goes_on_her_provider(config_file):
    _with(config_file, queen_llm={"queen_growth": {**OWN, "extra_body": {"reasoning_effort": "low"}}, "queen_sales": OWN})

    assert queen_models.build("queen_growth").extra_kwargs["extra_body"] == {"reasoning_effort": "low"}
    assert "extra_body" not in queen_models.build("queen_sales").extra_kwargs


def test_switching_her_model_switches_the_extra_body_too(config_file):
    from framework.llm.litellm import LiteLLMProvider

    main_body = {"thinking": {"type": "enabled"}}
    _with(config_file, llm={**MAIN, "extra_body": main_body}, queen_llm={"queen_growth": {**OWN, "extra_body": {"reasoning_effort": "low"}}})
    llm = LiteLLMProvider(model="anthropic/claude-x", api_key="sk-main", extra_body=main_body)

    queen_models.apply(llm, "queen_growth")
    hers = llm.extra_kwargs.get("extra_body")
    _with(config_file, llm={**MAIN, "extra_body": main_body}, queen_llm={"queen_growth": OWN})
    queen_models.apply(llm, "queen_growth")
    hers_without = llm.extra_kwargs.get("extra_body")
    _with(config_file, llm={**MAIN, "extra_body": main_body})
    queen_models.apply(llm, "queen_growth")

    assert hers == {"reasoning_effort": "low"}
    assert hers_without is None
    assert llm.extra_kwargs["extra_body"] == main_body


def test_the_worker_model_sends_its_own_extra_body(config_file):
    _with(
        config_file,
        llm={**MAIN, "extra_body": {"thinking": {"type": "enabled"}}},
        worker_llm={**OWN, "extra_body": {"thinking": {"type": "disabled"}}},
    )

    assert hive_config.get_worker_llm_extra_kwargs() == {"extra_body": {"thinking": {"type": "disabled"}}}


@pytest.mark.asyncio
async def test_the_dashboard_sets_and_clears_her_model_and_her_sessions_follow(config_file, monkeypatch):
    from framework.server import routes_config
    from framework.server.app import create_app

    checked = AsyncMock(return_value={"valid": True})
    monkeypatch.setattr(routes_config, "_validate_provider_key", checked)
    app = create_app()
    hers, other = FakeLLM("anthropic/claude-x"), FakeLLM("anthropic/claude-x")
    sessions = [SimpleNamespace(queen_name="queen_growth", llm=hers), SimpleNamespace(queen_name="queen_sales", llm=other)]
    monkeypatch.setattr(app["manager"], "list_sessions", lambda: sessions)

    async with TestClient(TestServer(app)) as client:
        before = await (await client.get("/api/queen/queen_growth/llm")).json()
        set_ = await client.put("/api/queen/queen_growth/llm", json={"section": OWN})
        set_body = await set_.json()
        after = await (await client.get("/api/queen/queen_growth/llm")).json()
        cleared = await (await client.put("/api/queen/queen_growth/llm", json={"section": None})).json()

    assert before["section"] is None and before["default_model"]
    assert set_.status == 200 and set_body["sessions_switched"] == 1
    assert after["section"] == OWN
    checked.assert_awaited_once()
    assert hers.calls[0] == ("openai/archivist-1", "sk-own", OWN["api_base"], "sk-own")
    assert hers.calls[1][0] == before["default_model"]  # back on the main model
    assert other.calls == []
    assert cleared["section"] is None and "queen_llm" not in json.loads(config_file.read_text(encoding="utf-8"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("queen", "body", "status", "error"),
    [
        ("queen_growth", {"section": {"provider": "openai"}}, 400, "'provider' and 'model' are required"),
        ("queen_growth", {"section": "openai/x"}, 400, "must be a JSON object or null"),
        ("queen_nobody", {"section": OWN}, 404, "not found"),
        ("queen_growth", {"section": OWN}, 400, "Key check failed"),
    ],
)
async def test_a_bad_model_is_refused_and_nothing_is_written(config_file, monkeypatch, queen, body, status, error):
    from framework.server import routes_config
    from framework.server.app import create_app

    monkeypatch.setattr(routes_config, "_validate_provider_key", AsyncMock(return_value={"valid": False, "message": "401"}))
    async with TestClient(TestServer(create_app())) as client:
        resp = await client.put(f"/api/queen/{queen}/llm", json=body)
        answer = await resp.json()

    assert resp.status == status and error in answer["error"]
    assert "queen_llm" not in json.loads(config_file.read_text(encoding="utf-8"))


def test_changing_the_main_model_leaves_a_queen_with_her_own(config_file):
    from framework.server.routes_config import _hot_swap_sessions

    _with(config_file, queen_llm={"queen_growth": OWN})
    hers, other = FakeLLM("openai/archivist-1"), FakeLLM("anthropic/claude-x")
    manager = SimpleNamespace(
        _model=None,
        list_sessions=lambda: [SimpleNamespace(queen_name="queen_growth", llm=hers), SimpleNamespace(queen_name="queen_sales", llm=other)],
    )

    swapped = _hot_swap_sessions(SimpleNamespace(app={"manager": manager}), "anthropic/claude-y", api_key="sk-main", api_base=None)

    assert swapped == 1
    assert hers.calls == [] and other.model == "anthropic/claude-y"
