"""Tests for hive doctor environment diagnostics (framework.runner.doctor)."""

from pathlib import Path

import pytest

from framework.runner.doctor import (
    CheckResult,
    run_doctor_checks,
)


class TestCheckResult:
    """Test CheckResult dataclass and serialization."""

    def test_to_dict(self):
        r = CheckResult(
            name="test_check",
            passed=True,
            message="OK",
            suggestion=None,
        )
        d = r.to_dict()
        assert d["name"] == "test_check"
        assert d["passed"] is True
        assert d["message"] == "OK"
        assert d["suggestion"] is None

    def test_to_dict_with_suggestion(self):
        r = CheckResult(
            name="fail",
            passed=False,
            message="Missing",
            suggestion="Run quickstart.sh",
        )
        d = r.to_dict()
        assert d["suggestion"] == "Run quickstart.sh"


class TestRunDoctorChecks:
    """Test run_doctor_checks with explicit project_root (e.g. tmp or fixture)."""

    def test_returns_list_of_check_results(self, tmp_path):
        """run_doctor_checks returns a list of CheckResult of expected length."""
        # Minimal layout: no core/tools so many checks will fail
        results = run_doctor_checks(project_root=tmp_path, skip_network=True)
        assert isinstance(results, list)
        assert all(isinstance(r, CheckResult) for r in results)
        # We have: Python, .python-version, Node, uv, ripgrep, core pyproject,
        # tools pyproject, core venv, tools venv, LLM env, optional env,
        # hive config, exports, network(skipped) = 14
        assert len(results) >= 12

    def test_python_version_check_passes_with_current_interpreter(self, tmp_path):
        """Python version check should pass when running on 3.11+."""
        results = run_doctor_checks(project_root=tmp_path, skip_network=True)
        python_check = next((r for r in results if r.name == "Python version"), None)
        assert python_check is not None
        # Current interpreter is 3.11+ in CI and dev
        assert python_check.passed is True
        assert "3." in python_check.message

    def test_core_pyproject_check_fails_when_missing(self, tmp_path):
        """core/pyproject.toml check fails when file is missing."""
        results = run_doctor_checks(project_root=tmp_path, skip_network=True)
        check = next((r for r in results if r.name == "core/pyproject.toml"), None)
        assert check is not None
        assert check.passed is False
        assert "suggestion" in (check.suggestion or "").lower() or "Not found" in check.message

    def test_core_pyproject_check_passes_when_exists(self, tmp_path):
        """core/pyproject.toml check passes when file exists."""
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "pyproject.toml").write_text("[project]\nname = \"framework\"")
        results = run_doctor_checks(project_root=tmp_path, skip_network=True)
        check = next((r for r in results if r.name == "core/pyproject.toml"), None)
        assert check is not None
        assert check.passed is True

    def test_network_check_skipped_when_skip_network_true(self, tmp_path):
        """Network check is skipped when skip_network=True."""
        results = run_doctor_checks(project_root=tmp_path, skip_network=True)
        net_check = next((r for r in results if r.name == "Network (LLM API)"), None)
        assert net_check is not None
        assert "kip" in net_check.message.lower() or "Skipped" in net_check.message

    def test_llm_env_check_exists_and_has_suggestion_when_failed(self, tmp_path):
        """LLM API key check exists; when it fails, a suggestion is provided."""
        results = run_doctor_checks(project_root=tmp_path, skip_network=True)
        llm_check = next((r for r in results if r.name == "LLM API key"), None)
        assert llm_check is not None
        if not llm_check.passed:
            assert llm_check.suggestion is not None
            assert "ANTHROPIC" in llm_check.suggestion or "OPENAI" in llm_check.suggestion
