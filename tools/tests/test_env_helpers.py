"""Tests for environment variable helpers."""
import pytest

from aden_tools.utils import get_env_var


class TestGetEnvVar:
    """Tests for get_env_var function."""

    def test_returns_value_when_set(self, monkeypatch):
        """Returns the environment variable value when set."""
        monkeypatch.setenv("TEST_VAR", "test_value")

        result = get_env_var("TEST_VAR")

        assert result == "test_value"

    def test_returns_default_when_not_set(self, monkeypatch):
        """Returns default value when variable is not set."""
        monkeypatch.delenv("UNSET_VAR", raising=False)

        result = get_env_var("UNSET_VAR", default="default_value")

        assert result == "default_value"

    def test_returns_none_when_not_set_and_no_default(self, monkeypatch):
        """Returns None when variable is not set and no default provided."""
        monkeypatch.delenv("UNSET_VAR", raising=False)

        result = get_env_var("UNSET_VAR")

        assert result is None

    def test_raises_when_required_and_missing(self, monkeypatch):
        """Raises ValueError when required=True and variable is missing."""
        monkeypatch.delenv("REQUIRED_VAR", raising=False)

        with pytest.raises(ValueError) as exc_info:
            get_env_var("REQUIRED_VAR", required=True)

        assert "REQUIRED_VAR" in str(exc_info.value)
        assert "not set" in str(exc_info.value)

    def test_returns_value_when_required_and_set(self, monkeypatch):
        """Returns value when required=True and variable is set."""
        monkeypatch.setenv("REQUIRED_VAR", "my_value")

        result = get_env_var("REQUIRED_VAR", required=True)

        assert result == "my_value"
