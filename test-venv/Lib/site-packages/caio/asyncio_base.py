import abc
import asyncio
import typing
from functools import partial

from . import abstract


ContextType = typing.Type[abstract.AbstractContext]
OperationType = typing.Type[abstract.AbstractOperation]


class AsyncioContextBase(abc.ABC):
    MAX_REQUESTS_DEFAULT = 512
    CONTEXT_CLASS = None    # type: ContextType
    OPERATION_CLASS = None  # type: OperationType

    def __init__(self, max_requests=None, loop=None, **kwargs):
        max_requests = max_requests or self.MAX_REQUESTS_DEFAULT
        self.loop = loop or asyncio.get_event_loop()
        self.semaphore = asyncio.BoundedSemaphore(max_requests)
        self.context = self._create_context(max_requests, **kwargs)

    def _create_context(self, max_requests, **kwargs):
        return self.CONTEXT_CLASS(max_requests=max_requests, **kwargs)

    def _destroy_context(self):
        return

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        self._destroy_context()

    async def submit(self, op):
        if not isinstance(op, self.OPERATION_CLASS):
            raise ValueError("Operation object expected")

        future = self.loop.create_future()
        op.set_callback(partial(self._on_done, future))

        async with self.semaphore:
            if self.context.submit(op) != 1:
                raise IOError("Operation was not submitted")

            try:
                await future
            except asyncio.CancelledError:
                try:
                    self.context.cancel(op)
                except ValueError:
                    pass
                raise
            return op.get_value()

    def _on_done(self, future, result):
        """
        In general case impossible predict current thread and the thread
        of event loop. So have to use `call_soon_threadsave` the result setter.
        """

        if future.done():
            return

        self.loop.call_soon_threadsafe(
            lambda: future.done() or future.set_result(True),
        )

    def read(
        self, nbytes: int, fd: int,
        offset: int, priority: int = 0,
    ) -> typing.Awaitable[bytes]:
        return self.submit(
            self.OPERATION_CLASS.read(nbytes, fd, offset, priority),
        )

    def write(
        self, payload: bytes, fd: int,
        offset: int, priority: int = 0,
    ) -> typing.Awaitable[int]:
        return self.submit(
            self.OPERATION_CLASS.write(payload, fd, offset, priority),
        )

    def fsync(self, fd: int) -> typing.Awaitable:
        return self.submit(self.OPERATION_CLASS.fsync(fd))

    def fdsync(self, fd: int) -> typing.Awaitable:
        return self.submit(self.OPERATION_CLASS.fdsync(fd))
