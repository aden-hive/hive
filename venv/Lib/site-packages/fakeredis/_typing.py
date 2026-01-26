import sys
from typing import Tuple, Union

import redis

if sys.version_info < (3, 8):
    from typing_extensions import Literal
else:
    from typing import Literal
if sys.version_info >= (3, 11):
    from typing import Self
    from asyncio import timeout as async_timeout
else:
    from async_timeout import timeout as async_timeout
    from typing_extensions import Self

try:
    from importlib import metadata
except ImportError:  # for Python < 3.8
    import importlib_metadata as metadata  # type: ignore

lib_version = metadata.version("fakeredis")
VersionType = Tuple[int, ...]
ServerType = Literal["redis", "dragonfly", "valkey"]

RaiseErrorTypes = (redis.ResponseError, redis.AuthenticationError)
ResponseErrorType = redis.ResponseError
try:
    import valkey

    RaiseErrorTypes = (redis.ResponseError, redis.AuthenticationError, valkey.ResponseError, valkey.AuthenticationError)
    ResponseErrorType = Union[redis.ResponseError, valkey.ResponseError]
except ImportError:
    pass

__all__ = [
    "Self",
    "async_timeout",
    "VersionType",
    "ServerType",
    "lib_version",
    "RaiseErrorTypes",
    "ResponseErrorType",
]
