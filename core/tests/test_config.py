"""Tests for framework/config.py - Hive configuration loading."""

import json
import logging

import pytest

from framework.config import get_api_base, get_hive_config, get_preferred_model


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
            '{"llm":{"provider":"openrouter","model":"x-ai/grok-4.20-beta","api_base":"https://proxy.example/v1"}}',
            encoding="utf-8",
        )
        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)

        assert get_api_base() == "https://proxy.example/v1"


class TestGetPreferredModel:
    """Test get_preferred_model() provider/model resolution."""

    @pytest.fixture()
    def _config_file(self, tmp_path, monkeypatch):
        """Provide a helper that writes a config and patches the path."""
        config_file = tmp_path / "configuration.json"
        monkeypatch.setattr("framework.config.HIVE_CONFIG_FILE", config_file)
        return config_file

    def test_returns_default_when_no_config(self, _config_file):
        """No config file → default Anthropic model."""
        assert get_preferred_model() == "anthropic/claude-sonnet-4-20250514"

    def test_prepends_provider_when_model_has_no_prefix(self, _config_file):
        """model='qwen2.5:7b' + provider='ollama' → 'ollama/qwen2.5:7b'."""
        _config_file.write_text(json.dumps({"llm": {"provider": "ollama", "model": "qwen2.5:7b"}}))
        assert get_preferred_model() == "ollama/qwen2.5:7b"

    def test_no_double_prefix_when_model_already_includes_provider(self, _config_file):
        """model='ollama/qwen2.5:7b' + provider='ollama' → 'ollama/qwen2.5:7b' (not doubled)."""
        _config_file.write_text(
            json.dumps({"llm": {"provider": "ollama", "model": "ollama/qwen2.5:7b"}})
        )
        assert get_preferred_model() == "ollama/qwen2.5:7b"

    def test_anthropic_provider_with_full_model_string(self, _config_file):
        """model='anthropic/claude-sonnet-4-20250514' + provider='anthropic' → no double prefix."""
        _config_file.write_text(
            json.dumps(
                {"llm": {"provider": "anthropic", "model": "anthropic/claude-sonnet-4-20250514"}}
            )
        )
        assert get_preferred_model() == "anthropic/claude-sonnet-4-20250514"

    def test_returns_default_when_provider_missing(self, _config_file):
        """Only model set, no provider → default."""
        _config_file.write_text(json.dumps({"llm": {"model": "qwen2.5:7b"}}))
        assert get_preferred_model() == "anthropic/claude-sonnet-4-20250514"
