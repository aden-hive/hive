from _typeshed import Unused
from asyncio import AbstractEventLoop
from contextvars import Context
from typing import Any, TypeVar, Optional, Callable, Coroutine

from typing_extensions import Self, final

__all__ = ("Runner",)

_T = TypeVar("_T")

@final
class Runner:
    def __init__(
        self,
        *,
        debug: Optional[bool] = None,
        loop_factory: Optional[Callable[[], AbstractEventLoop]] = None,
    ) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type: Unused, exc_val: Unused, exc_tb: Unused) -> None: ...
    def close(self) -> None: ...
    def get_loop(self) -> AbstractEventLoop: ...
    def run(
        self, coro: Coroutine[Any, Any, _T], *, context: Optional[Context] = None
    ) -> _T: ...
