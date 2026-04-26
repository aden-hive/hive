import os
from collections import defaultdict
from enum import IntEnum, unique
from io import BytesIO
from multiprocessing.pool import ThreadPool
from threading import Lock, RLock
from types import MappingProxyType
from typing import Any, Callable, Optional, Union

from .abstract import AbstractContext, AbstractOperation


fdsync = getattr(os, "fdatasync", os.fsync)
NATIVE_PREAD_PWRITE = hasattr(os, "pread") and hasattr(os, "pwrite")


@unique
class OpCode(IntEnum):
    READ = 0
    WRITE = 1
    FSYNC = 2
    FDSYNC = 3
    NOOP = -1


class Context(AbstractContext):
    """
    python aio context implementation
    """

    MAX_POOL_SIZE = 128

    def __init__(self, max_requests: int = 32, pool_size: int = 8):
        assert pool_size < self.MAX_POOL_SIZE

        self.__max_requests = max_requests
        self.pool = ThreadPool(pool_size)
        self._in_progress = 0
        self._closed = False
        self._closed_lock = Lock()

        if not NATIVE_PREAD_PWRITE:
            self._locks_cleaner = RLock()       # type: ignore
            self._locks = defaultdict(RLock)    # type: ignore

    @property
    def max_requests(self) -> int:
        return self.__max_requests

    def _execute(self, operation: "Operation"):
        handler = self._OP_MAP[operation.opcode]

        def on_error(exc):
            self._in_progress -= 1
            operation.exception = exc
            operation.written = 0
            operation.callback(None)

        def on_success(result):
            self._in_progress -= 1
            operation.written = result
            operation.callback(result)

        if self._in_progress > self.__max_requests:
            raise RuntimeError(
                "Maximum simultaneous requests have been reached",
            )

        self._in_progress += 1

        self.pool.apply_async(
            handler, args=(self, operation),
            callback=on_success,
            error_callback=on_error,
        )

    if NATIVE_PREAD_PWRITE:
        def __pread(self, fd, size, offset):
            return os.pread(fd, size, offset)

        def __pwrite(self, fd, bytes, offset):
            return os.pwrite(fd, bytes, offset)
    else:
        def __pread(self, fd, size, offset):
            with self._locks[fd]:
                os.lseek(fd, 0, os.SEEK_SET)
                os.lseek(fd, offset, os.SEEK_SET)
                return os.read(fd, size)

        def __pwrite(self, fd, bytes, offset):
            with self._locks[fd]:
                os.lseek(fd, 0, os.SEEK_SET)
                os.lseek(fd, offset, os.SEEK_SET)
                return os.write(fd, bytes)

    def _handle_read(self, operation: "Operation"):
        return operation.buffer.write(
            self.__pread(
                operation.fileno,
                operation.nbytes,
                operation.offset,
            ),
        )

    def _handle_write(self, operation: "Operation"):
        return self.__pwrite(
            operation.fileno, operation.buffer.getvalue(), operation.offset,
        )

    def _handle_fsync(self, operation: "Operation"):
        return os.fsync(operation.fileno)

    def _handle_fdsync(self, operation: "Operation"):
        return fdsync(operation.fileno)

    def _handle_noop(self, operation: "Operation"):
        return

    def submit(self, *aio_operations) -> int:
        operations = []

        for operation in aio_operations:
            if not isinstance(operation, Operation):
                raise ValueError("Invalid Operation %r", operation)

            operations.append(operation)

        count = 0
        for operation in operations:
            self._execute(operation)
            count += 1

        return count

    def cancel(self, *aio_operations) -> int:
        """
        Cancels multiple Operations. Returns

         Operation.cancel(aio_op1, aio_op2, aio_opN, ...) -> int

        (Always returns zero, this method exists for compatibility reasons)
        """
        return 0

    def close(self):
        if self._closed:
            return

        with self._closed_lock:
            self.pool.close()
            self._closed = True

    def __del__(self):
        if self.pool.close():
            self.close()

    _OP_MAP = MappingProxyType({
        OpCode.READ: _handle_read,
        OpCode.WRITE: _handle_write,
        OpCode.FSYNC: _handle_fsync,
        OpCode.FDSYNC: _handle_fdsync,
        OpCode.NOOP: _handle_noop,
    })


# noinspection PyPropertyDefinition
class Operation(AbstractOperation):
    """
    python aio operation implementation
    """
    def __init__(
        self,
        fd: int,
        nbytes: Optional[int],
        offset: Optional[int],
        opcode: OpCode,
        payload: Optional[bytes] = None,
        priority: Optional[int] = None,
    ):
        self.callback = None    # type: Optional[Callable[[int], Any]]
        self.buffer = BytesIO()

        if opcode == OpCode.WRITE and payload:
            self.buffer = BytesIO(payload)

        self.opcode = opcode
        self.__fileno = fd
        self.__offset = offset or 0
        self.__opcode = opcode
        self.__nbytes = nbytes or 0
        self.__priority = priority or 0
        self.exception = None
        self.written = 0

    @classmethod
    def read(
        cls, nbytes: int, fd: int, offset: int, priority=0,
    ) -> "Operation":
        """
        Creates a new instance of Operation on read mode.
        """
        return cls(fd, nbytes, offset, opcode=OpCode.READ, priority=priority)

    @classmethod
    def write(
        cls, payload_bytes: bytes, fd: int, offset: int, priority=0,
    ) -> "Operation":
        """
        Creates a new instance of AIOOperation on write mode.
        """
        return cls(
            fd,
            len(payload_bytes),
            offset,
            payload=payload_bytes,
            opcode=OpCode.WRITE,
            priority=priority,
        )

    @classmethod
    def fsync(cls, fd: int, priority=0) -> "Operation":

        """
        Creates a new instance of AIOOperation on fsync mode.
        """
        return cls(fd, None, None, opcode=OpCode.FSYNC, priority=priority)

    @classmethod
    def fdsync(cls, fd: int, priority=0) -> "Operation":

        """
        Creates a new instance of AIOOperation on fdsync mode.
        """
        return cls(fd, None, None, opcode=OpCode.FDSYNC, priority=priority)

    def get_value(self) -> Union[bytes, int]:
        """
        Method returns a bytes value of AIOOperation's result or None.
        """
        if self.exception:
            raise self.exception

        if self.opcode == OpCode.WRITE:
            return self.written

        if self.buffer is None:
            return

        return self.buffer.getvalue()

    @property
    def fileno(self) -> int:
        return self.__fileno

    @property
    def offset(self) -> int:
        return self.__offset

    @property
    def payload(self) -> Optional[memoryview]:
        return self.buffer.getbuffer()

    @property
    def nbytes(self) -> int:
        return self.__nbytes

    def set_callback(self, callback: Callable[[int], Any]) -> bool:
        self.callback = callback
        return True
