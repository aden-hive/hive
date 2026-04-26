"""Dependency resolution: resolving, wrapping, and failure handling."""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from functools import lru_cache
from typing import Any

from .annotations import get_annotation_dependencies
from .functional import _Depends
from .introspection import get_dependency_parameters, get_signature


class FailedDependency:
    """Placeholder for a dependency that raised during resolution."""

    def __init__(self, parameter: str, error: Exception) -> None:
        self.parameter = parameter
        self.error = error


@asynccontextmanager
async def resolved_dependencies(
    function: Callable[..., Any],
    kwargs: dict[str, Any] | None = None,
) -> AsyncGenerator[dict[str, Any]]:
    """Resolve all dependencies declared on a function's signature.

    Yields a dict mapping parameter names to resolved values. Dependencies
    are entered as async context managers and cleaned up when the context
    exits.

    Parameters already present in *kwargs* are passed through without
    resolution, allowing callers to override specific dependencies.
    """
    provided = kwargs or {}
    cache_token = _Depends.cache.set({})

    try:
        async with AsyncExitStack() as stack:
            stack_token = _Depends.stack.set(stack)
            try:
                arguments: dict[str, Any] = {}
                parameters = get_dependency_parameters(function)

                for parameter, dependency in parameters.items():
                    if parameter in provided:
                        arguments[parameter] = provided[parameter]
                        continue

                    try:
                        arguments[parameter] = await stack.enter_async_context(
                            dependency
                        )
                    except Exception as error:
                        arguments[parameter] = FailedDependency(parameter, error)

                annotation_dependencies = get_annotation_dependencies(function)
                for parameter_name, dependencies in annotation_dependencies.items():
                    value = provided.get(parameter_name, arguments.get(parameter_name))
                    for dependency in dependencies:
                        bound = dependency.bind_to_parameter(parameter_name, value)
                        await stack.enter_async_context(bound)

                yield arguments
            finally:
                _Depends.stack.reset(stack_token)
    finally:
        _Depends.cache.reset(cache_token)


@lru_cache(maxsize=5_000)
def without_dependencies(function: Callable[..., Any]) -> Callable[..., Any]:
    """Produce a wrapper whose signature hides dependency parameters.

    If *function* has no ``Dependency`` defaults, it is returned unchanged.
    Otherwise an async wrapper is returned that resolves dependencies
    automatically and forwards user-supplied keyword arguments.
    """
    dependency_names = set(get_dependency_parameters(function))
    annotation_dependencies = get_annotation_dependencies(function)
    if not dependency_names and not annotation_dependencies:
        return function

    original_signature = get_signature(function)
    filtered_parameters = [
        p
        for name, p in original_signature.parameters.items()
        if name not in dependency_names
    ]
    new_signature = original_signature.replace(
        parameters=filtered_parameters, return_annotation=inspect.Parameter.empty
    )

    is_async = inspect.iscoroutinefunction(function)

    async def wrapper(**kwargs: Any) -> Any:
        async with resolved_dependencies(function, kwargs) as resolved:
            all_kwargs = {**resolved, **kwargs}
            if is_async:
                return await function(**all_kwargs)
            return function(**all_kwargs)

    wrapper.__name__ = function.__name__
    wrapper.__doc__ = function.__doc__
    wrapper.__signature__ = new_signature  # type: ignore[attr-defined]
    wrapper.__annotations__ = {
        k: v
        for k, v in function.__annotations__.items()
        if k not in dependency_names and k != "return"
    }

    return wrapper
