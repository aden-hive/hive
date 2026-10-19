"""Check a pip-installed Hive works as the whole app, with no checkout of this repository.

Run it with the Python of a virtualenv that installed ``aden-hive[tools]`` from built wheels,
from a directory outside the repository (CI's Package job does this):

    python -I scripts/check_installed_package.py

It checks that every ``hive`` export resolves, that every built-in tool group loads, that the
dashboard comes from the installed package, and that ``hive serve`` serves it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PORT = 18787


def main() -> None:
    import hive

    missing = [name for name in hive._EXPORTS if getattr(hive, name, None) is None]
    assert not missing, f"hive exports that do not resolve: {missing}"
    print(f"hive {hive.__version__}: {len(hive._EXPORTS)} exports resolve")

    from framework.tools.harness_tools import HARNESS_GROUPS, build_harness_group

    counts = {group: len(build_harness_group(group)) for group in HARNESS_GROUPS}
    print(f"tool groups: {counts}")
    assert all(counts.values()), f"empty tool groups: {[g for g, n in counts.items() if not n]}"

    from framework.server.app import frontend_dist_dir

    dist = frontend_dist_dir()
    assert dist is not None, "no dashboard in the installed package"
    assert "site-packages" in dist.parts, f"dashboard served from {dist}, not the installed package"
    print(f"dashboard: {dist}")

    hive_cli = shutil.which("hive", path=str(Path(sys.executable).parent))
    assert hive_cli, "the hive command is not installed next to this Python"
    # On Windows a child of the server can still hold its log open when the directory goes.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as home:
        env = {**os.environ, "HIVE_HOME": home}
        server = subprocess.Popen([hive_cli, "serve", "--port", str(PORT)], env=env, cwd=home)
        try:
            page = _get_when_up(f"http://127.0.0.1:{PORT}/")
        finally:
            server.terminate()
            server.wait(timeout=30)
    assert "<title>" in page, "hive serve did not serve the dashboard"
    print("hive serve: dashboard served")


def _get_when_up(url: str, *, wait: float = 90.0) -> str:
    deadline = time.monotonic() + wait
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return resp.read().decode("utf-8", "replace")
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


if __name__ == "__main__":
    main()
