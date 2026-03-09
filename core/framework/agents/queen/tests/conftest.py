"""Test fixtures for Hive Coder agent."""

import sys
from pathlib import Path

import pytest
import pytest_asyncio

_repo_root = Path(__file__).resolve().parents[3]
for _p in ["exports", "core"]:
    _path = str(_repo_root / _p)
    if _path not in sys.path:
        sys.path.insert(0, _path)

AGENT_PATH = str(Path(__file__).resolve().parents[1])


@pytest.fixture(scope="session")
def mock_mode():
    return True


@pytest_asyncio.fixture(scope="session")
async def runner(tmp_path_factory, mock_mode):
    from framework.runner.runner import AgentRunner

    storage = tmp_path_factory.mktemp("agent_storage")
    r = AgentRunner.load(AGENT_PATH, mock_mode=mock_mode, storage_path=storage)
    r._setup()
    yield r
    await r.cleanup_async()
