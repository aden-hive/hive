from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    paths = [
        root / "tools/src/aden_tools/tools/office_skills_pack",
        root / "tools/src/aden_tools/tools/excel_write_tool",
        root / "tools/src/aden_tools/tools/powerpoint_tool",
        root / "tools/src/aden_tools/tools/word_tool",
        root / "tools/src/aden_tools/tools/chart_tool",
        root / "tools/src/aden_tools/cli",
    ]
    cmd = [sys.executable, "-m", "pyright", *[str(p) for p in paths]]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
