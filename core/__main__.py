"""
Allow `python -m core` to work by forwarding to the Hive CLI.

Hive's core package imports `framework` as a top-level package, so we add
the `core/` directory to sys.path to make `framework/` importable.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    core_dir = Path(__file__).resolve().parent  # .../hive/core
    sys.path.insert(0, str(core_dir))

    # `framework` lives at core/framework
    from framework.cli import main as cli_main

    return int(cli_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())

