"""Locate and verify the external ripgrep dependency, including stale Windows PATHs."""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

_IS_WINDOWS = os.name == "nt"
_POSIX_PATHS = ("/usr/bin/rg", "/usr/local/bin/rg", "/opt/homebrew/bin/rg", "/home/linuxbrew/.linuxbrew/bin/rg")


def installation_hint() -> str:
    return (
        "Run quickstart again to install ripgrep, or set HIVE_RIPGREP_PATH to a working absolute executable path. "
        "Remove or correct that override if it is invalid. "
        + (
            "Windows: winget install --exact --id BurntSushi.ripgrep.MSVC --source winget --scope user"
            if _IS_WINDOWS
            else "macOS: brew install ripgrep; Debian/Ubuntu: sudo apt-get install ripgrep"
        )
    )


def _windows_registry_paths() -> list[str]:
    # GUI processes can inherit a PATH from before WinGet installed its alias.
    # Read current registry paths without replacing the caller's environment.
    import winreg

    paths = []
    for hive, key in (
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ):
        try:
            with winreg.OpenKey(hive, key) as opened:
                value, _ = winreg.QueryValueEx(opened, "Path")
            paths.extend(os.path.expandvars(entry.strip().strip('"')) for entry in value.split(";") if entry.strip())
        except OSError:
            continue
    return paths


def _candidate_paths() -> list[str]:
    override = os.environ.get("HIVE_RIPGREP_PATH")
    if override:
        # An explicit invalid setting must be corrected, not silently bypassed.
        return [override] if os.path.isabs(override) else []

    candidates = []
    found = shutil.which("rg")
    if found:
        candidates.append(found)
    user_dir = Path.home()
    if _IS_WINDOWS:
        directories = [Path(entry) for entry in _windows_registry_paths() if os.path.isabs(entry)]
        directories.extend([user_dir / ".cargo" / "bin", user_dir / "scoop" / "shims"])
        for variable, suffix in (
            ("CARGO_HOME", "bin"),
            ("SCOOP", "shims"),
            ("SCOOP_GLOBAL", "shims"),
            ("LOCALAPPDATA", "Microsoft/WinGet/Links"),
            ("ProgramFiles", "WinGet/Links"),
            ("ChocolateyInstall", "bin"),
        ):
            root = os.environ.get(variable)
            if root and os.path.isabs(root):
                directories.append(Path(root) / suffix)
        candidates.extend(str(directory / "rg.exe") for directory in directories)
    else:
        candidates.extend(_POSIX_PATHS)
        candidates.append(str(Path(os.environ.get("CARGO_HOME", str(user_dir / ".cargo"))) / "bin" / "rg"))
    return list(dict.fromkeys(candidates))


@lru_cache(maxsize=32)
def _probe_version(path: str, mtime_ns: int, size: int) -> str | None:
    # File metadata invalidates cached probes when a package manager replaces rg.
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            timeout=2,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = result.stdout.decode("utf-8", errors="replace").splitlines()
    if result.returncode == 0 and lines and lines[0].startswith("ripgrep "):
        return lines[0]
    return None


def _verified_candidates():
    for candidate in _candidate_paths():
        path = Path(candidate)
        try:
            if not path.is_file() or not os.access(path, os.X_OK):
                continue
            stat = path.stat()
            version = _probe_version(str(path.absolute()), stat.st_mtime_ns, stat.st_size)
        except OSError:
            continue
        if version:
            yield str(path.absolute()), version


def resolve_ripgrep() -> str | None:
    return next((path for path, _ in _verified_candidates()), None)


def ripgrep_status() -> dict:
    resolved = next(_verified_candidates(), None)
    if resolved:
        path, version = resolved
        return {"available": True, "path": path, "version": version}
    return {"available": False, "code": "ripgrep_required", "hint": installation_hint()}
