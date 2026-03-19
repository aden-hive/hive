import os
import sys
from types import ModuleType, SimpleNamespace

from framework.credentials import key_storage
from framework.credentials.validation import ensure_credential_key_env


def _install_fake_aden_modules(monkeypatch, check_fn, credential_specs):
    shell_config_module = ModuleType("aden_tools.credentials.shell_config")
    shell_config_module.check_env_var_in_shell_config = check_fn

    credentials_module = ModuleType("aden_tools.credentials")
    credentials_module.CREDENTIAL_SPECS = credential_specs

    monkeypatch.setitem(sys.modules, "aden_tools.credentials.shell_config", shell_config_module)
    monkeypatch.setitem(sys.modules, "aden_tools.credentials", credentials_module)


def test_bootstrap_loads_configured_llm_env_var_from_shell_config(monkeypatch):
    monkeypatch.setattr(key_storage, "load_credential_key", lambda: None)
    monkeypatch.setattr(key_storage, "load_aden_api_key", lambda: None)
    monkeypatch.setattr(
        "framework.config.get_hive_config",
        lambda: {"llm": {"api_key_env_var": "OPENROUTER_API_KEY"}},
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    calls = []

    def check_env(var_name):
        calls.append(var_name)
        if var_name == "OPENROUTER_API_KEY":
            return True, "or-key-123"
        return False, None

    _install_fake_aden_modules(
        monkeypatch,
        check_env,
        {"anthropic": SimpleNamespace(env_var="ANTHROPIC_API_KEY")},
    )

    ensure_credential_key_env()

    assert os.environ.get("OPENROUTER_API_KEY") == "or-key-123"
    assert "OPENROUTER_API_KEY" in calls


def test_bootstrap_does_not_override_existing_configured_llm_env_var(monkeypatch):
    monkeypatch.setattr(key_storage, "load_credential_key", lambda: None)
    monkeypatch.setattr(key_storage, "load_aden_api_key", lambda: None)
    monkeypatch.setattr(
        "framework.config.get_hive_config",
        lambda: {"llm": {"api_key_env_var": "OPENROUTER_API_KEY"}},
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "already-set")

    calls = []

    def check_env(var_name):
        calls.append(var_name)
        return True, "new-value-should-not-apply"

    _install_fake_aden_modules(monkeypatch, check_env, {})

    ensure_credential_key_env()

    assert os.environ.get("OPENROUTER_API_KEY") == "already-set"
    assert "OPENROUTER_API_KEY" not in calls
