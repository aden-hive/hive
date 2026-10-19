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


# ---------------------------------------------------------------------------
# HIVE_CREDENTIAL_KEY env-to-disk persistence
# ---------------------------------------------------------------------------
#
# Without persisting an env-provided key to ``~/.hive/secrets/credential_key``,
# a process that boots with HIVE_CREDENTIAL_KEY only in its environment
# (e.g. hive serve under supervisord in a sandbox VM, where the parent
# env doesn't survive a process restart) encrypts credentials with an
# in-memory key, then loses it on restart — the .enc files on the
# persistent volume become permanently undecryptable. The patch in
# key_storage.py:_persist_key_if_missing_or_stale closes this loop.


def test_load_credential_key_persists_env_value_to_disk(monkeypatch, tmp_path):
    """Env-sourced key gets written to ``credential_key`` file so a
    subsequent boot without the env var can recover the same key."""
    key_path = tmp_path / "secrets" / "credential_key"
    monkeypatch.setattr(key_storage, "CREDENTIAL_KEY_PATH", key_path)
    monkeypatch.setenv("HIVE_CREDENTIAL_KEY", "env-key-abc")

    loaded = key_storage.load_credential_key()

    assert loaded == "env-key-abc"
    assert key_path.is_file()
    assert key_path.read_text(encoding="utf-8") == "env-key-abc"


def test_load_credential_key_overwrites_stale_disk_value_with_env(monkeypatch, tmp_path):
    """When env and file disagree, env wins (already current behavior),
    AND the file gets overwritten so a future restart-without-env reads
    the key the encrypted store was actually written with."""
    key_path = tmp_path / "secrets" / "credential_key"
    key_path.parent.mkdir(parents=True)
    key_path.write_text("disk-old-key", encoding="utf-8")
    monkeypatch.setattr(key_storage, "CREDENTIAL_KEY_PATH", key_path)
    monkeypatch.setenv("HIVE_CREDENTIAL_KEY", "env-new-key")

    loaded = key_storage.load_credential_key()

    assert loaded == "env-new-key"
    assert key_path.read_text(encoding="utf-8") == "env-new-key"


def test_load_credential_key_skips_write_when_env_and_file_match(monkeypatch, tmp_path):
    """Idempotent path: identical env + file means no unnecessary write
    (avoids churning mtime on the credential_key file every boot)."""
    key_path = tmp_path / "secrets" / "credential_key"
    key_path.parent.mkdir(parents=True)
    key_path.write_text("same-key", encoding="utf-8")
    original_mtime = key_path.stat().st_mtime_ns
    monkeypatch.setattr(key_storage, "CREDENTIAL_KEY_PATH", key_path)
    monkeypatch.setenv("HIVE_CREDENTIAL_KEY", "same-key")

    loaded = key_storage.load_credential_key()

    assert loaded == "same-key"
    assert key_path.stat().st_mtime_ns == original_mtime


def test_load_credential_key_from_disk_does_not_rewrite_itself(monkeypatch, tmp_path):
    """When the env var is absent and the key comes from disk, we don't
    need to write the file back — it's already there. Guards against an
    accidental double-write loop on every boot."""
    key_path = tmp_path / "secrets" / "credential_key"
    key_path.parent.mkdir(parents=True)
    key_path.write_text("from-disk", encoding="utf-8")
    original_mtime = key_path.stat().st_mtime_ns
    monkeypatch.setattr(key_storage, "CREDENTIAL_KEY_PATH", key_path)
    monkeypatch.delenv("HIVE_CREDENTIAL_KEY", raising=False)

    loaded = key_storage.load_credential_key()

    assert loaded == "from-disk"
    assert os.environ.get("HIVE_CREDENTIAL_KEY") == "from-disk"
    assert key_path.stat().st_mtime_ns == original_mtime


def test_load_credential_key_swallows_persistence_failure(monkeypatch, tmp_path, caplog):
    """Best-effort write: a permission error on the credential_key file
    must not turn a successful load into a failure. The in-memory key
    is still usable for THIS process; the warning surfaces the durability
    risk for forensics. Guards against making a degraded boot fatal."""
    key_path = tmp_path / "readonly" / "secrets" / "credential_key"
    monkeypatch.setattr(key_storage, "CREDENTIAL_KEY_PATH", key_path)
    monkeypatch.setenv("HIVE_CREDENTIAL_KEY", "env-key")

    def explode(*_args, **_kwargs):
        raise PermissionError("simulated read-only fs")

    monkeypatch.setattr(key_storage, "save_credential_key", explode)

    loaded = key_storage.load_credential_key()

    assert loaded == "env-key"  # in-memory load still works
    assert "failed to persist HIVE_CREDENTIAL_KEY" in caplog.text
