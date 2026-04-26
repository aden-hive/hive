"""App-scoped shared dependencies: Shared and SharedContext."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    AsyncExitStack,
)
from contextvars import ContextVar
from types import TracebackType
from typing import Any, ClassVar, TypeVar, cast, overload

from .functional import DependencyFactory, _FunctionalDependency
from .introspection import get_dependency_parameters

R = TypeVar("R")


class _Shared(_FunctionalDependency[R]):
    """App-scoped dependency resolved once and reused across all calls.

    Unlike _Depends (which resolves per-call), _Shared dependencies initialize
    once within a SharedContext and the same instance is provided to all
    subsequent resolutions.
    """

    async def __aenter__(self) -> R:
        resolved = SharedContext.resolved.get()

        if self.factory in resolved:
            return resolved[self.factory]

        arguments = await self._resolve_parameters()

        async with SharedContext.lock.get():
            if self.factory in resolved:  # pragma: no cover
                return resolved[self.factory]

            stack = SharedContext.stack.get()
            raw_value = self.factory(**arguments)
            resolved_value = await self._resolve_factory_value(stack, raw_value)

            resolved[self.factory] = resolved_value
            return resolved_value

    async def _resolve_parameters(self) -> dict[str, Any]:
        stack = SharedContext.stack.get()
        arguments: dict[str, Any] = {}
        parameters = get_dependency_parameters(self.factory)

        for parameter, dependency in parameters.items():
            arguments[parameter] = await stack.enter_async_context(dependency)

        return arguments


class SharedContext:
    """Manages app-scoped Shared dependency lifecycle.

    Use as an async context manager to establish a scope for Shared
    dependencies. All Shared factories resolved within this scope will
    be cached and reused. Context managers are cleaned up when the
    SharedContext exits.

    Example::

        async with SharedContext():
            async with resolved_dependencies(my_func) as dependencies:
                # Shared dependencies are resolved once and cached here
                ...
            async with resolved_dependencies(my_func) as dependencies:
                # Same Shared instances reused
                ...
        # Shared context managers are cleaned up here
    """

    resolved: ClassVar[ContextVar[dict[DependencyFactory[Any], Any]]] = ContextVar(
        "shared_resolved"
    )
    lock: ClassVar[ContextVar[asyncio.Lock]] = ContextVar("shared_lock")
    stack: ClassVar[ContextVar[AsyncExitStack]] = ContextVar("shared_stack")

    async def __aenter__(self) -> SharedContext:
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()

        self._resolved_token = SharedContext.resolved.set({})
        self._lock_token = SharedContext.lock.set(asyncio.Lock())
        self._stack_token = SharedContext.stack.set(self._stack)

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._stack.__aexit__(exc_type, exc_value, traceback)

        SharedContext.stack.reset(self._stack_token)
        SharedContext.lock.reset(self._lock_token)
        SharedContext.resolved.reset(self._resolved_token)


@overload
def Shared(factory: Callable[..., AbstractAsyncContextManager[R]]) -> R: ...
@overload
def Shared(factory: Callable[..., AbstractContextManager[R]]) -> R: ...
@overload
def Shared(factory: Callable[..., Awaitable[R]]) -> R: ...
@overload
def Shared(factory: Callable[..., R]) -> R: ...
def Shared(factory: DependencyFactory[R]) -> R:
    """Declare an app-scoped dependency shared across all calls.

    The factory initializes once within a ``SharedContext`` and the value is
    reused for all subsequent resolutions. Factories may be:

    - A sync function returning a value
    - An async function returning a value
    - A sync generator (context manager) yielding a value
    - An async generator (async context manager) yielding a value

    Context managers are cleaned up when the SharedContext exits.
    Identity is the factory function — multiple ``Shared(same_factory)``
    declarations anywhere resolve to the same cached value.
    """
    return cast(R, _Shared(factory))
