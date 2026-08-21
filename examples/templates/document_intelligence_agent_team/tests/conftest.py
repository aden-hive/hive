"""Test fixtures for Document Intelligence Agent Team."""

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
def agent(agent_module):
    """Get the default agent instance."""
    return agent_module.default_agent
