"""Annotation-based dependency extraction from ``Annotated`` type hints."""

from __future__ import annotations

from typing import Annotated, Any, get_args, get_origin, get_type_hints

from collections.abc import Callable

from .base import Dependency

_annotation_cache: dict[Callable[..., Any], dict[str, list[Dependency[Any]]]] = {}


def get_annotation_dependencies(
    function: Callable[..., Any],
) -> dict[str, list[Dependency[Any]]]:
    """Find ``Dependency`` instances in ``Annotated`` type-hint metadata."""
    if function in _annotation_cache:
        return _annotation_cache[function]

    result: dict[str, list[Dependency[Any]]] = {}
    try:
        hints = get_type_hints(function, include_extras=True)
    except Exception:
        _annotation_cache[function] = result
        return result

    for name, hint in hints.items():
        if name == "return":
            continue
        if get_origin(hint) is not Annotated:
            continue
        dependencies = [a for a in get_args(hint)[1:] if isinstance(a, Dependency)]
        if dependencies:
            result[name] = dependencies  # pyright: ignore[reportUnknownMemberType]

    _annotation_cache[function] = result
    return result
