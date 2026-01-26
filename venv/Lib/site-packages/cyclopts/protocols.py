import inspect
from collections.abc import Callable
from typing import Any, Protocol


class Dispatcher(Protocol):
    def __call__(
        self, command: Callable[..., Any], bound: inspect.BoundArguments, ignored: dict[str, Any], /
    ) -> Any: ...
