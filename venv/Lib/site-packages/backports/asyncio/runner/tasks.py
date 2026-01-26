"""Minimal backported implementation of asyncio._PyTask from 3.11 compatible down to Python 3.8."""

import asyncio.tasks
import sys
from asyncio import AbstractEventLoop
from typing import Coroutine, TypeVar, Any, Optional

_T = TypeVar("_T")


# See https://github.com/python/cpython/blob/3.11/Lib/asyncio/tasks.py


class Task(asyncio.tasks._PyTask):  # type: ignore[name-defined, misc]
    """A coroutine wrapped in a Future."""

    def __init__(
        self,
        coro: Coroutine[Any, Any, _T],
        *,
        loop: Optional[AbstractEventLoop] = None,
        name: Optional[str] = None,
    ) -> None:
        self._num_cancels_requested = 0
        # https://github.com/python/cpython/blob/3.11/Modules/_asynciomodule.c#L2026
        # Backport Note: self._context is temporarily patched in Runner.run() instead.
        super().__init__(coro, loop=loop, name=name)

    def cancel(self, msg: Optional[str] = None) -> bool:
        """Request that this task cancel itself.

        This arranges for a CancelledError to be thrown into the
        wrapped coroutine on the next cycle through the event loop.
        The coroutine then has a chance to clean up or even deny
        the request using try/except/finally.

        Unlike Future.cancel, this does not guarantee that the
        task will be cancelled: the exception might be caught and
        acted upon, delaying cancellation of the task or preventing
        cancellation completely.  The task may also return a value or
        raise a different exception.

        Immediately after this method is called, Task.cancelled() will
        not return True (unless the task was already cancelled).  A
        task will be marked as cancelled when the wrapped coroutine
        terminates with a CancelledError exception (even if cancel()
        was not called).

        This also increases the task's count of cancellation requests.
        """
        self._log_traceback = False
        if self.done():
            return False
        self._num_cancels_requested += 1
        # These two lines are controversial.  See discussion starting at
        # https://github.com/python/cpython/pull/31394#issuecomment-1053545331
        # Also remember that this is duplicated in _asynciomodule.c.
        # if self._num_cancels_requested > 1:
        #     return False
        if self._fut_waiter is not None:
            if sys.version_info >= (3, 9):
                if self._fut_waiter.cancel(msg=msg):
                    # Leave self._fut_waiter; it may be a Task that
                    # catches and ignores the cancellation so we may have
                    # to cancel it again later.
                    return True
            else:
                if self._fut_waiter.cancel():
                    return True
        # It must be the case that self.__step is already scheduled.
        self._must_cancel = True
        if sys.version_info >= (3, 9):
            self._cancel_message = msg
        return True

    def cancelling(self) -> int:
        """Return the count of the task's cancellation requests.

        This count is incremented when .cancel() is called
        and may be decremented using .uncancel().
        """
        return self._num_cancels_requested

    def uncancel(self) -> int:
        """Decrement the task's count of cancellation requests.

        This should be called by the party that called `cancel()` on the task
        beforehand.

        Returns the remaining number of cancellation requests.
        """
        if self._num_cancels_requested > 0:
            self._num_cancels_requested -= 1
        return self._num_cancels_requested
