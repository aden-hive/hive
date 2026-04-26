"""Dependency declaration validation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from .annotations import get_annotation_dependencies
from .base import Dependency
from .introspection import get_dependency_parameters


def validate_dependencies(function: Callable[..., Any]) -> None:
    """Check that a function's dependency declarations are valid.

    Raises ``ValueError`` if multiple dependencies with ``single=True``
    share the same type or base class. The check spans both default-parameter
    dependencies and ``Annotated`` annotation dependencies — ``single`` means
    at most one instance of that type across the entire function.

    Concrete-type duplicates are checked first so the error message names
    the exact type (e.g. "Retry") rather than an abstract ancestor
    (e.g. "FailureHandler").
    """
    default_dependencies: list[Dependency[Any]] = list(
        get_dependency_parameters(function).values()
    )

    annotation_dependencies_by_parameter = get_annotation_dependencies(function)
    annotation_dependencies: list[Dependency[Any]] = [
        dependency
        for parameter_dependencies in annotation_dependencies_by_parameter.values()
        for dependency in parameter_dependencies  # pyright: ignore[reportUnknownVariableType]
    ]

    all_dependencies = default_dependencies + annotation_dependencies

    # Check for duplicate concrete types.  This catches e.g. two Retry(...)
    # and reports "Only one Retry dependency is allowed".
    counts: Counter[type[Dependency[Any]]] = Counter(
        type(dependency)
        for dependency in all_dependencies  # pyright: ignore[reportUnknownArgumentType]
    )
    for dependency_type, count in counts.items():
        if getattr(dependency_type, "single", False) and count > 1:  # pyright: ignore[reportUnknownArgumentType]
            raise ValueError(
                f"Only one {dependency_type.__name__} dependency is allowed"  # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType]
            )

    # Check for conflicts between *different* subclasses that share a single
    # base (e.g. Timeout + CustomRuntime both under Runtime).
    single_bases: set[type[Dependency[Any]]] = set()
    for dependency in all_dependencies:
        for cls in type(dependency).__mro__:
            if (
                issubclass(cls, Dependency)
                and cls is not Dependency
                and getattr(cls, "single", False)  # pyright: ignore[reportUnknownArgumentType]
            ):
                single_bases.add(cls)  # pyright: ignore[reportUnknownArgumentType]

    for base_class in single_bases:
        instances = [
            dependency
            for dependency in all_dependencies
            if isinstance(dependency, base_class)
        ]
        if len(instances) > 1:
            types = ", ".join(type(instance).__name__ for instance in instances)
            raise ValueError(
                f"Only one {base_class.__name__} dependency is allowed, "
                f"but found: {types}"
            )
