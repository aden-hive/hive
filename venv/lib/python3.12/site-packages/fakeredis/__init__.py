from . import _typing
from ._connection import (
    FakeRedis,
    FakeStrictRedis,
    FakeConnection,
)
from ._server import FakeServer
from .aioredis import (
    FakeRedis as FakeAsyncRedis,
    FakeConnection as FakeAsyncConnection,
)
from ._tcp_server import TcpFakeServer


__version__ = _typing.lib_version
__author__ = "Daniel Moran"
__maintainer__ = "Daniel Moran"
__email__ = "daniel@moransoftware.ca"
__license__ = "BSD-3-Clause"
__url__ = "https://github.com/cunla/fakeredis-py"
__bugtrack_url__ = "https://github.com/cunla/fakeredis-py/issues"

__all__ = [
    "FakeServer",
    "FakeRedis",
    "FakeStrictRedis",
    "FakeConnection",
    "FakeAsyncRedis",
    "FakeAsyncConnection",
    "TcpFakeServer",
]

try:
    import valkey  # noqa: F401
    from ._valkey import FakeValkey, FakeAsyncValkey, FakeStrictValkey  # noqa: F401

    __all__.extend(
        [
            "FakeValkey",
            "FakeAsyncValkey",
            "FakeStrictValkey",
        ]
    )
except ImportError:
    pass
