import json
import pytest
from pathlib import Path

from framework.config import get_hive_config, HIVE_CONFIG_FILE


def test_invalid_json_config_raises(monkeypatch, tmp_path):
    bad_config = tmp_path / "configuration.json"
    bad_config.write_text('{ "llm": "x", }')

    monkeypatch.setattr(
        "framework.config.HIVE_CONFIG_FILE",
        bad_config,
    )

    with pytest.raises(ValueError) as exc:
        get_hive_config()

    msg = str(exc.value)
    assert "Invalid JSON in Hive configuration file" in msg
    assert str(bad_config) in msg


def test_missing_config_returns_empty(monkeypatch):
    fake_path = Path("/tmp/does_not_exist.json")

    monkeypatch.setattr(
        "framework.config.HIVE_CONFIG_FILE",
        fake_path,
    )

    assert get_hive_config() == {}
