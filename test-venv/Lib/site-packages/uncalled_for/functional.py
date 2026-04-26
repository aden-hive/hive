"""Factory-based dependencies: Depends and its internals."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    AsyncExitStack,
)
from contextvars import ContextVar
from typing import Any, ClassVar, TypeVar, cast, overload

from .base import Dependency
from .introspection import get_dependency_parameters

R = TypeVar("R")

DependencyFactory = Callable[
    ..., R | Awaitable[R] | AbstractContextManager[R] | AbstractAsyncContextManager[R]
]


class _FunctionalDependency(Dependency[R]):
    """Base for dependencies that wrap a factory function."""

    factory: DependencyFactory[R]

    def __init__(self, factory: DependencyFactory[R]) -> None:
        self.factory = factory

    async def _resolve_factory_value(
        self,
        stack: AsyncExitStack,
        raw_value: (
            R
            | Awaitable[R]
            | AbstractContextManager[R]
            | AbstractAsyncContextManager[R]
        ),
    ) -> R:
        if isinstance(raw_value, AbstractAsyncContextManager):
            return await stack.enter_async_context(raw_value)  # pyright: ignore[reportUnknownArgumentType]
        elif isinstance(raw_value, AbstractContextManager):
            return stack.enter_context(raw_value)  # pyright: ignore[reportUnknownArgumentType]
        elif inspect.iscoroutine(raw_value) or isinstance(raw_value, Awaitable):
            return await cast(Awaitable[R], raw_value)
        else:
            return cast(R, raw_value)


class _Depends(_FunctionalDependency[R]):
    """Call-scoped dependency, resolved fresh for each call."""

    cache: ClassVar[ContextVar[dict[DependencyFactory[Any], Any]]] = ContextVar(
        "uncalled_for_cache"
    )
    stack: ClassVar[ContextVar[AsyncExitStack]] = ContextVar("uncalled_for_stack")

    async def _resolve_parameters(
        self,
        function: Callable[..., Any],
    ) -> dict[str, Any]:
        stack = self.stack.get()
        arguments: dict[str, Any] = {}
        parameters = get_dependency_parameters(function)

        for parameter, dependency in parameters.items():
            arguments[parameter] = await stack.enter_async_context(dependency)

        return arguments

    async def __aenter__(self) -> R:
        cache = self.cache.get()

        if self.factory in cache:
            return cache[self.factory]

        stack = self.stack.get()
        arguments = await self._resolve_parameters(self.factory)
        raw_value = self.factory(**arguments)
        resolved_value = await self._resolve_factory_value(stack, raw_value)

        cache[self.factory] = resolved_value
        return resolved_value


@overload
def Depends(factory: Callable[..., AbstractAsyncContextManager[R]]) -> R: ...
@overload
def Depends(factory: Callable[..., AbstractContextManager[R]]) -> R: ...
@overload
def Depends(factory: Callable[..., Awaitable[R]]) -> R: ...
@overload
def Depends(factory: Callable[..., R]) -> R: ...
def Depends(factory: DependencyFactory[R]) -> R:
    """Declare a dependency on a factory function.

    The factory is called once per resolution scope. It may be:

    - A sync function returning a value
    - An async function returning a value
    - A sync generator (context manager) yielding a value
    - An async generator (async context manager) yielding a value

    Context managers get proper enter/exit lifecycle management.
    """
    return cast(R, _Depends(factory))
