"""Tests for framework/config.py - Hive configuration loading."""

import logging
from unittest.mock import patch

from framework.config import (
    get_api_base,
    get_hive_config,
    get_llm_extra_kwargs,
    get_preferred_model,
)
from framework.llm.codex_backend import CODEX_API_BASE, is_codex_api_base, normalize_codex_api_base


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


class TestOpenRouterConfig:
    """OpenRouter config composition and fallback behavior."""

    def test_get_preferred_model_for_openrouter(self, tmp_path, monkeypatch):
        config_file = tmp_path / "configuration.json"
        config_file.write_text(
            '{"llm":{"provider":"openrouter","model":"x-ai/grok-4.20-beta"}}',
            encoding="utf-8",
        )
        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)

        assert get_preferred_model() == "openrouter/x-ai/grok-4.20-beta"

    def test_get_preferred_model_normalizes_openrouter_prefixed_model(self, tmp_path, monkeypatch):
        config_file = tmp_path / "configuration.json"
        config_file.write_text(
            '{"llm":{"provider":"openrouter","model":"openrouter/x-ai/grok-4.20-beta"}}',
            encoding="utf-8",
        )
        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)

        assert get_preferred_model() == "openrouter/x-ai/grok-4.20-beta"

    def test_get_api_base_falls_back_to_openrouter_default(self, tmp_path, monkeypatch):
        config_file = tmp_path / "configuration.json"
        config_file.write_text(
            '{"llm":{"provider":"openrouter","model":"x-ai/grok-4.20-beta"}}',
            encoding="utf-8",
        )
        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)

        assert get_api_base() == "https://openrouter.ai/api/v1"

    def test_get_api_base_keeps_explicit_openrouter_api_base(self, tmp_path, monkeypatch):
        config_file = tmp_path / "configuration.json"
        config_file.write_text(
            (
                '{"llm":{"provider":"openrouter","model":"x-ai/grok-4.20-beta",'
                '"api_base":"https://proxy.example/v1"}}'
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)

        assert get_api_base() == "https://proxy.example/v1"


class TestCodexConfig:
    """Codex config helpers should share the same transport defaults."""

    def test_get_api_base_uses_shared_codex_backend(self, tmp_path, monkeypatch):
        config_file = tmp_path / "configuration.json"
        config_file.write_text(
            '{"llm":{"provider":"openai","model":"gpt-5.3-codex","use_codex_subscription":true}}',
            encoding="utf-8",
        )
        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)

        assert get_api_base() == CODEX_API_BASE

    def test_get_llm_extra_kwargs_uses_shared_codex_transport(self, tmp_path, monkeypatch):
        config_file = tmp_path / "configuration.json"
        config_file.write_text(
            '{"llm":{"provider":"openai","model":"gpt-5.3-codex","use_codex_subscription":true}}',
            encoding="utf-8",
        )
        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)

        with (
            patch("framework.runner.runner.get_codex_token", return_value="tok_test"),
            patch("framework.runner.runner.get_codex_account_id", return_value="acct_123"),
        ):
            kwargs = get_llm_extra_kwargs()

        assert kwargs["store"] is False
        assert kwargs["allowed_openai_params"] == ["store"]
        assert kwargs["extra_headers"] == {
            "Authorization": "Bearer tok_test",
            "User-Agent": "CodexBar",
            "ChatGPT-Account-Id": "acct_123",
        }

    def test_codex_api_base_detection_requires_real_chatgpt_origin(self):
        assert is_codex_api_base("https://chatgpt.com/backend-api/codex")
        assert is_codex_api_base("https://chatgpt.com/backend-api/codex/responses")
        assert not is_codex_api_base(
            "https://proxy.example/v1?target=https://chatgpt.com/backend-api/codex"
        )

    def test_normalize_codex_api_base_strips_only_real_responses_suffix(self):
        assert (
            normalize_codex_api_base("https://chatgpt.com/backend-api/codex/responses")
            == CODEX_API_BASE
        )
        assert (
            normalize_codex_api_base("https://proxy.example/v1/responses")
            == "https://proxy.example/v1/responses"
        )
