"""Keep every test run under core/ away from real Hive homes.

pytest loads this before any other conftest or test module, so it runs before
anything imports Hive or litellm. litellm's import calls ``load_dotenv()``,
which finds the repository's ``.env`` and the ``HIVE_HOME`` there, a real Hive
home; and Hive modules compute paths from ``HIVE_HOME`` when they are imported
(the credential key, the Sentinel secret, the runtime id, ...). The fixtures in
tests/conftest.py repoint only some of those, so a test once overwrote a real
home's credential key. With ``HIVE_HOME`` already set, ``load_dotenv()`` leaves
it alone and every import-time path lands in a throwaway directory.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

_IMPORT_TIME_HIVE_HOME = tempfile.mkdtemp(prefix="hive-tests-")
os.environ["HIVE_HOME"] = _IMPORT_TIME_HIVE_HOME
atexit.register(shutil.rmtree, _IMPORT_TIME_HIVE_HOME, ignore_errors=True)
