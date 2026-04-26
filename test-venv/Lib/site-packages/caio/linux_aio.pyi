from typing import Union, Optional, Callable, Any

from .abstract import AbstractContext, AbstractOperation


# noinspection PyPropertyDefinition
class Context(AbstractContext):
    def __init__(self, max_requests: int = 32): ...


# noinspection PyPropertyDefinition
class Operation(AbstractOperation):
    @classmethod
    def read(
        cls, nbytes: int, fd: int, offset: int, priority=0
    ) -> "AbstractOperation": ...

    @classmethod
    def write(
        cls, payload_bytes: bytes,
        fd: int, offset: int, priority=0,
    ) -> "AbstractOperation": ...

    @classmethod
    def fsync(cls, fd: int, priority=0) -> "AbstractOperation": ...

    @classmethod
    def fdsync(cls, fd: int, priority=0) -> "AbstractOperation": ...

    def get_value(self) -> Union[bytes, int]: ...

    @property
    def fileno(self) -> int: ...

    @property
    def offset(self) -> int: ...

    @property
    def payload(self) -> Optional[Union[bytes, memoryview]]: ...

    @property
    def nbytes(self) -> int: ...

    def set_callback(self, callback: Callable[[int], Any]) -> bool: ...

