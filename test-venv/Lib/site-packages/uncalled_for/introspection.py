"""Signature and dependency parameter introspection."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from .base import Dependency

_signature_cache: dict[Callable[..., Any], inspect.Signature] = {}


def get_signature(function: Callable[..., Any]) -> inspect.Signature:
    """Get a cached signature for a function."""
    if function in _signature_cache:
        return _signature_cache[function]

    signature_attr = getattr(function, "__signature__", None)
    if isinstance(signature_attr, inspect.Signature):
        _signature_cache[function] = signature_attr
        return signature_attr

    signature = inspect.signature(function)
    _signature_cache[function] = signature
    return signature


_parameter_cache: dict[Callable[..., Any], dict[str, Dependency[Any]]] = {}


def get_dependency_parameters(
    function: Callable[..., Any],
) -> dict[str, Dependency[Any]]:
    """Find parameters whose defaults are Dependency instances."""
    if function in _parameter_cache:
        return _parameter_cache[function]

    dependencies: dict[str, Dependency[Any]] = {}
    signature = get_signature(function)

    for name, parameter in signature.parameters.items():
        if isinstance(parameter.default, Dependency):
            dependencies[name] = parameter.default  # pyright: ignore[reportUnknownMemberType]

    _parameter_cache[function] = dependencies
    return dependencies
