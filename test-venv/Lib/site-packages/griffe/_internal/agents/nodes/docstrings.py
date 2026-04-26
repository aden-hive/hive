# This module contains utilities for extracting docstrings from nodes.

from __future__ import annotations

import ast


def get_docstring(
    node: ast.AST,
    *,
    strict: bool = False,
) -> tuple[str | None, int | None, int | None]:
    """Extract a docstring.

    Parameters:
        node: The node to extract the docstring from.
        strict: Whether to skip searching the body (functions).

    Returns:
        A tuple with the value and line numbers of the docstring.
    """
    # TODO: Possible optimization using a type map.
    if isinstance(node, ast.Expr):
        doc = node.value
    elif not strict and node.body and isinstance(node.body, list) and isinstance(node.body[0], ast.Expr):  # ty:ignore[unresolved-attribute]
        doc = node.body[0].value  # ty:ignore[unresolved-attribute]
    else:
        return None, None, None
    if isinstance(doc, ast.Constant) and isinstance(doc.value, str):
        return doc.value, doc.lineno, doc.end_lineno
    return None, None, None
