"""Test fixtures."""

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[4]
for _p in ["examples/templates", "core"]:
    _path = str(_repo_root / _p)
    if _path not in sys.path:
        sys.path.insert(0, _path)

AGENT_PATH = str(Path(__file__).resolve().parents[1])


@pytest.fixture(scope="session")
def agent_module():
    """Import the agent package for structural validation."""
    import importlib

    return importlib.import_module(Path(AGENT_PATH).name)


@pytest.fixture(scope="session")
def runner_loaded():
    """Load the agent through AgentRunner (structural only, no LLM needed)."""
    from framework.runner.runner import AgentRunner

    return AgentRunner.load(AGENT_PATH)
