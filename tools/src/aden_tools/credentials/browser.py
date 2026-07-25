"""
Browser utilities for OAuth2 flows.

Opens URLs in the user's default browser for authorization flows.
Supports macOS, Linux, and Windows.
"""

from __future__ import annotations

import platform
import subprocess
import urllib.parse
import webbrowser


def _is_safe_url(url: str) -> bool:
    """Validate URL is safe (http/https scheme only, no shell metacharacters)."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        # Check for shell metacharacters
        dangerous_chars = set(";&|`$(){}[]!#~")
        if any(c in url for c in dangerous_chars):
            return False
        return True
    except Exception:
        return False


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
    # Validate URL to prevent command injection
    if not _is_safe_url(url):
        return False, f"Invalid or unsafe URL: {url!r}"

    system = platform.system()

    try:
        if system == "Darwin":  # macOS
            subprocess.run(
                ["open", url],
                check=True,
                capture_output=True,
                encoding="utf-8",
            )
            return True, "Opened in browser"

        elif system == "Linux":
            # Try xdg-open first (most Linux distros)
            try:
                subprocess.run(
                    ["xdg-open", url],
                    check=True,
                    capture_output=True,
                    encoding="utf-8",
                )
                return True, "Opened in browser"
            except FileNotFoundError:
                # xdg-open not available, fall back to webbrowser
                if webbrowser.open(url):
                    return True, "Opened in browser"
                return False, "Could not open browser (xdg-open not found)"

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
