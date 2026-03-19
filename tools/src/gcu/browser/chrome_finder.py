"""
Detect system-installed Chrome or Edge browsers.

Searches platform-specific well-known paths to find a Chromium-based browser
executable. Used by chrome_launcher to avoid bundling Playwright's Chromium.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# Search order per platform: Chrome stable first, then Edge, then Chromium.
_MACOS_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

_LINUX_WHICH_NAMES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium-browser",
    "chromium",
    "microsoft-edge",
    "microsoft-edge-stable",
]

_WINDOWS_CANDIDATES = [
    r"Google\Chrome\Application\chrome.exe",
    r"Microsoft\Edge\Application\msedge.exe",
]


def find_chrome() -> str | None:
    """Return the absolute path to a system Chrome/Edge executable, or None.

    Check order:
    1. ``CHROME_PATH`` environment variable (explicit override)
    2. Platform-specific well-known install locations
    """
    # 1. Explicit override
    env_path = os.environ.get("CHROME_PATH")
    if env_path and _is_executable(env_path):
        return env_path

    # 2. Platform search
    if sys.platform == "darwin":
        return _find_macos()
    elif sys.platform == "win32":
        return _find_windows()
    else:
        return _find_linux()


def require_chrome() -> str:
    """Return a Chrome/Edge path or raise with an actionable error message."""
    path = find_chrome()
    if path is None:
        raise RuntimeError(
            "No Chrome or Edge browser found. GCU browser tools require a "
            "Chromium-based browser.\n\n"
            "Options:\n"
            "  1. Install Google Chrome: https://www.google.com/chrome/\n"
            "  2. Set the CHROME_PATH environment variable to your browser executable\n"
        )
    return path


def _is_executable(path: str) -> bool:
    """Check that path exists and is executable."""
    p = Path(path)
    return p.exists() and os.access(p, os.X_OK)


def _find_macos() -> str | None:
    for candidate in _MACOS_CANDIDATES:
        if _is_executable(candidate):
            return candidate
    return None


def _find_linux() -> str | None:
    for name in _LINUX_WHICH_NAMES:
        result = shutil.which(name)
        if result:
            return result
    return None


def _find_windows() -> str | None:
    program_dirs = []
    for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        val = os.environ.get(env_var)
        if val:
            program_dirs.append(val)

    for base_dir in program_dirs:
        for candidate in _WINDOWS_CANDIDATES:
            full_path = os.path.join(base_dir, candidate)
            if os.path.isfile(full_path):
                return full_path
    return None
