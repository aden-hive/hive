"""Tests for with_aden_sync error handling (issue #5859).

When ADEN_API_KEY is set but Aden sync initialization fails,
CredentialStore.with_aden_sync() must raise CredentialError
instead of silently falling back to local storage.
"""

import sys
from types import ModuleType
from unittest.mock import patch

import pytest

from framework.credentials.models import CredentialError
from framework.credentials.store import CredentialStore


def _stub_aden_modules(monkeypatch, *, sync_all_side_effect=None, init_side_effect=None):
    """Install fake aden sub-modules so ImportError is not raised."""
    aden_mod = ModuleType("framework.credentials.aden")

    class FakeConfig:
        def __init__(self, **kw):
            pass

    class FakeClient:
        def __init__(self, config):
            if init_side_effect:
                raise init_side_effect

    class FakeProvider:
        def __init__(self, **kw):
            pass

        def sync_all(self, store):
            if sync_all_side_effect:
                raise sync_all_side_effect
            return 0

    class FakeCachedStorage:
        def __init__(self, **kw):
            pass

    aden_mod.AdenClientConfig = FakeConfig
    aden_mod.AdenCredentialClient = FakeClient
    aden_mod.AdenSyncProvider = FakeProvider
    aden_mod.AdenCachedStorage = FakeCachedStorage

    monkeypatch.setitem(sys.modules, "framework.credentials.aden", aden_mod)


def test_raises_when_api_key_set_and_init_fails(monkeypatch, tmp_path):
    """ADEN_API_KEY present + client init raises → CredentialError."""
    monkeypatch.setenv("ADEN_API_KEY", "test-key-123")
    _stub_aden_modules(
        monkeypatch,
        init_side_effect=ConnectionError("connection refused"),
    )

    with pytest.raises(CredentialError, match="Failed to initialize Aden sync"):
        CredentialStore.with_aden_sync(local_path=str(tmp_path / "creds"))


def test_raises_when_api_key_set_and_sync_fails(monkeypatch, tmp_path):
    """ADEN_API_KEY present + sync_all raises → CredentialError."""
    monkeypatch.setenv("ADEN_API_KEY", "test-key-123")
    _stub_aden_modules(
        monkeypatch,
        sync_all_side_effect=RuntimeError("server returned 500"),
    )

    with pytest.raises(CredentialError, match="Failed to initialize Aden sync"):
        CredentialStore.with_aden_sync(local_path=str(tmp_path / "creds"))


def test_falls_back_when_no_api_key(monkeypatch, tmp_path):
    """No ADEN_API_KEY → local-only storage, no error."""
    monkeypatch.delenv("ADEN_API_KEY", raising=False)

    store = CredentialStore.with_aden_sync(local_path=str(tmp_path / "creds"))
    assert store is not None


def test_falls_back_when_aden_not_installed(monkeypatch, tmp_path):
    """ADEN_API_KEY set but aden package missing → local fallback (ImportError)."""
    monkeypatch.setenv("ADEN_API_KEY", "test-key-123")
    # Ensure the aden module cannot be imported
    monkeypatch.delitem(sys.modules, "framework.credentials.aden", raising=False)

    with patch.dict(sys.modules, {"framework.credentials.aden": None}):
        store = CredentialStore.with_aden_sync(local_path=str(tmp_path / "creds"))
        assert store is not None
