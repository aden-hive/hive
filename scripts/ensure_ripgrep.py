"""Check/install Hive's native search dependency. Run with uv run scripts/ensure_ripgrep.py --install."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Also works before editable workspace packages have been installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "src"))

from terminal_tools.common.ripgrep import ripgrep_status  # noqa: E402


def install_command() -> list[str] | None:
    if sys.platform == "win32":
        choices = [
            (
                "winget",
                [
                    "install",
                    "--exact",
                    "--id",
                    "BurntSushi.ripgrep.MSVC",
                    "--source",
                    "winget",
                    "--scope",
                    "user",
                    "--silent",
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                    "--disable-interactivity",
                ],
            ),
            ("scoop", ["install", "ripgrep"]),
            ("choco", ["install", "ripgrep", "-y", "--no-progress"]),
        ]
    else:
        choices = [
            ("brew", ["install", "ripgrep"]),
            ("apt-get", ["install", "-y", "ripgrep"]),
            ("apk", ["add", "ripgrep"]),
            ("dnf", ["install", "-y", "ripgrep"]),
            ("pacman", ["-S", "--needed", "--noconfirm", "ripgrep"]),
            ("zypper", ["--non-interactive", "install", "ripgrep"]),
        ]
    for program, args in choices:
        executable = shutil.which(program)
        if not executable:
            continue
        command = [executable, *args]
        if sys.platform != "win32" and program != "brew" and os.geteuid() != 0:
            sudo = shutil.which("sudo")
            if not sudo:
                continue
            command.insert(0, sudo)
        return command
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Install missing rg using the platform package manager")
    args = parser.parse_args(argv)
    status = ripgrep_status()
    if status["available"]:
        print(f"{status['version']} ({status['path']})")
        return 0
    if args.install and not os.environ.get("HIVE_RIPGREP_PATH"):
        command = install_command()
        if command:
            print("Installing ripgrep: " + " ".join(command), flush=True)
            try:
                result = subprocess.run(command, timeout=300, check=False)
                if result.returncode:
                    print(f"Package manager exited with code {result.returncode}.", file=sys.stderr)
            except (OSError, subprocess.TimeoutExpired) as exc:
                print(f"ripgrep installation failed: {exc}", file=sys.stderr)
            # Trust a fresh executable probe, not the installer's exit code or old PATH.
            status = ripgrep_status()
            if status["available"]:
                print(f"{status['version']} ({status['path']})")
                return 0
    print("ripgrep is unavailable. " + status["hint"], file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
