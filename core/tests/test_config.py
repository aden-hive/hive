"""Tests for framework/config.py - Hive configuration loading."""

import logging

from framework import config
from framework.config import get_hive_config


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


def test_get_api_base_accepts_base_url_alias(monkeypatch):
    monkeypatch.setattr(
        config,
        "get_hive_config",
        lambda: {"llm": {"provider": "openai", "model": "glm-5", "base_url": "https://api.z.ai/api/coding/paas/v4"}},
    )
    assert config.get_api_base() == "https://api.z.ai/api/coding/paas/v4"


def test_get_api_base_prefers_api_base_over_base_url(monkeypatch):
    monkeypatch.setattr(
        config,
        "get_hive_config",
        lambda: {
            "llm": {
                "provider": "openai",
                "model": "glm-5",
                "api_base": "https://primary.example/v1",
                "base_url": "https://secondary.example/v1",
            }
        },
    )
    assert config.get_api_base() == "https://primary.example/v1"
