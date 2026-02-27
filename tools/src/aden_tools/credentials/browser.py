"""
Browser utilities for OAuth2 flows.

Opens URLs in the user's default browser for authorization flows.
Supports macOS, Linux, and Windows.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import webbrowser
from urllib.parse import urlparse


def _is_safe_browser_url(url: str) -> bool:
    """Return True only for http/https URLs with a hostname."""
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _run_browser_command(command: list[str]) -> None:
    """Execute browser command using a controlled subprocess call."""
    subprocess.run(command, check=True, capture_output=True)  # noqa: S603


def open_browser(url: str) -> tuple[bool, str]:
    """
    Open a URL in the user's default browser.

    Uses platform-specific commands for reliability:
    - macOS: `open` command
    - Linux: `xdg-open` command (falls back to webbrowser module)
    - Windows: webbrowser module

    Args:
        url: The URL to open

    Returns:
        Tuple of (success, message)

    Example:
        >>> success, msg = open_browser("https://hive.adenhq.com/connect/hubspot")
        >>> if success:
        ...     print("Browser opened!")
    """
    system = platform.system()

    if not _is_safe_browser_url(url):
        return False, "Invalid URL: only absolute http/https URLs are allowed"

    try:
        if system == "Darwin":  # macOS
            open_path = shutil.which("open")
            if not open_path:
                return False, "Could not open browser (open command not found)"
            _run_browser_command([open_path, url])
            return True, "Opened in browser"

        elif system == "Linux":
            # Try xdg-open first (most Linux distros)
            try:
                xdg_open_path = shutil.which("xdg-open")
                if xdg_open_path:
                    _run_browser_command([xdg_open_path, url])
                    return True, "Opened in browser"
            except subprocess.CalledProcessError:
                pass

            if not shutil.which("xdg-open"):
                # xdg-open not available, fall back to webbrowser
                if webbrowser.open(url):
                    return True, "Opened in browser"
                return False, "Could not open browser (xdg-open not found)"

            # xdg-open exists but failed, fall back to webbrowser
            if webbrowser.open(url):
                return True, "Opened in browser"
            return False, "Could not open browser"

        elif system == "Windows":
            if webbrowser.open(url):
                return True, "Opened in browser"
            return False, "Could not open browser"

        else:
            # Unknown system - try webbrowser module
            if webbrowser.open(url):
                return True, "Opened in browser"
            return False, f"Could not open browser on {system}"

    except subprocess.CalledProcessError as e:
        return False, f"Failed to open browser: {e}"
    except Exception as e:
        return False, f"Failed to open browser: {e}"


def get_aden_auth_url(provider_name: str, base_url: str = "https://hive.adenhq.com") -> str:
    """
    Get the Aden authorization URL for a provider.

    Args:
        provider_name: Provider name (e.g., 'hubspot')
        base_url: Aden server base URL

    Returns:
        Full authorization URL
    """
    return f"{base_url}/connect/{provider_name}"


def get_aden_setup_url(base_url: str = "https://hive.adenhq.com") -> str:
    """
    Get the Aden setup URL for creating an API key.

    Args:
        base_url: Aden server base URL

    Returns:
        Setup URL for getting an Aden API key
    """
    return f"{base_url}/setup"
