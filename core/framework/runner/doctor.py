"""
Environment diagnostics for Hive (hive doctor).

Runs checks for Python/Node versions, dependencies, env vars, config files,
and optional network connectivity. Used by the `hive doctor` CLI command to
help developers diagnose setup issues before running agents.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Minimum Python version required by core/pyproject.toml (requires-python = ">=3.11")
MIN_PYTHON_MAJOR = 3
MIN_PYTHON_MINOR = 11

# Node is optional (only needed for frontend); minimum from root package.json engines
MIN_NODE_MAJOR = 20

# LLM env vars: at least one must be set for running agents (see docs/configuration.md)
LLM_ENV_VARS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "CEREBRAS_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
]

# Optional env vars (tools, etc.)
OPTIONAL_ENV_VARS = [
    "BRAVE_SEARCH_API_KEY",
    "EXA_API_KEY",
]

# Endpoint used for optional network check (Anthropic; most users need this for agents)
NETWORK_CHECK_URL = "https://api.anthropic.com"
NETWORK_CHECK_TIMEOUT_SEC = 5


@dataclass
class CheckResult:
    """Result of a single doctor check."""

    name: str
    passed: bool
    message: str
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output."""
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "suggestion": self.suggestion,
        }


def _project_root_from_runner() -> Path:
    """Resolve project root: runner/doctor.py -> runner -> framework -> core -> project root."""
    this_file = Path(__file__).resolve()
    return this_file.parent.parent.parent.parent


def _check_python_version(project_root: Path) -> CheckResult:
    """Verify Python version meets project requirement (>=3.11)."""
    major, minor = sys.version_info.major, sys.version_info.minor
    version_str = f"{major}.{minor}.{sys.version_info.micro}"
    if major > MIN_PYTHON_MAJOR or (major == MIN_PYTHON_MAJOR and minor >= MIN_PYTHON_MINOR):
        return CheckResult(
            name="Python version",
            passed=True,
            message=f"Python {version_str} (>= {MIN_PYTHON_MAJOR}.{MIN_PYTHON_MINOR} required)",
        )
    return CheckResult(
        name="Python version",
        passed=False,
        message=f"Python {version_str} (project requires >= {MIN_PYTHON_MAJOR}.{MIN_PYTHON_MINOR})",
        suggestion="Install Python 3.11+ from https://www.python.org/downloads/ or use pyenv.",
    )


def _check_python_version_file(project_root: Path) -> CheckResult:
    """Check .python-version exists and matches current interpreter (informational)."""
    pv_path = project_root / ".python-version"
    if not pv_path.exists():
        return CheckResult(
            name=".python-version",
            passed=True,
            message="Not found (optional; uv/pyenv use it for version pinning)",
        )
    try:
        requested = pv_path.read_text().strip()
    except OSError:
        return CheckResult(
            name=".python-version",
            passed=False,
            message="File exists but could not be read",
        )
    current = f"{sys.version_info.major}.{sys.version_info.minor}"
    if requested == current or requested.startswith(current):
        return CheckResult(
            name=".python-version",
            passed=True,
            message=f"Set to {requested} (current: {current})",
        )
    return CheckResult(
        name=".python-version",
        passed=False,
        message=f"File requests {requested} but current Python is {current}",
        suggestion="Run `uv sync` in core/ and tools/ or switch interpreter to match.",
    )


def _check_node_version(project_root: Path) -> CheckResult:
    """Check Node.js version if available (optional; required only for frontend)."""
    node_path = shutil.which("node")
    if not node_path:
        return CheckResult(
            name="Node.js",
            passed=True,
            message="Not found (optional; only needed for frontend: npm run frontend:dev)",
        )
    try:
        out = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CheckResult(
            name="Node.js",
            passed=False,
            message="node found but version check failed",
        )
    if out.returncode != 0:
        return CheckResult(
            name="Node.js",
            passed=False,
            message="node found but version check failed",
        )
    raw = out.stdout.strip().lstrip("v")
    parts = raw.split(".")
    try:
        major = int(parts[0]) if parts else 0
    except ValueError:
        major = 0
    if major >= MIN_NODE_MAJOR:
        return CheckResult(
            name="Node.js",
            passed=True,
            message=f"v{raw} (>= {MIN_NODE_MAJOR} required for frontend)",
        )
    return CheckResult(
        name="Node.js",
        passed=False,
        message=f"v{raw} (project recommends >= {MIN_NODE_MAJOR} for frontend)",
        suggestion="Upgrade Node from https://nodejs.org/ or use nvm.",
    )


def _check_uv(project_root: Path) -> CheckResult:
    """Check that uv is on PATH (required for install/sync)."""
    if shutil.which("uv"):
        return CheckResult(
            name="uv",
            passed=True,
            message="Found on PATH (Python package manager)",
        )
    return CheckResult(
        name="uv",
        passed=False,
        message="Not found on PATH",
        suggestion="Install uv: https://docs.astral.sh/uv/getting-started/installation/",
    )


def _check_ripgrep(project_root: Path) -> CheckResult:
    """Check ripgrep (rg) - optional but recommended for search_files tool."""
    if shutil.which("rg"):
        return CheckResult(
            name="ripgrep (rg)",
            passed=True,
            message="Found (used by search_files tool)",
        )
    return CheckResult(
        name="ripgrep (rg)",
        passed=False,
        message="Not found",
        suggestion="Optional. On Windows: winget install BurntSushi.ripgrep or scoop install ripgrep.",
    )


def _check_core_pyproject(project_root: Path) -> CheckResult:
    """Verify core/pyproject.toml exists."""
    path = project_root / "core" / "pyproject.toml"
    if path.is_file():
        return CheckResult(
            name="core/pyproject.toml",
            passed=True,
            message=f"Found at {path}",
        )
    return CheckResult(
        name="core/pyproject.toml",
        passed=False,
        message=f"Not found at {path}",
        suggestion="Ensure you are in the Hive repo root (clone from https://github.com/adenhq/hive).",
    )


def _check_tools_pyproject(project_root: Path) -> CheckResult:
    """Verify tools/pyproject.toml exists."""
    path = project_root / "tools" / "pyproject.toml"
    if path.is_file():
        return CheckResult(
            name="tools/pyproject.toml",
            passed=True,
            message=f"Found at {path}",
        )
    return CheckResult(
        name="tools/pyproject.toml",
        passed=False,
        message=f"Not found at {path}",
        suggestion="Ensure you are in the Hive repo root.",
    )


def _check_core_venv(project_root: Path) -> CheckResult:
    """Check that core virtualenv exists (created by uv sync in core/)."""
    venv = project_root / "core" / ".venv"
    if venv.is_dir():
        return CheckResult(
            name="core/.venv",
            passed=True,
            message="Found (run `uv sync` in core/ if you see import errors)",
        )
    return CheckResult(
        name="core/.venv",
        passed=False,
        message="Not found",
        suggestion="Run: cd core && uv sync (or run ./quickstart.sh from repo root).",
    )


def _check_tools_venv(project_root: Path) -> CheckResult:
    """Check that tools virtualenv exists (created by uv sync in tools/)."""
    venv = project_root / "tools" / ".venv"
    if venv.is_dir():
        return CheckResult(
            name="tools/.venv",
            passed=True,
            message="Found",
        )
    return CheckResult(
        name="tools/.venv",
        passed=False,
        message="Not found",
        suggestion="Run: cd tools && uv sync (or run ./quickstart.sh from repo root).",
    )


def _check_llm_env_vars(project_root: Path) -> CheckResult:
    """At least one LLM API key must be set for running agents."""
    set_vars = [v for v in LLM_ENV_VARS if os.environ.get(v, "").strip()]
    if set_vars:
        return CheckResult(
            name="LLM API key",
            passed=True,
            message=f"At least one set: {', '.join(set_vars)}",
        )
    return CheckResult(
        name="LLM API key",
        passed=False,
        message="None of ANTHROPIC_API_KEY, OPENAI_API_KEY, etc. are set",
        suggestion="Set one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY. See docs/configuration.md.",
    )


def _check_optional_env_vars(project_root: Path) -> CheckResult:
    """Report status of optional env vars (no fail)."""
    set_opt = [v for v in OPTIONAL_ENV_VARS if os.environ.get(v, "").strip()]
    if set_opt:
        return CheckResult(
            name="Optional env (search, etc.)",
            passed=True,
            message=f"Set: {', '.join(set_opt)}",
        )
    return CheckResult(
        name="Optional env (search, etc.)",
        passed=True,
        message="None set (optional: BRAVE_SEARCH_API_KEY, EXA_API_KEY for web search tools)",
    )


def _check_hive_config(project_root: Path) -> CheckResult:
    """Check ~/.hive/configuration.json (created by quickstart)."""
    config_path = Path.home() / ".hive" / "configuration.json"
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text())
            if isinstance(data, dict) and "llm" in data:
                return CheckResult(
                    name="~/.hive/configuration.json",
                    passed=True,
                    message="Found and valid (default LLM config)",
                )
            return CheckResult(
                name="~/.hive/configuration.json",
                passed=False,
                message="File exists but missing 'llm' key",
                suggestion="Re-run quickstart.sh or see docs/configuration.md.",
            )
        except (json.JSONDecodeError, OSError):
            return CheckResult(
                name="~/.hive/configuration.json",
                passed=False,
                message="File exists but invalid or unreadable",
                suggestion="Re-run quickstart.sh to regenerate.",
            )
    return CheckResult(
        name="~/.hive/configuration.json",
        passed=True,
        message="Not found (optional; quickstart.sh creates it)",
    )


def _check_exports_dir(project_root: Path) -> CheckResult:
    """Check exports/ directory exists (agents live here)."""
    path = project_root / "exports"
    if path.is_dir():
        return CheckResult(
            name="exports/",
            passed=True,
            message="Found (agent packages directory)",
        )
    return CheckResult(
        name="exports/",
        passed=True,
        message="Not found (create it or run agents from examples/templates)",
    )


def _check_network(skip: bool) -> CheckResult:
    """Test connectivity to LLM API (optional; can be skipped)."""
    if skip:
        return CheckResult(
            name="Network (LLM API)",
            passed=True,
            message="Skipped (use without --no-network to check)",
        )
    try:
        req = urllib.request.Request(
            NETWORK_CHECK_URL,
            method="HEAD",
            headers={"User-Agent": "Hive-Doctor/1.0"},
        )
        urllib.request.urlopen(req, timeout=NETWORK_CHECK_TIMEOUT_SEC)
        return CheckResult(
            name="Network (LLM API)",
            passed=True,
            message=f"Reachable {NETWORK_CHECK_URL}",
        )
    except OSError as e:
        return CheckResult(
            name="Network (LLM API)",
            passed=False,
            message=f"Could not reach {NETWORK_CHECK_URL}: {e!s}",
            suggestion="Check firewall/proxy or run with --no-network to skip this check.",
        )


def run_doctor_checks(
    project_root: Path | None = None,
    skip_network: bool = False,
) -> list[CheckResult]:
    """
    Run all environment diagnostics.

    Args:
        project_root: Repo root path. If None, inferred from this file's location.
        skip_network: If True, do not perform the network connectivity check.

    Returns:
        List of CheckResult in display order.
    """
    root = project_root or _project_root_from_runner()
    results: list[CheckResult] = []

    # Runtime & tooling
    results.append(_check_python_version(root))
    results.append(_check_python_version_file(root))
    results.append(_check_node_version(root))
    results.append(_check_uv(root))
    results.append(_check_ripgrep(root))

    # Project structure and dependencies
    results.append(_check_core_pyproject(root))
    results.append(_check_tools_pyproject(root))
    results.append(_check_core_venv(root))
    results.append(_check_tools_venv(root))

    # Configuration and env
    results.append(_check_llm_env_vars(root))
    results.append(_check_optional_env_vars(root))
    results.append(_check_hive_config(root))
    results.append(_check_exports_dir(root))

    # Network (optional)
    results.append(_check_network(skip_network))

    return results
