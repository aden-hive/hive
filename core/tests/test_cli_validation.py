from __future__ import annotations

import sys
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))

import pytest
from framework.runner.runner import ValidationResult

# ---------- test fixture ----------

class _FakeArgs:
    """Minimal argparse.Namespace stand-in."""
    def __init__(self, **kw):
        self.agent_path = kw.pop("agent_path", Path("fake"))
        self.interactive = kw.pop("interactive", False)
        self.quiet = kw.pop("quiet", True)
        self.input = kw.pop("input", "")
        self.input_file = kw.pop("input_file", None)
        self.output = kw.pop("output", None)
        self.model = kw.pop("model", None)
        for k, v in kw.items():
            setattr(self, k, v)

def _runner(validation: ValidationResult, run_result_success: bool = True):
    r = MagicMock()
    r.validate.return_value = validation
    r.cleanup = MagicMock()
    r.run = AsyncMock(return_value=MagicMock(success=run_result_success))
    return r

# ---------- helpers ----------

def _run_cli(args=None):
    """Import late so every test gets a fresh patch surface."""
    from framework.runner.cli import cmd_run
    return cmd_run(args or _FakeArgs())

# ---------- tests ----------

class TestValidationErrors:
    """runner.validate() returns errors → cmd_run must abort with code 1."""

    def test_single_error_aborts(self, capsys):
        val = ValidationResult(
            valid=False, errors=["Entry node '' not found"],
            missing_tools=[], warnings=[], missing_credentials=[]
        )
        mock = _runner(val)
        with patch("framework.runner.AgentRunner.load", return_value=mock):
            code = _run_cli(_FakeArgs())
        assert code == 1
        mock.cleanup.assert_called_once()
        mock.run.assert_not_called()

        out = capsys.readouterr().out
        assert "Agent has errors:" in out
        assert "Entry node '' not found" in out

    def test_multiple_errors_all_printed(self, capsys):
        val = ValidationResult(
            valid=False,
            errors=["Node X missing", "Node Y orphan"],
            missing_tools=[], warnings=[], missing_credentials=[]
        )
        mock = _runner(val)
        with patch("framework.runner.AgentRunner.load", return_value=mock):
            code = _run_cli(_FakeArgs())
        assert code == 1
        out = capsys.readouterr().out
        assert "Node X missing" in out
        assert "Node Y orphan" in out

class TestMissingTools:
    """missing_tools list populated → must abort despite valid=True."""

    def test_missing_tools_aborts(self, capsys):
        val = ValidationResult(
            valid=True, errors=[],
            missing_tools=["web_search", "file_writer"],
            warnings=[], missing_credentials=[]
        )
        mock = _runner(val)
        with patch("framework.runner.AgentRunner.load", return_value=mock):
            code = _run_cli(_FakeArgs())
        assert code == 1
        out = capsys.readouterr().out
        assert "Missing tool implementations:" in out
        assert "web_search" in out

    def test_fix_hint_printed(self, capsys):
        val = ValidationResult(
            valid=True, errors=[],
            missing_tools=["tool_a"],
            warnings=[], missing_credentials=[]
        )
        mock = _runner(val)
        with patch("framework.runner.AgentRunner.load", return_value=mock):
            code = _run_cli(_FakeArgs())
        out = capsys.readouterr().out
        assert "Create tools.py" in out

class TestWarnings:
    """Warnings must print but must NOT block execution."""

    def test_warnings_do_not_block(self, capsys):
        val = ValidationResult(
            valid=True, errors=[], missing_tools=[],
            warnings=["Deprecated type"], missing_credentials=[]
        )
        mock = _runner(val)
        with patch("framework.runner.AgentRunner.load", return_value=mock):
            with patch("sys.stdin.isatty", return_value=False):
                with patch("framework.runner.cli._detect_agent_version", return_value=1):
                    code = _run_cli(_FakeArgs())
        out = capsys.readouterr().out
        assert "WARNING" in out or "Warnings:" in out

class TestRunProceedsWhenValid:
    """Fully valid agent → .run() must be called."""

    def test_valid_agent_proceeds(self):
        val = ValidationResult(
            valid=True, errors=[], missing_tools=[],
            warnings=[], missing_credentials=[]
        )
        mock = _runner(val)
        with patch("framework.runner.AgentRunner.load", return_value=mock):
            with patch("sys.stdin.isatty", return_value=False):
                with patch("framework.runner.cli._detect_agent_version", return_value=1):
                    code = _run_cli(_FakeArgs())
        assert code == 0
        mock.validate.assert_called_once()
        mock.run.assert_called_once()

class TestCleanupOnAllPaths:
    """runner.cleanup() must be called on every error path."""

    def test_cleanup_on_error(self):
        val = ValidationResult(valid=False, errors=["bad"], missing_tools=[], warnings=[], missing_credentials=[])
        mock = _runner(val)
        with patch("framework.runner.AgentRunner.load", return_value=mock):
            _run_cli(_FakeArgs())
        mock.cleanup.assert_called_once()

    def test_cleanup_on_missing_tools(self):
        val = ValidationResult(valid=True, errors=[], missing_tools=["x"], warnings=[], missing_credentials=[])
        mock = _runner(val)
        with patch("framework.runner.AgentRunner.load", return_value=mock):
            _run_cli(_FakeArgs())
        mock.cleanup.assert_called_once()

class TestStressConcurrency:
    """Stress: 50 back-to-back calls, ensure no state bleed."""

    def test_rapid_repeated_calls(self):
        val_invalid = ValidationResult(valid=False, errors=["e"], missing_tools=[], warnings=[], missing_credentials=[])
        val_valid = ValidationResult(valid=True, errors=[], missing_tools=[], warnings=[], missing_credentials=[])

        codes = []
        for i in range(50):
            val = val_invalid if i % 2 == 0 else val_valid
            mock = _runner(val)
            with patch("framework.runner.AgentRunner.load", return_value=mock):
                with patch("sys.stdin.isatty", return_value=False):
                    with patch("framework.runner.cli._detect_agent_version", return_value=1):
                        code = _run_cli(_FakeArgs())
            codes.append(code)

        assert codes[::2] == [1] * 25
        assert codes[1::2] == [0] * 25


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
