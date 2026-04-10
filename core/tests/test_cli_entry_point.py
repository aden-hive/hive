"""Tests for the hive CLI entry point and path auto-configuration."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from framework.cli import _configure_paths


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return Path(__file__).resolve().parent.parent.parent


class TestConfigurePaths:
    """Test _configure_paths auto-discovers core/."""

    def test_adds_core_to_sys_path(self, project_root):
        core_dir = project_root / "core"
        core_str = str(core_dir)
        original_path = sys.path.copy()
        sys.path = [p for p in sys.path if p != core_str]

        try:
            _configure_paths()
            assert core_str in sys.path
        finally:
            sys.path = original_path

    def test_does_not_duplicate_paths(self):
        _configure_paths()
        before = sys.path.copy()
        _configure_paths()
        assert sys.path == before


class TestFrameworkModule:
    """Test ``python -m framework`` invocation."""

    def test_module_help(self, project_root):
        result = subprocess.run(
            [sys.executable, "-m", "framework", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(project_root / "core"),
        )
        assert result.returncode == 0
        assert "hive" in result.stdout.lower()

    def test_module_serve_subcommand(self, project_root):
        """Verify ``python -m framework serve --help`` prints usage."""
        result = subprocess.run(
            [sys.executable, "-m", "framework", "serve", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(project_root / "core"),
        )
        assert result.returncode == 0
        assert "host" in result.stdout.lower() or "port" in result.stdout.lower()


class TestHiveEntryPoint:
    """Test the ``hive`` console_scripts entry point."""

    @pytest.fixture(autouse=True)
    def _require_hive(self):
        if shutil.which("hive") is None:
            pytest.skip("'hive' entry point not installed (run: pip install -e core/)")

    def test_hive_help(self):
        """Verify ``hive --help`` exits 0 and lists the new commands."""
        result = subprocess.run(
            ["hive", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0
        out = result.stdout.lower()
        # New CLI surface (post-cleanup)
        assert "serve" in out
        assert "queen" in out
        assert "colony" in out
        assert "session" in out
        assert "chat" in out

    def test_hive_queen_list_help(self):
        """``hive queen list --help`` is one of the new core commands."""
        result = subprocess.run(
            ["hive", "queen", "list", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0

    def test_hive_colony_list_help(self):
        """``hive colony list --help`` is one of the new core commands."""
        result = subprocess.run(
            ["hive", "colony", "list", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0

    def test_hive_unknown_command_exits_nonzero(self):
        """An unknown subcommand must error out."""
        result = subprocess.run(
            ["hive", "definitely-not-a-command"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode != 0
