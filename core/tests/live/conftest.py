"""Live-test pytest setup.

Registers the ``live`` marker. Tests under this directory make REAL LLM
calls with the LLM configuration and keys of the Hive home the run started
with (``HIVE_HOME``, else ``~/.hive``: the same source the desktop app
uses), which they read but never write. They never run unless ``-m live``
is explicitly passed. They skip when no LLM is configured, and fail when
one is configured but its key can't be resolved.

The fixtures here construct the SAME components the desktop app uses
(AgentLoop, NodeContext, NodeConversation, LiteLLMProvider, EventBus,
FileConversationStore). No test-only subclasses or context-handling
shortcuts. The only difference from production is the source of user
turns (a Python list) and the working directory (a pytest tmp_path).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from framework.credentials import CredentialStore, EncryptedFileStorage

_NO_WRITES = "Live tests only read the real Hive home's credential store"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live: mark test as making real LLM API calls (run manually with -m live)",
    )


class _ReadOnlyEncryptedFileStorage(EncryptedFileStorage):
    """The real home's credential store, opened for reading.

    EncryptedFileStorage creates its directories and may rebuild its index
    when it's constructed. Here that's skipped, and every write raises.
    """

    def _ensure_dirs(self) -> None:
        pass

    def _maybe_rebuild_index(self) -> None:
        pass

    def save(self, credential) -> None:
        raise PermissionError(_NO_WRITES)

    def delete(self, credential_id: str) -> bool:
        raise PermissionError(_NO_WRITES)

    def _write_index(self, index: dict) -> None:
        raise PermissionError(_NO_WRITES)


def read_real_hive_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """Point the LLM config and key lookups at ``home``, without letting them write there.

    * ``framework.config.HIVE_CONFIG_FILE``, for the provider, model and any
      key in the configuration.
    * ``HIVE_CREDENTIAL_KEY``, read from ``home``'s key file unless it's
      already set. Not through ``load_credential_key()``, which writes the
      key back to disk.
    * The default encrypted credential store: ``home``'s, read-only and
      without auto-refresh, since a refresh saves.
    """
    import framework.config as config

    monkeypatch.setattr(config, "HIVE_CONFIG_FILE", home / "configuration.json")

    key_file = home / "secrets" / "credential_key"
    if not os.environ.get("HIVE_CREDENTIAL_KEY") and key_file.is_file():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            monkeypatch.setenv("HIVE_CREDENTIAL_KEY", key)

    with_encrypted_storage = CredentialStore.with_encrypted_storage.__func__

    def read_only_by_default(cls, base_path=None, **kwargs):
        if base_path is not None:
            return with_encrypted_storage(cls, base_path, **kwargs)
        return cls(storage=_ReadOnlyEncryptedFileStorage(home / "credentials"), **{**kwargs, "auto_refresh": False})

    monkeypatch.setattr(CredentialStore, "with_encrypted_storage", classmethod(read_only_by_default))


@pytest.fixture(autouse=True)
def _live_reads_real_hive_home(request, real_hive_home, _isolate_hive_home_autouse, monkeypatch):
    """Give live tests the real LLM config and keys, and keep everything else sandboxed.

    The parent conftest sandboxes the Hive home for every test. This points
    only the LLM config and key lookups at ``real_hive_home`` (recorded in
    core/conftest.py before ``HIVE_HOME`` was replaced), so sessions, queens
    and colonies stay in the sandbox, and so do its other patches, such as
    ``_no_real_browser_bridge``. Tests here without the ``live`` marker get
    the plain sandbox.
    """
    if request.node.get_closest_marker("live"):
        read_real_hive_home(monkeypatch, real_hive_home)


@dataclass(frozen=True)
class LiveLLMConfig:
    """Resolved LLM config for live runs.

    Defaults come from the real Hive home's ``configuration.json`` via
    ``framework.config.RuntimeConfig`` — the same path production uses
    in ``session_manager.build_llm``. ``HIVE_LIVE_MODEL`` overrides the
    model only; auth still comes from the user's configuration.
    """

    model: str
    api_key: str | None
    api_base: str | None
    extra_kwargs: dict


def resolve_live_llm_config() -> LiveLLMConfig:
    """What ``live_llm_config`` provides: the resolved config, or a skip or a failure."""
    import framework.config as config

    rc = config.RuntimeConfig()
    model = os.getenv("HIVE_LIVE_MODEL", rc.model).strip()

    api_key = rc.api_key
    api_base = rc.api_base
    extra = dict(rc.extra_kwargs)

    # Provider-specific env vars take priority. When HIVE_LIVE_MODEL switches
    # to another provider, the configured api_key (bound to the user's main
    # provider) doesn't authenticate it, so that provider's env var is required.
    configured = rc.model.lower()
    if model.lower().startswith("hive/"):
        hive_key = os.getenv("HIVE_API_KEY")
        if hive_key:
            api_key = hive_key
            api_base = None  # let rewrite_proxy_model set the hive proxy base
        elif not configured.startswith("hive/"):
            pytest.skip(
                "HIVE_LIVE_MODEL points at hive/, but HIVE_API_KEY is not set. "
                "Exchange your access JWT for a stream token via "
                "POST https://app.open-hive.com/user/refresh-stream-token "
                "and export the returned streamToken as HIVE_API_KEY."
            )
    elif model.lower().startswith("anthropic/") and not model.lower().startswith("anthropic/hive"):
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            api_key = anthropic_key
            api_base = None
        elif not configured.startswith("anthropic/"):
            pytest.skip("HIVE_LIVE_MODEL points at anthropic/, but ANTHROPIC_API_KEY is not set, and the configured key is for another provider.")

    if not api_key and not api_base:
        # A configured provider that resolves nothing is a harness problem, not missing setup.
        provider = config.get_hive_config().get("llm", {}).get("provider")
        if provider:
            pytest.fail(
                f"{config.HIVE_CONFIG_FILE} configures {provider!r}, but no API key or base resolved for it. "
                "If that home has the key, the live harness isn't reading it."
            )
        pytest.skip(f"No LLM provider configured — set one in {config.HIVE_CONFIG_FILE} or an API key env var (e.g. HIVE_API_KEY, ANTHROPIC_API_KEY)")
    return LiveLLMConfig(
        model=model,
        api_key=api_key,
        api_base=api_base,
        extra_kwargs=extra,
    )


@pytest.fixture
def live_llm_config() -> LiveLLMConfig:
    """Resolve a real LLM config, or skip the test when none is configured.

    Default: reads the real Hive home's ``configuration.json`` via
    ``RuntimeConfig`` so the harness uses whatever the desktop app is
    currently configured for. Overrides:

    * ``HIVE_LIVE_MODEL`` — model string (e.g. ``hive/hive-2.1``,
      ``anthropic/claude-haiku-4-5-20251001``). Used as-is by
      ``LiteLLMProvider``; the ``rewrite_proxy_model`` helper then
      rewrites ``hive/`` to ``anthropic/`` and points the api_base at
      the Hive proxy when applicable.
    * ``HIVE_API_KEY`` — bearer token for ``hive/`` models. Required
      when ``HIVE_LIVE_MODEL`` switches to ``hive/`` from another
      provider, because the user's configured ``api_key`` is bound to
      that provider (e.g. Z.AI). Obtain by exchanging a user JWT via
      ``POST https://app.open-hive.com/user/refresh-stream-token``.
    * ``ANTHROPIC_API_KEY`` — bearer for direct ``anthropic/`` models,
      required the same way when ``HIVE_LIVE_MODEL`` switches to one.

    When set, either key takes the place of the configured one for its
    provider.

    Fails instead of skipping when the configuration names a provider
    but no key or API base resolves for it.
    """
    return resolve_live_llm_config()
