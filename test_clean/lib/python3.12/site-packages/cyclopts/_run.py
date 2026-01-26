import inspect
import sys
from collections.abc import Callable, Coroutine
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, TypeVar, overload

from cyclopts._result_action import ResultAction

if sys.version_info < (3, 11):  # pragma: no cover
    from typing_extensions import assert_never
else:  # pragma: no cover
    from typing import assert_never

if TYPE_CHECKING:
    from cyclopts.core import App

V = TypeVar("V")

# App will be lazily imported to avoid circular imports
App = None  # type: ignore[assignment]


def _run_maybe_async_command(
    command: Callable,
    bound: inspect.BoundArguments | None = None,
    backend: Literal["asyncio", "trio"] = "asyncio",
):
    """Run a command, handling both sync and async cases.

    If the command is async, an async context will be created to run it.

    Parameters
    ----------
    command : Callable
        The command to execute.
    bound : inspect.BoundArguments | None
        Bound arguments for the command. If None, command is called with no arguments.
    backend : Literal["asyncio", "trio"]
        The async backend to use if the command is async.

    Returns
    -------
    return_value: Any
        The value the command function returns.
    """
    if not inspect.iscoroutinefunction(command):
        if bound is None:
            return command()
        else:
            return command(*bound.args, **bound.kwargs)

    if backend == "asyncio":
        import asyncio

        if bound is None:
            return asyncio.run(command())
        else:
            return asyncio.run(command(*bound.args, **bound.kwargs))
    elif backend == "trio":
        import trio

        if bound is None:
            return trio.run(command)
        else:
            return trio.run(partial(command, *bound.args, **bound.kwargs))
    else:  # pragma: no cover
        assert_never(backend)


@overload
def run(callable: Callable[..., Coroutine[None, None, V]], /, *, result_action: Literal["return_value"]) -> V: ...


@overload
def run(callable: Callable[..., V], /, *, result_action: Literal["return_value"]) -> V: ...


@overload
def run(
    callable: Callable[..., Coroutine[None, None, Any]], /, *, result_action: ResultAction | None = None
) -> Any: ...


@overload
def run(callable: Callable[..., Any], /, *, result_action: ResultAction | None = None) -> Any: ...


def run(callable, /, *, result_action: ResultAction | None = None):
    """Run the given callable as a CLI command.

    The callable may also be a coroutine function.
    This function is syntax sugar for very simple use cases, and is roughly equivalent to:

    .. code-block:: python

        from cyclopts import App

        app = App()
        app.default(callable)
        app()

    Parameters
    ----------
    callable
        The function to execute as a CLI command.
    result_action
        How to handle the command's return value. If not specified, uses the default
        ``"print_non_int_sys_exit"`` which calls :func:`sys.exit` with the appropriate code.
        Can be set to ``"return_value"`` to return the result directly for testing/embedding.

    Example usage:

    .. code-block:: python

        import cyclopts


        def main(name: str, age: int):
            print(f"Hello {name}, you are {age} years old.")


        cyclopts.run(main)
    """
    global App
    if App is None:
        from cyclopts.core import App as _App

        App = _App

    app = App(result_action=result_action)
    app.default(callable)
    return app()
