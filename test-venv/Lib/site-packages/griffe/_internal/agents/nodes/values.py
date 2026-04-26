# This module contains utilities for extracting attribute values.

from __future__ import annotations

import ast
from ast import unparse
from typing import TYPE_CHECKING

from griffe._internal.logger import logger

if TYPE_CHECKING:
    from pathlib import Path


def get_value(node: ast.AST | None) -> str | None:
    """Get the string representation of a node.

    Parameters:
        node: The node to represent.

    Returns:
        The representing code for the node.
    """
    if node is None:
        return None
    return unparse(node)


def safe_get_value(node: ast.AST | None, filepath: str | Path | None = None) -> str | None:
    """Safely (no exception) get the string representation of a node.

    Parameters:
        node: The node to represent.
        filepath: An optional filepath from where the node comes.

    Returns:
        The representing code for the node.
    """
    try:
        return get_value(node)
    except Exception as error:  # noqa: BLE001
        message = f"Failed to represent node {node}"
        if filepath:
            message += f" at {filepath}:{node.lineno}"  # ty:ignore[unresolved-attribute]
        message += f": {error}"
        logger.exception(message)
        return None
