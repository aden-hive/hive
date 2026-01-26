"""Shell detection utilities for completion generation.

This module provides functionality to detect the current shell type by inspecting
environment variables. This is useful for dynamically generating appropriate completion
scripts for different shell environments.
"""

import os
import subprocess
from pathlib import Path
from typing import Literal


class ShellDetectionError(Exception):
    """Raised when the shell type cannot be detected."""


def _extract_shell_name(shell_string: str) -> Literal["zsh", "bash", "fish"] | None:
    """Extract shell name from a string (path or process name).

    Parameters
    ----------
    shell_string : str
        String that may contain a shell name (e.g., "/bin/bash", "zsh", "-bash").

    Returns
    -------
    Literal["zsh", "bash", "fish"] | None
        The detected shell type, or None if not recognized.
    """
    shell_lower = shell_string.lower()
    if "zsh" in shell_lower:
        return "zsh"
    elif "bash" in shell_lower:
        return "bash"
    elif "fish" in shell_lower:
        return "fish"
    return None


def detect_shell() -> Literal["zsh", "bash", "fish"]:
    """Detect the current shell type using multiple detection methods.

    Returns
    -------
    Literal["zsh", "bash", "fish"]
        The detected shell type.

    Raises
    ------
    ShellDetectionError
        If the shell type cannot be determined from any detection method.

    Examples
    --------
    >>> shell = detect_shell()  # doctest: +SKIP
    >>> print(f"Detected shell: {shell}")  # doctest: +SKIP
    Detected shell: bash
    """
    if os.environ.get("ZSH_VERSION"):
        return "zsh"
    elif os.environ.get("BASH_VERSION"):
        return "bash"
    elif os.environ.get("FISH_VERSION"):
        return "fish"

    try:
        ppid = os.getppid()
        result = subprocess.run(
            ["ps", "-p", str(ppid), "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0 and result.stdout:
            parent_process = result.stdout.strip()
            shell = _extract_shell_name(parent_process)
            if shell:
                return shell
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass

    shell_path = os.environ.get("SHELL", "")
    if shell_path:
        shell_name = Path(shell_path).name
        shell = _extract_shell_name(shell_name)
        if shell:
            return shell

    raise ShellDetectionError("Unable to detect shell type.")
