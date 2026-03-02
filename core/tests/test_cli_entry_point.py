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
    """Test _configure_paths auto-discovers exports/ and core/."""

    def test_adds_exports_to_sys_path(self, project_root):
        exports_dir = project_root / "exports"
        if not exports_dir.is_dir():
            pytest.skip("exports/ directory does not exist in this environment")

        exports_str = str(exports_dir)
        # Remove if already present to test fresh addition
        original_path = sys.path.copy()
        sys.path = [p for p in sys.path if p != exports_str]

        try:
            _configure_paths()
            assert exports_str in sys.path
        finally:
            sys.path = original_path

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
        # Call twice — should not create duplicates
        before = sys.path.copy()
        _configure_paths()
        assert sys.path == before

    def test_handles_missing_exports_gracefully(self):
        """If exports/ doesn't exist, _configure_paths should not crash."""
        _configure_paths()


class TestFrameworkModule:
    """Test ``python -m framework`` invocation (the underlying module)."""

    def test_module_help(self, project_root):
        """Verify ``python -m framework --help`` prints usage."""
        result = subprocess.run(
            [sys.executable, "-m", "framework", "--help"],
            capture_output=True,
            text=True,
            cwd=str(project_root / "core"),
        )
        assert result.returncode == 0
        assert "hive" in result.stdout.lower() or "goal" in result.stdout.lower()

    def test_module_list_subcommand(self, project_root):
        """Verify ``python -m framework list --help`` registers the subcommand."""
        result = subprocess.run(
            [sys.executable, "-m", "framework", "list", "--help"],
            capture_output=True,
            text=True,
            cwd=str(project_root / "core"),
        )
        assert result.returncode == 0
        assert "agents" in result.stdout.lower() or "directory" in result.stdout.lower()


class TestHiveEntryPoint:
    """Test the ``hive`` console_scripts entry point.

    These tests verify the actual ``hive`` command installed by
    ``pip install -e core/``. If the entry point is not installed,
    the tests are skipped gracefully.
    """

    @pytest.fixture(autouse=True)
    def _require_hive(self):
        if shutil.which("hive") is None:
            pytest.skip("'hive' entry point not installed (run: pip install -e core/)")

    def test_hive_help(self):
        """Verify ``hive --help`` exits 0 and prints usage."""
        result = subprocess.run(
            ["hive", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "run" in result.stdout.lower()
        assert "validate" in result.stdout.lower()

    def test_hive_list_help(self):
        """Verify ``hive list --help`` exits 0."""
        result = subprocess.run(
            ["hive", "list", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_hive_run_missing_agent(self):
        """Verify ``hive run`` with a non-existent agent prints an error."""
        result = subprocess.run(
            ["hive", "run", "nonexistent_agent_xyz"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
