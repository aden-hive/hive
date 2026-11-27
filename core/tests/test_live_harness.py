"""Live tests read the real Hive home's LLM config and keys, and never write to it."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

import framework.config as config
from framework.credentials import CredentialKey, CredentialObject, CredentialStore, EncryptedFileStorage, key_storage
from tests.live import conftest as live


def _api_key(cred_id: str, value: str) -> CredentialObject:
    return CredentialObject(id=cred_id, keys={"api_key": CredentialKey(name="api_key", value=SecretStr(value))})


def _snapshot(home: Path) -> dict[str, bytes | None]:
    return {str(p.relative_to(home)): p.read_bytes() if p.is_file() else None for p in home.rglob("*")}


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
    key = Fernet.generate_key()
    (home / "secrets").mkdir(parents=True)
    (home / "secrets" / "credential_key").write_text(key.decode(), encoding="utf-8")
    (home / "configuration.json").write_text(json.dumps({"llm": {"provider": "openai", "model": "gpt-test"}}), encoding="utf-8")
    EncryptedFileStorage(home / "credentials", encryption_key=key).save(_api_key("openai", "sk-from-store"))
    shutil.rmtree(home / "credentials" / "metadata")
    return home


def test_live_config_comes_from_the_real_home_without_writing_to_it(real_home, monkeypatch):
    before = _snapshot(real_home)

    live.read_real_hive_home(monkeypatch, real_home)
    resolved = live.resolve_live_llm_config()

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
