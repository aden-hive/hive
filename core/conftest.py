"""Keep every test run under core/ away from real Hive homes.

pytest loads this before any other conftest or test module, so it runs before
anything imports Hive or litellm. litellm's import calls ``load_dotenv()``,
which finds the repository's ``.env`` and the ``HIVE_HOME`` there, a real Hive
home; and Hive modules compute paths from ``HIVE_HOME`` when they are imported
(the credential key, the Sentinel secret, the runtime id, ...). The fixtures in
tests/conftest.py repoint only some of those, so a test once overwrote a real
home's credential key. With ``HIVE_HOME`` already set, ``load_dotenv()`` leaves
it alone and every import-time path lands in a throwaway directory.

The home the run started with is recorded first: live tests read their LLM
configuration and keys from it (``real_hive_home``), and nothing writes to it.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Resolved the way framework.config resolves HIVE_HOME: the variable the run
# started with, else ~/.hive. The repository .env's HIVE_HOME doesn't count,
# since load_dotenv() never gets to apply it now. pytest-xdist workers inherit
# HIVE_HOME after it's replaced below, so the first process passes the real
# home on to them in HIVE_TESTS_REAL_HIVE_HOME.
_REAL_HIVE_HOME = Path(os.environ.setdefault("HIVE_TESTS_REAL_HIVE_HOME", os.environ.get("HIVE_HOME") or str(Path.home() / ".hive"))).expanduser()

_IMPORT_TIME_HIVE_HOME = tempfile.mkdtemp(prefix="hive-tests-")
os.environ["HIVE_HOME"] = _IMPORT_TIME_HIVE_HOME
atexit.register(shutil.rmtree, _IMPORT_TIME_HIVE_HOME, ignore_errors=True)


@pytest.fixture(scope="session")
def real_hive_home() -> Path:
    """The Hive home this run started with, which live tests read config and keys from.

    Read it, never write to it. tests/live/conftest.py points only the LLM
    config and key lookups here; everything else stays in the sandbox.
    """
    return _REAL_HIVE_HOME
