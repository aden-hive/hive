import abc
from typing import Any, Callable, Optional, Union


class AbstractContext(abc.ABC):
    @property
    def max_requests(self) -> int:
        raise NotImplementedError

    def submit(self, *aio_operations) -> int:
        raise NotImplementedError(aio_operations)

    def cancel(self, *aio_operations) -> int:
        raise NotImplementedError(aio_operations)


class AbstractOperation(abc.ABC):
    @classmethod
    @abc.abstractmethod
    def read(
        cls, nbytes: int, fd: int,
        offset: int, priority=0,
    ) -> "AbstractOperation":
        """
        Creates a new instance of AIOOperation on read mode.
        """
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def write(
        cls, payload_bytes: bytes,
        fd: int, offset: int, priority=0,
    ) -> "AbstractOperation":
        """
        Creates a new instance of AIOOperation on write mode.
        """
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def fsync(cls, fd: int, priority=0) -> "AbstractOperation":
        """
        Creates a new instance of AIOOperation on fsync mode.
        """
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def fdsync(cls, fd: int, priority=0) -> "AbstractOperation":

        """
        Creates a new instance of AIOOperation on fdsync mode.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_value(self) -> Union[bytes, int]:
        """
        Method returns a bytes value of AIOOperation's result or None.
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def fileno(self) -> int:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def offset(self) -> int:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def payload(self) -> Optional[Union[bytes, memoryview]]:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def nbytes(self) -> int:
        raise NotImplementedError

    @abc.abstractmethod
    def set_callback(self, callback: Callable[[int], Any]) -> bool:
        raise NotImplementedError
