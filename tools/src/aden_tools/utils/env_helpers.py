"""
Environment variable helpers for Aden Tools.
"""
from __future__ import annotations

import os
from typing import Optional


def get_env_var(
    name: str,
    default: Optional[str] = None,
    required: bool = False,
) -> Optional[str]:
    """
    Get an environment variable with optional default and required validation.

    Args:
        name: Name of the environment variable
        default: Default value if not set
        required: If True, raises ValueError when not set and no default

    Returns:
        The environment variable value or default

    Raises:
        ValueError: If required=True and variable is not set with no default
    """
    value = os.environ.get(name, default)
    if required and value is None:
        raise ValueError(
            f"Required environment variable '{name}' is not set. "
            f"Please set it before using this tool."
        )
    return value
