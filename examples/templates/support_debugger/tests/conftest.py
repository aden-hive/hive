"""Pytest configuration — ensures examples.templates is importable."""

import sys
from pathlib import Path

# Add hive/ to sys.path so that `examples.templates.support_debugger` resolves
_hive_root = Path(__file__).resolve().parents[4]  # …/hive
if str(_hive_root) not in sys.path:
    sys.path.insert(0, str(_hive_root))
