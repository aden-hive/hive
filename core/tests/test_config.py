"""Tests for framework/config.py - Hive configuration loading."""

import json
import logging

from framework.config import (
    get_api_base,
    get_api_key,
    get_hive_config,
    get_llm_extra_kwargs,
    get_llm_runtime_fingerprint,
    resolve_llm_auth_mode,
)


def _write_config(config_file, payload) -> None:
    config_file.write_text(json.dumps(payload), encoding="utf-8")


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


class TestLLMAuthMode:
    def test_explicit_api_key_auth_mode_ignores_stale_subscription_flags(
        self, tmp_path, monkeypatch
    ):
        config_file = tmp_path / "configuration.json"
        _write_config(
            config_file,
            {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4.1",
                    "auth_mode": "api_key",
                    "api_key_env_var": "OPENAI_API_KEY",
                    "api_base": "https://api.openai.com/v1",
                    "use_codex_subscription": True,
                }
            },
        )

        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)
        monkeypatch.setenv("OPENAI_API_KEY", "api-key-123")

        assert resolve_llm_auth_mode() == "api_key"
        assert get_api_key() == "api-key-123"
        assert get_api_base() == "https://api.openai.com/v1"
        assert get_llm_extra_kwargs() == {}

    def test_codex_auth_mode_uses_codex_backend_and_headers(self, tmp_path, monkeypatch):
        config_file = tmp_path / "configuration.json"
        _write_config(
            config_file,
            {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-5.3-codex",
                    "auth_mode": "codex",
                }
            },
        )

        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)
        monkeypatch.setattr("framework.runner.runner.get_codex_token", lambda: "codex-token")
        monkeypatch.setattr("framework.runner.runner.get_codex_account_id", lambda: "acct-123")

        assert resolve_llm_auth_mode() == "codex"
        assert get_api_key() == "codex-token"
        assert get_api_base() == "https://chatgpt.com/backend-api/codex"
        assert get_llm_extra_kwargs() == {
            "extra_headers": {
                "Authorization": "Bearer codex-token",
                "User-Agent": "CodexBar",
                "ChatGPT-Account-Id": "acct-123",
            },
            "store": False,
            "allowed_openai_params": ["store"],
        }

    def test_legacy_subscription_flags_still_resolve(self, tmp_path, monkeypatch):
        config_file = tmp_path / "configuration.json"
        _write_config(
            config_file,
            {
                "llm": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-20250514",
                    "use_claude_code_subscription": True,
                }
            },
        )

        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)

        assert resolve_llm_auth_mode() == "claude_code"

    def test_runtime_fingerprint_changes_when_auth_mode_changes(self, tmp_path, monkeypatch):
        config_file = tmp_path / "configuration.json"
        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)

        _write_config(
            config_file,
            {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-5.3-codex",
                    "auth_mode": "codex",
                }
            },
        )
        monkeypatch.setattr("framework.runner.runner.get_codex_token", lambda: "codex-token")
        codex_fingerprint = get_llm_runtime_fingerprint()

        _write_config(
            config_file,
            {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4.1",
                    "auth_mode": "api_key",
                    "api_key_env_var": "OPENAI_API_KEY",
                }
            },
        )
        monkeypatch.setenv("OPENAI_API_KEY", "api-key-123")
        api_key_fingerprint = get_llm_runtime_fingerprint()

        assert codex_fingerprint != api_key_fingerprint

    def test_runtime_fingerprint_ignores_rotating_subscription_tokens(self, tmp_path, monkeypatch):
        config_file = tmp_path / "configuration.json"
        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)
        _write_config(
            config_file,
            {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-5.3-codex",
                    "auth_mode": "codex",
                }
            },
        )
        monkeypatch.setattr("framework.runner.runner.get_codex_token", lambda: "codex-token-1")
        first = get_llm_runtime_fingerprint()

        monkeypatch.setattr("framework.runner.runner.get_codex_token", lambda: "codex-token-2")
        second = get_llm_runtime_fingerprint()

        assert first == second
