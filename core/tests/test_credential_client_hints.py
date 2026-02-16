"""Tests for client-aware credential guidance messaging."""

from framework.credentials.client_hints import (
    detect_client_environment,
    get_credential_fix_guidance_lines,
)
from framework.credentials.validation import build_missing_credentials_error


CLIENT_ENV_KEYS = [
    "HIVE_CLIENT",
    "CLAUDECODE",
    "CLAUDE_CODE",
    "CODEX_HOME",
    "CODEX_SANDBOX",
    "CURSOR_TRACE_ID",
    "CURSOR_AGENT",
]


def _clear_client_env(monkeypatch) -> None:
    for key in CLIENT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_detect_client_environment_defaults_to_generic(monkeypatch):
    _clear_client_env(monkeypatch)
    assert detect_client_environment() == "generic"


def test_detect_client_environment_honors_override(monkeypatch):
    _clear_client_env(monkeypatch)
    monkeypatch.setenv("HIVE_CLIENT", "codex")
    assert detect_client_environment() == "codex"


def test_guidance_is_generic_when_client_unknown(monkeypatch):
    _clear_client_env(monkeypatch)

    guidance = "\n".join(get_credential_fix_guidance_lines())
    assert "Claude Code" not in guidance
    assert "/hive-credentials" not in guidance
    assert "set the missing environment variables" in guidance


def test_guidance_includes_skill_hint_for_known_client(monkeypatch):
    _clear_client_env(monkeypatch)
    monkeypatch.setenv("HIVE_CLIENT", "cursor")

    guidance = "\n".join(get_credential_fix_guidance_lines())
    assert "/hive-credentials" in guidance


def test_build_missing_credentials_error_is_client_agnostic_by_default(monkeypatch):
    _clear_client_env(monkeypatch)

    message = build_missing_credentials_error(["  OPENAI_API_KEY for llm_generate nodes"])
    assert "Claude Code" not in message
    assert "/hive-credentials" not in message
    assert "OPENAI_API_KEY" in message


def test_build_missing_credentials_error_can_include_skill_hint(monkeypatch):
    _clear_client_env(monkeypatch)
    monkeypatch.setenv("HIVE_CLIENT", "claude")

    message = build_missing_credentials_error(["  ANTHROPIC_API_KEY for llm_generate nodes"])
    assert "/hive-credentials" in message

