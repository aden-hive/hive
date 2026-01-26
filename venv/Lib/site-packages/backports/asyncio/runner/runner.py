"""Backported implementation of asyncio.Runner from 3.11 compatible down to Python 3.8."""

import asyncio
import asyncio.tasks
import contextvars
import enum
import functools
import signal
import sys
import threading
from asyncio import coroutines, events, tasks, exceptions, AbstractEventLoop
from contextvars import Context
from types import TracebackType, FrameType
from typing import (
    Callable,
    Coroutine,
    TypeVar,
    Any,
    Optional,
    Type,
    final,
    TYPE_CHECKING,
)

from ._int_to_enum import _orig_int_to_enum, _patched_int_to_enum
from ._patch import _patch_object
from .tasks import Task

# See https://github.com/python/cpython/blob/3.11/Lib/asyncio/runners.py

if TYPE_CHECKING:  # pragma: no cover
    from signal import _HANDLER

__all__ = ("Runner",)

_T = TypeVar("_T")


class _State(enum.Enum):
    CREATED = "created"
    INITIALIZED = "initialized"
    CLOSED = "closed"


@final
class Runner:
    """A context manager that controls event loop life cycle.

    The context manager always creates a new event loop,
    allows to run async functions inside it,
    and properly finalizes the loop at the context manager exit.

    If debug is True, the event loop will be run in debug mode.
    If loop_factory is passed, it is used for new event loop creation.

    asyncio.run(main(), debug=True)

    is a shortcut for

    with Runner(debug=True) as runner:
        runner.run(main())

    The run() method can be called multiple times within the runner's context.

    This can be useful for interactive console (e.g. IPython),
    unittest runners, console tools, -- everywhere when async code
    is called from existing sync framework and where the preferred single
    asyncio.run() call doesn't work.

    """

    # Note: the class is final, it is not intended for inheritance.

    def __init__(
        self,
        *,
        debug: Optional[bool] = None,
        loop_factory: Optional[Callable[[], AbstractEventLoop]] = None,
    ):
        self._state = _State.CREATED
        self._debug = debug
        self._loop_factory = loop_factory
        self._loop: Optional[AbstractEventLoop] = None
        self._context = None
        self._interrupt_count = 0
        self._set_event_loop = False

    def __enter__(self) -> "Runner":
        self._lazy_init()
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException],
        exc_val: BaseException,
        exc_tb: TracebackType,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Shutdown and close event loop."""
        if self._state is not _State.INITIALIZED:
            return
        try:
            # TYPING: self._loop should not be None
            loop: AbstractEventLoop = self._loop  # type: ignore[assignment]
            _cancel_all_tasks(loop)
            loop.run_until_complete(loop.shutdown_asyncgens())
            # Backport Patch
            if sys.version_info >= (3, 9):
                loop.run_until_complete(loop.shutdown_default_executor())
            else:
                loop.run_until_complete(_shutdown_default_executor(loop))
        finally:
            if self._set_event_loop:
                events.set_event_loop(None)
            loop.close()
            self._loop = None
            self._state = _State.CLOSED
            # See https://github.com/python/cpython/pull/113444
            # Reverts signal._int_to_enum patch
            signal._int_to_enum = _orig_int_to_enum  # type: ignore[attr-defined]

    def get_loop(self) -> AbstractEventLoop:
        """Return embedded event loop."""
        self._lazy_init()
        # TYPING: self._loop should not be None
        return self._loop  # type: ignore[return-value]

    def run(
        self, coro: Coroutine[Any, Any, _T], *, context: Optional[Context] = None
    ) -> _T:
        """Run a coroutine inside the embedded event loop."""
        if not coroutines.iscoroutine(coro):
            raise ValueError("a coroutine was expected, got {!r}".format(coro))

        if events._get_running_loop() is not None:
            # fail fast with short traceback
            raise RuntimeError(
                "Runner.run() cannot be called from a running event loop"
            )

        self._lazy_init()

        if context is None:
            context = self._context

        # Backport Patch: <= 3.11 does not have create_task with context parameter
        # Reader note: context.run will not work here as it does not match how asyncio.Runner retains context
        with _patch_object(asyncio.tasks, asyncio.tasks.Task.__name__, Task):
            with _patch_object(
                contextvars, contextvars.copy_context.__name__, lambda: context
            ):
                task = self._loop.create_task(coro)  # type: ignore[union-attr]

        if (
            threading.current_thread() is threading.main_thread()
            and signal.getsignal(signal.SIGINT) is signal.default_int_handler
        ):
            sigint_handler: "_HANDLER" = functools.partial(
                self._on_sigint, main_task=task
            )
            try:
                signal.signal(signal.SIGINT, sigint_handler)
            except ValueError:
                # `signal.signal` may throw if `threading.main_thread` does
                # not support signals (e.g. embedded interpreter with signals
                # not registered - see gh-91880)
                sigint_handler = None
        else:
            sigint_handler = None

        self._interrupt_count = 0
        try:
            return self._loop.run_until_complete(task)  # type: ignore[union-attr, no-any-return]
        except exceptions.CancelledError:
            if self._interrupt_count > 0:
                uncancel = getattr(task, "uncancel", None)
                if uncancel is not None and uncancel() == 0:
                    raise KeyboardInterrupt()
            raise  # CancelledError
        finally:
            if (
                sigint_handler is not None
                and signal.getsignal(signal.SIGINT) is sigint_handler
            ):
                signal.signal(signal.SIGINT, signal.default_int_handler)

    def _lazy_init(self) -> None:
        if self._state is _State.CLOSED:
            raise RuntimeError("Runner is closed")
        if self._state is _State.INITIALIZED:
            return
        # See https://github.com/python/cpython/pull/113444
        # Patches signal._int_to_enum temporarily
        signal._int_to_enum = _patched_int_to_enum  # type: ignore[attr-defined]
        # Continue original implementation
        if self._loop_factory is None:
            self._loop = events.new_event_loop()
            if not self._set_event_loop:
                # Call set_event_loop only once to avoid calling
                # attach_loop multiple times on child watchers
                events.set_event_loop(self._loop)
                self._set_event_loop = True
        else:
            self._loop = self._loop_factory()
        if self._debug is not None:
            self._loop.set_debug(self._debug)
        self._context = contextvars.copy_context()  # type: ignore[assignment]
        self._state = _State.INITIALIZED

    def _on_sigint(
        self, signum: int, frame: Optional[FrameType], main_task: asyncio.Task
    ) -> None:
        # TYPING: self._loop should not be None
        self._interrupt_count += 1
        if self._interrupt_count == 1 and not main_task.done():
            main_task.cancel()
            # wakeup loop if it is blocked by select() with long timeout
            self._loop.call_soon_threadsafe(lambda: None)  # type: ignore[union-attr]
            return
        raise KeyboardInterrupt()


# See https://github.com/python/cpython/blob/3.11/Lib/asyncio/runners.py
def _cancel_all_tasks(loop: AbstractEventLoop) -> None:
    to_cancel = tasks.all_tasks(loop)
    if not to_cancel:
        return

    for task in to_cancel:
        task.cancel()

    loop.run_until_complete(tasks.gather(*to_cancel, return_exceptions=True))

    for task in to_cancel:
        if task.cancelled():
            continue
        if task.exception() is not None:
            loop.call_exception_handler(
                {
                    "message": "unhandled exception during asyncio.run() shutdown",
                    "exception": task.exception(),
                    "task": task,
                }
            )


# See https://github.com/python/cpython/blob/3.11/Lib/asyncio/base_events.py


async def _shutdown_default_executor(loop: AbstractEventLoop) -> None:
    """Schedule the shutdown of the default executor."""
    # TYPING: Both _executor_shutdown_called and _default_executor are expected private properties of BaseEventLoop
    loop._executor_shutdown_called = True  # type: ignore[attr-defined]
    if loop._default_executor is None:  # type: ignore[attr-defined]
        return
    future = loop.create_future()
    # Backport modified to include send loop to _do_shutdown
    thread = threading.Thread(target=_do_shutdown, args=(loop, future))
    thread.start()
    try:
        await future
    finally:
        thread.join()


def _do_shutdown(loop: AbstractEventLoop, future: asyncio.futures.Future) -> None:
    try:
        loop._default_executor.shutdown(wait=True)  # type: ignore[attr-defined]
        if not loop.is_closed():
            loop.call_soon_threadsafe(future.set_result, None)
    except Exception as ex:
        if not loop.is_closed():
            loop.call_soon_threadsafe(future.set_exception, ex)
