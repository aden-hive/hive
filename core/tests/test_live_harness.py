"""Live tests read the real Hive home's LLM config and keys, and never write to it."""

from __future__ import annotations

import json
import os
import runpy
import shutil
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

import framework.config as config
from framework.credentials import CredentialKey, CredentialObject, CredentialStore, EncryptedFileStorage, key_storage
from tests.live import conftest as live

CORE_CONFTEST = Path(__file__).resolve().parents[1] / "conftest.py"


def _api_key(cred_id: str, value: str) -> CredentialObject:
    return CredentialObject(id=cred_id, keys={"api_key": CredentialKey(name="api_key", value=SecretStr(value))})


def _save(home: Path, cred_id: str, value: str) -> None:
    key = (home / "secrets" / "credential_key").read_bytes()
    EncryptedFileStorage(home / "credentials", encryption_key=key).save(_api_key(cred_id, value))


def _configure(home: Path, provider: str, model: str) -> None:
    (home / "configuration.json").write_text(json.dumps({"llm": {"provider": provider, "model": model}}), encoding="utf-8")


def _snapshot(home: Path) -> dict[str, bytes | None]:
    return {str(p.relative_to(home)): p.read_bytes() if p.is_file() else None for p in home.rglob("*")}


def _resolve() -> live.LiveLLMConfig:
    """``resolve_live_llm_config()``, failing rather than skipping, so a regression can't pass quietly."""
    try:
        return live.resolve_live_llm_config()
    except pytest.skip.Exception as skip:
        pytest.fail(f"live_llm_config skipped: {skip}")


@pytest.fixture(autouse=True)
def _no_llm_env(monkeypatch):
    for name in ("HIVE_CREDENTIAL_KEY", "HIVE_LIVE_MODEL", "HIVE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def real_home(tmp_path):
    """A developer's Hive home: OpenAI configured, its key in the credential store.

    The store's index is gone, as in a home from before it existed, so opening
    the store the usual way would write a new one.
    """
    home = tmp_path / "real-home"
    (home / "secrets").mkdir(parents=True)
    (home / "secrets" / "credential_key").write_text(Fernet.generate_key().decode(), encoding="utf-8")
    _configure(home, "openai", "gpt-test")
    _save(home, "openai", "sk-from-store")
    shutil.rmtree(home / "credentials" / "metadata")
    return home


def test_live_config_comes_from_the_real_home_without_writing_to_it(real_home, monkeypatch):
    before = _snapshot(real_home)

    live.read_real_hive_home(monkeypatch, real_home)
    resolved = _resolve()

    assert (resolved.model, resolved.api_key) == ("openai/gpt-test", "sk-from-store")
    assert _snapshot(real_home) == before


def test_the_rest_of_the_home_stays_in_the_sandbox(real_home, monkeypatch):
    live.read_real_hive_home(monkeypatch, real_home)

    for path in (config.HIVE_HOME, config.QUEENS_DIR, config.COLONIES_DIR, key_storage.CREDENTIAL_KEY_PATH):
        assert not Path(path).is_relative_to(real_home)


def test_the_real_credential_store_refuses_writes(real_home, monkeypatch):
    live.read_real_hive_home(monkeypatch, real_home)
    before = _snapshot(real_home)

    with pytest.raises(PermissionError):
        CredentialStore.with_encrypted_storage().save_credential(_api_key("openai", "sk-overwritten"))

    assert _snapshot(real_home) == before


def test_a_configured_provider_that_resolves_nothing_fails(real_home, monkeypatch):
    (real_home / "secrets" / "credential_key").unlink()
    live.read_real_hive_home(monkeypatch, real_home)

    with pytest.raises(pytest.fail.Exception, match="configures 'openai'"):
        live.resolve_live_llm_config()


def test_no_configured_provider_still_skips(tmp_path, monkeypatch):
    live.read_real_hive_home(monkeypatch, tmp_path / "empty-home")

    with pytest.raises(pytest.skip.Exception):
        live.resolve_live_llm_config()


def test_a_configured_hive_provider_uses_its_stored_token(real_home, monkeypatch):
    _configure(real_home, "hive", "hive-2.1")
    _save(real_home, "hive", "hive-stored-token")
    live.read_real_hive_home(monkeypatch, real_home)

    resolved = _resolve()

    assert (resolved.model, resolved.api_key) == ("hive/hive-2.1", "hive-stored-token")


def test_switching_to_anthropic_without_its_key_skips(real_home, monkeypatch):
    monkeypatch.setenv("HIVE_LIVE_MODEL", "anthropic/claude-test")
    live.read_real_hive_home(monkeypatch, real_home)

    # The configured OpenAI key would otherwise go to Anthropic.
    with pytest.raises(pytest.skip.Exception, match="ANTHROPIC_API_KEY"):
        live.resolve_live_llm_config()


def test_the_first_process_passes_its_hive_home_on(tmp_path, monkeypatch):
    monkeypatch.setenv("HIVE_HOME", str(tmp_path / "real-home"))
    monkeypatch.delenv("HIVE_TESTS_REAL_HIVE_HOME", raising=False)

    assert runpy.run_path(str(CORE_CONFTEST))["_REAL_HIVE_HOME"] == tmp_path / "real-home"
    assert os.environ["HIVE_TESTS_REAL_HIVE_HOME"] == str(tmp_path / "real-home")


def test_an_xdist_worker_gets_the_real_home_not_the_inherited_sandbox(tmp_path, monkeypatch):
    # A worker starts with the controller's environment, where HIVE_HOME is already a throwaway directory.
    monkeypatch.setenv("HIVE_HOME", str(tmp_path / "controller-throwaway"))
    monkeypatch.setenv("HIVE_TESTS_REAL_HIVE_HOME", str(tmp_path / "real-home"))

    assert runpy.run_path(str(CORE_CONFTEST))["_REAL_HIVE_HOME"] == tmp_path / "real-home"
