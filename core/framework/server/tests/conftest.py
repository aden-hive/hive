"""Server tests get the same per-test isolation as ``core/tests``.

The repo ``.env`` points ``HIVE_HOME`` at a real Hive home, and
``framework.config`` resolves it at import. Without these fixtures the
server tests read and write that home (and dial the live browser bridge).
"""

from tests.conftest import (  # noqa: F401
    _isolate_hive_home_autouse,
    _no_real_browser_bridge,
    _session_hive_home_floor,
)
