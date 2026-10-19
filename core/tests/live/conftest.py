"""Live-test pytest setup.

Registers the ``live`` marker. Tests under this directory make REAL LLM
calls and read REAL credentials from the user's ``~/.hive/configuration.json``
(the same source the desktop app uses). They never run unless ``-m live``
is explicitly passed, and they skip gracefully when no LLM is configured.

The fixtures here construct the SAME components the desktop app uses
(AgentLoop, NodeContext, NodeConversation, LiteLLMProvider, EventBus,
FileConversationStore). No test-only subclasses or context-handling
shortcuts. The only difference from production is the source of user
turns (a Python list) and the working directory (a pytest tmp_path).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live: mark test as making real LLM API calls (run manually with -m live)",
    )


@pytest.fixture(autouse=True)
def _live_uses_real_hive_home(request, _isolate_hive_home_autouse):
    """Undo the global ``~/.hive`` redirect for live tests.

    The parent conftest auto-isolates every test to a per-test ``~/.hive``
    so unit tests don't pollute the developer's real home. Live tests
    must read the developer's actual ``~/.hive/configuration.json`` so
    the harness exercises the same LLM provider, credentials, and model
    as the desktop app. This fixture, autouse-scoped to ``tests/live/``,
    runs AFTER the parent isolation and unwinds its monkeypatching by
    triggering ``monkeypatch.undo()`` on the parent fixture's request.

    Implementation: we just force the parent's monkeypatch to undo by
    looking it up in pytest's per-test fixture cache.
    """
    # The parent autouse fixture stashes Path.home before patching; we
    # restore by walking ``request._pyfuncitem.funcargs`` for the
    # ``monkeypatch`` instance the parent installed. Calling .undo()
    # reverts all setattrs in reverse order.
    mp = request.getfixturevalue("monkeypatch")
    mp.undo()
    yield


@dataclass(frozen=True)
class LiveLLMConfig:
    """Resolved LLM config for live runs.

    Defaults come from the user's ``~/.hive/configuration.json`` via
    ``framework.config.RuntimeConfig`` — the same path production uses
    in ``session_manager.build_llm``. ``HIVE_LIVE_MODEL`` overrides the
    model only; auth still comes from the user's configuration.
    """

    model: str
    api_key: str | None
    api_base: str | None
    extra_kwargs: dict


@pytest.fixture
def live_llm_config() -> LiveLLMConfig:
    """Resolve a real LLM config or skip the test.

    Default: reads ``~/.hive/configuration.json`` via ``RuntimeConfig``
    so the harness uses whatever the desktop app is currently configured
    for. Overrides:

    * ``HIVE_LIVE_MODEL`` — model string (e.g. ``hive/hive-2.1``,
      ``anthropic/claude-haiku-4-5-20251001``). Used as-is by
      ``LiteLLMProvider``; the ``rewrite_proxy_model`` helper then
      rewrites ``hive/`` to ``anthropic/`` and points the api_base at
      the Hive proxy when applicable.
    * ``HIVE_API_KEY`` — bearer token for ``hive/`` models. Required
      when ``HIVE_LIVE_MODEL`` starts with ``hive/`` because the user's
      configured ``api_key`` is bound to a different provider (e.g.
      Z.AI). Obtain by exchanging a user JWT via
      ``POST https://app.open-hive.com/user/refresh-stream-token``.
    * ``ANTHROPIC_API_KEY`` — bearer for direct ``anthropic/`` models.
    """
    from framework.config import RuntimeConfig

    rc = RuntimeConfig()
    model = os.getenv("HIVE_LIVE_MODEL", rc.model).strip()

    api_key = rc.api_key
    api_base = rc.api_base
    extra = dict(rc.extra_kwargs)

    # When HIVE_LIVE_MODEL overrides the provider prefix, the configured
    # api_key (bound to the user's main provider) doesn't authenticate
    # the new provider. Resolve provider-specific env vars in priority.
    if model.lower().startswith("hive/"):
        hive_key = os.getenv("HIVE_API_KEY")
        if not hive_key:
            pytest.skip(
                "HIVE_LIVE_MODEL points at hive/, but HIVE_API_KEY is not set. "
                "Exchange your access JWT for a stream token via "
                "POST https://app.open-hive.com/user/refresh-stream-token "
                "and export the returned streamToken as HIVE_API_KEY."
            )
        api_key = hive_key
        api_base = None  # let rewrite_proxy_model set the hive proxy base
    elif model.lower().startswith("anthropic/") and not model.lower().startswith("anthropic/hive"):
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            api_key = anthropic_key
            api_base = None

    if not api_key and not api_base:
        pytest.skip("No LLM provider configured — set ~/.hive/configuration.json or an API key env var (e.g. HIVE_API_KEY, ANTHROPIC_API_KEY)")
    return LiveLLMConfig(
        model=model,
        api_key=api_key,
        api_base=api_base,
        extra_kwargs=extra,
    )
