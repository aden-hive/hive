from typing import Any, Dict

import valkey

from ._connection import FakeRedisMixin
from .aioredis import FakeRedisMixin as FakeAsyncRedisMixin
from ._typing import Self


def _validate_server_type(args_dict: Dict[str, Any]) -> None:
    if "server_type" in args_dict and args_dict["server_type"] != "valkey":
        raise ValueError("server_type must be valkey")
    args_dict.setdefault("server_type", "valkey")
    args_dict.setdefault("client_class", valkey.Valkey)


class FakeValkey(FakeRedisMixin, valkey.Valkey):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _validate_server_type(kwargs)
        super().__init__(*args, **kwargs)

    @classmethod
    def from_url(cls, *args: Any, **kwargs: Any) -> Self:
        return super().from_url(*args, **kwargs)


class FakeStrictValkey(FakeRedisMixin, valkey.StrictValkey):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _validate_server_type(kwargs)
        super(FakeStrictValkey, self).__init__(*args, **kwargs)

    @classmethod
    def from_url(cls, *args: Any, **kwargs: Any) -> Self:
        return super().from_url(*args, **kwargs)


class FakeAsyncValkey(FakeAsyncRedisMixin, valkey.asyncio.Valkey):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("client_class", valkey.asyncio.Valkey)
        _validate_server_type(kwargs)
        super(FakeAsyncValkey, self).__init__(*args, **kwargs)

    @classmethod
    def from_url(cls, *args: Any, **kwargs: Any) -> Self:
        return super().from_url(*args, **kwargs)
