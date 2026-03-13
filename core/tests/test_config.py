"""Tests for framework/config.py - Hive configuration loading."""

import json
import logging

from framework.config import (
    get_api_base,
    get_api_key,
    get_hive_config,
    get_llm_extra_kwargs,
    resolve_llm_auth_mode,
)


class TestGetHiveConfig:
    """Test get_hive_config() logs warnings on parse errors."""

    def test_logs_warning_on_malformed_json(self, tmp_path, monkeypatch, caplog):
        """Test that malformed JSON logs warning and returns empty dict."""
        config_file = tmp_path / "configuration.json"
        config_file.write_text('{"broken": }')

        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)

        with caplog.at_level(logging.WARNING):
            result = get_hive_config()

        assert result == {}
        assert "Failed to load Hive config" in caplog.text
        assert str(config_file) in caplog.text


def _write_config(tmp_path, monkeypatch, llm: dict):
    config_file = tmp_path / "configuration.json"
    config_file.write_text(json.dumps({"llm": llm}))
    monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)


def test_api_key_auth_mode_ignores_stale_subscription_flags(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        monkeypatch,
        {
            "provider": "groq",
            "model": "openai/gpt-oss-120b",
            "auth_mode": "api_key",
            "api_key_env_var": "GROQ_API_KEY",
            "use_codex_subscription": True,  # stale legacy flag should be ignored
        },
    )
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")

    assert resolve_llm_auth_mode() == "api_key"
    assert get_api_key() == "groq-test-key"
    assert get_api_base() is None
    assert get_llm_extra_kwargs() == {}


def test_codex_auth_mode_uses_codex_token_flow(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        monkeypatch,
        {
            "provider": "openai",
            "model": "gpt-5.3-codex",
            "auth_mode": "codex",
        },
    )
    monkeypatch.setattr("framework.runner.runner.get_codex_token", lambda: "codex-token")
    monkeypatch.setattr("framework.runner.runner.get_codex_account_id", lambda: None)

    assert resolve_llm_auth_mode() == "codex"
    assert get_api_key() == "codex-token"
    assert get_api_base() == "https://chatgpt.com/backend-api/codex"

    extra = get_llm_extra_kwargs()
    assert extra["extra_headers"]["Authorization"] == "Bearer codex-token"
    assert extra["store"] is False


def test_legacy_subscription_flags_still_supported(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        monkeypatch,
        {
            "provider": "openai",
            "model": "gpt-5.3-codex",
            "use_codex_subscription": True,
        },
    )
    monkeypatch.setattr("framework.runner.runner.get_codex_token", lambda: "legacy-codex-token")

    assert resolve_llm_auth_mode() == "codex"
    assert get_api_key() == "legacy-codex-token"
