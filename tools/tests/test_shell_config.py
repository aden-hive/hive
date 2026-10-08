"""Tests for shell config path selection and env-var lookups."""

from pathlib import Path

from aden_tools.credentials import shell_config


def _mock_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shell_config.Path, "home", staticmethod(lambda: tmp_path))


def test_get_shell_config_path_prefers_existing_bash_profile(monkeypatch, tmp_path):
    _mock_home(monkeypatch, tmp_path)
    monkeypatch.setenv("SHELL", "/usr/bin/bash")
    monkeypatch.setattr(shell_config.platform, "system", lambda: "Windows")

    (tmp_path / ".bashrc").write_text("# bashrc\n", encoding="utf-8")
    (tmp_path / ".bash_profile").write_text("# bash profile\n", encoding="utf-8")

    assert shell_config.get_shell_config_path() == tmp_path / ".bash_profile"


def test_get_shell_config_path_prefers_bashrc_for_non_windows_bash(monkeypatch, tmp_path):
    _mock_home(monkeypatch, tmp_path)
    monkeypatch.setenv("SHELL", "/usr/bin/bash")
    monkeypatch.setattr(shell_config.platform, "system", lambda: "Linux")

    (tmp_path / ".bashrc").write_text("# bashrc\n", encoding="utf-8")
    (tmp_path / ".bash_profile").write_text("# bash profile\n", encoding="utf-8")

    assert shell_config.get_shell_config_path() == tmp_path / ".bashrc"


def test_check_env_var_in_shell_config_reads_bash_profile(monkeypatch, tmp_path):
    _mock_home(monkeypatch, tmp_path)
    monkeypatch.setenv("SHELL", "/usr/bin/bash")
    monkeypatch.setattr(shell_config.platform, "system", lambda: "Windows")

    (tmp_path / ".bash_profile").write_text(
        'export HIVE_API_KEY="hive-key-123"\n',
        encoding="utf-8",
    )

    assert shell_config.check_env_var_in_shell_config("HIVE_API_KEY") == (
        True,
        "hive-key-123",
    )


def test_check_env_var_in_shell_config_falls_back_to_bashrc_on_windows(monkeypatch, tmp_path):
    _mock_home(monkeypatch, tmp_path)
    monkeypatch.setenv("SHELL", "/usr/bin/bash")
    monkeypatch.setattr(shell_config.platform, "system", lambda: "Windows")

    (tmp_path / ".bash_profile").write_text("# no key here\n", encoding="utf-8")
    (tmp_path / ".bashrc").write_text(
        'export HIVE_API_KEY="hive-key-from-bashrc"\n',
        encoding="utf-8",
    )

    assert shell_config.check_env_var_in_shell_config("HIVE_API_KEY") == (
        True,
        "hive-key-from-bashrc",
    )


def test_check_env_var_in_shell_config_reads_zshenv_when_zshrc_missing(monkeypatch, tmp_path):
    _mock_home(monkeypatch, tmp_path)
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(shell_config.platform, "system", lambda: "Darwin")

    (tmp_path / ".zshenv").write_text(
        "export OPENROUTER_API_KEY='or-key-123'\n",
        encoding="utf-8",
    )

    assert shell_config.check_env_var_in_shell_config("OPENROUTER_API_KEY") == (
        True,
        "or-key-123",
    )


def test_get_shell_config_path_falls_back_to_profile_for_unknown_shell(monkeypatch, tmp_path):
    _mock_home(monkeypatch, tmp_path)
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    monkeypatch.setattr(shell_config.platform, "system", lambda: "Linux")

    (tmp_path / ".profile").write_text("# profile\n", encoding="utf-8")

    assert shell_config.get_shell_config_path() == tmp_path / ".profile"
