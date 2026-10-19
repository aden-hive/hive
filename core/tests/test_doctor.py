"""Tests for the hive doctor CLI command."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Subprocess env that forces UTF-8 so emoji output doesn't crash on Windows.
_UTF8_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return Path(__file__).resolve().parent.parent.parent


class TestDoctorSubcommand:
    """Test `hive doctor` CLI subcommand registration and execution."""

    def test_doctor_help(self, project_root):
        """Verify ``python -m framework doctor --help`` prints usage and exits 0."""
        result = subprocess.run(
            [sys.executable, "-m", "framework", "doctor", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(project_root / "core"),
            env=_UTF8_ENV,
        )
        assert result.returncode == 0
        assert "diagnostic" in result.stdout.lower() or "doctor" in result.stdout.lower()

    def test_doctor_runs(self, project_root):
        """Verify ``python -m framework doctor`` runs without crashing.

        The command may report missing credentials (exit code 1) or all-clear
        (exit code 0) depending on the environment — either is acceptable.
        The key assertion is that it does NOT crash with an unhandled exception.
        """
        result = subprocess.run(
            [sys.executable, "-m", "framework", "doctor"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(project_root / "core"),
            env=_UTF8_ENV,
            timeout=60,
        )
        # Should exit cleanly (0 = all ok, 1 = issues found)
        assert result.returncode in (0, 1), (
            f"doctor crashed with exit code {result.returncode}.\n"
            f"stdout: {result.stdout[-500:]}\n"
            f"stderr: {result.stderr[-500:]}"
        )
        # Should produce the doctor header
        assert "Hive Doctor" in result.stdout

    def test_doctor_verify_flag(self, project_root):
        """Verify ``python -m framework doctor --verify`` is accepted."""
        result = subprocess.run(
            [sys.executable, "-m", "framework", "doctor", "--verify"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(project_root / "core"),
            env=_UTF8_ENV,
            timeout=120,
        )
        assert result.returncode in (0, 1)
        assert "Hive Doctor" in result.stdout

    def test_existing_commands_still_work(self, project_root):
        """Ensure adding doctor didn't break existing subcommands."""
        result = subprocess.run(
            [sys.executable, "-m", "framework", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(project_root / "core"),
            env=_UTF8_ENV,
        )
        assert result.returncode == 0
        # Existing commands should still appear
        assert "run" in result.stdout.lower()
        assert "validate" in result.stdout.lower()
        # Doctor should also appear
        assert "doctor" in result.stdout.lower()
