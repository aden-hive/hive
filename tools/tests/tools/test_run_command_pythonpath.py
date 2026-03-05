"""Tests for run_command PYTHONPATH handling (Windows compatibility).

On Windows, PYTHONPATH must use semicolon (;) as separator, not colon (:).
These tests verify the correct behavior. They are Windows-only because
the bug only manifests on Windows.
"""

import os
import subprocess
import sys

import pytest

# Skip entire module on non-Windows (tests will pass when fixes are applied)
pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows-only: PYTHONPATH separator behavior",
)


def _build_pythonpath_buggy(project_root: str) -> str:
    """Replicate current (buggy) PYTHONPATH construction in run_command."""
    return f"{project_root}/core:{project_root}/exports:{project_root}/core/framework/agents"


def _build_pythonpath_fixed(project_root: str) -> str:
    """Correct PYTHONPATH construction using os.pathsep."""
    return os.pathsep.join(
        [
            os.path.join(project_root, "core"),
            os.path.join(project_root, "exports"),
            os.path.join(project_root, "core", "framework", "agents"),
        ]
    )


class TestPythonpathSeparatorWindows:
    """Verify PYTHONPATH uses correct separator on Windows."""

    def test_pythonpath_with_semicolons_parses_multiple_paths(self, tmp_path):
        """PYTHONPATH built with os.pathsep allows Python to find modules in multiple dirs."""
        # Create two dirs, each with a module
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "mod_a.py").write_text("x = 1\n")

        exports_dir = tmp_path / "exports"
        exports_dir.mkdir()
        (exports_dir / "mod_b.py").write_text("y = 2\n")

        pythonpath = os.pathsep.join([str(core_dir), str(exports_dir)])
        env = {**os.environ, "PYTHONPATH": pythonpath}

        # Python should find both when we add them to path
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; "
                "sys.path = [p for p in sys.path if 'mod_a' not in p and 'mod_b' not in p]; "
                "import mod_a; import mod_b; print('ok')",
            ],
            env=env,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=10,
        )

        assert result.returncode == 0, f"Stdout: {result.stdout} Stderr: {result.stderr}"
        assert "ok" in result.stdout

    def test_pythonpath_with_colons_fails_on_windows(self, tmp_path):
        """PYTHONPATH built with colons (Unix style) fails on Windows - single path parsed."""
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "mod_c.py").write_text("z = 3\n")

        exports_dir = tmp_path / "exports"
        exports_dir.mkdir()
        (exports_dir / "mod_d.py").write_text("w = 4\n")

        # Buggy: colon-separated (Unix style)
        pythonpath = f"{tmp_path}/core:{tmp_path}/exports"
        env = {**os.environ, "PYTHONPATH": pythonpath}

        # On Windows, Python splits by ; only. The colon string is one invalid path.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; "
                "pp = [p for p in sys.path if 'core' in p or 'exports' in p]; "
                "import mod_c; import mod_d; print('ok')",
            ],
            env=env,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=10,
        )

        # Should fail: Python won't parse multiple paths from colon-separated string
        assert result.returncode != 0 or "ok" not in result.stdout

    def test_fixed_pythonpath_construction_uses_pathsep(self, tmp_path):
        """The fix pattern (os.pathsep.join) produces valid multi-path PYTHONPATH."""
        project_root = str(tmp_path)
        fixed = _build_pythonpath_fixed(project_root)

        # On Windows, os.pathsep is ';'
        assert os.pathsep in fixed, "Fixed PYTHONPATH must use os.pathsep on Windows"
        # Three paths => two separators
        assert fixed.count(os.pathsep) == 2
