import queue
import warnings
from typing import Tuple, Any, List, Optional, Set, Sequence, Union, Type

import redis

from fakeredis._fakesocket import FakeSocket
from fakeredis._helpers import FakeSelector, convert_args_to_redis_init_kwargs
from . import _msgs as msgs
from ._server import FakeBaseConnectionMixin, FakeServer
from ._typing import Self, lib_version, RaiseErrorTypes, VersionType, ServerType


class FakeConnection(FakeBaseConnectionMixin, redis.Connection):
    def __init__(*args: Any, **kwargs: Any) -> None:
        FakeBaseConnectionMixin.__init__(*args, **kwargs)

    def connect(self) -> None:
        super().connect()  # type: ignore
        # The selector is set in redis.Connection.connect() after _connect() is called
        self._selector: Optional[FakeSelector] = FakeSelector(self._sock)

    def _connect(self) -> FakeSocket:
        if not self._server.connected:
            raise redis.ConnectionError(msgs.CONNECTION_ERROR_MSG)
        return FakeSocket(
            self._server,
            client_class=self._client_class,
            db=self.db,
            lua_modules=self._lua_modules,
            client_info=self._client_info,
        )

    def can_read(self, timeout: Optional[float] = 0) -> bool:
        if not self._server.connected:
            return True
        if not self._sock:
            self.connect()
        # We use check_can_read rather than can_read, because on redis-py<3.2,
        # FakeSelector inherits from a stub BaseSelector which doesn't
        # implement can_read. Normally can_read provides retries on EINTR,
        # but that's not necessary for the implementation of
        # FakeSelector.check_can_read.
        return self._selector is not None and self._selector.check_can_read(timeout)

    def _decode(self, response: Any) -> Any:
        if isinstance(response, list):
            return [self._decode(item) for item in response]
        elif isinstance(response, dict):
            return {self._decode(k): self._decode(v) for k, v in response.items()}
        elif isinstance(response, bytes):
            return self.encoder.decode(response)  # type: ignore
        else:
            return response

    def read_response(self, **kwargs: Any) -> Any:  # type: ignore
        if not self._sock:
            raise redis.ConnectionError(msgs.CONNECTION_ERROR_MSG)
        if not self._server.connected:
            try:
                response = self._sock.responses.get_nowait()
            except queue.Empty:
                if kwargs.get("disconnect_on_error", True):
                    self.disconnect()
                raise redis.ConnectionError(msgs.CONNECTION_ERROR_MSG)
        else:
            response = self._sock.responses.get()

        if isinstance(response, RaiseErrorTypes):
            raise response
        res = response if kwargs.get("disable_decoding", False) else self._decode(response)
        return res

    def repr_pieces(self) -> List[Tuple[str, Any]]:
        pieces = [("server", self._server), ("db", self.db)]
        if self.client_name:
            pieces.append(("client_name", self.client_name))
        return pieces

    def _get_from_local_cache(self, command: Sequence[str]) -> None:
        return None

    def _add_to_local_cache(self, command: Sequence[str], response: Any, keys: List[Any]) -> None:
        return None

    def get_socket(self) -> FakeSocket:
        if not self._sock:
            self.connect()
        return self._sock  # type: ignore

    def __str__(self) -> str:
        return self.server_key


class FakeRedisMixin:
    def __init__(
        self,
        *args: Any,
        server: Optional[FakeServer] = None,
        version: Union[VersionType, str, int] = (7,),  # https://github.com/cunla/fakeredis-py/issues/401
        server_type: ServerType = "redis",
        lua_modules: Optional[Set[str]] = None,
        client_class: Type[redis.Redis] = redis.Redis,
        **kwargs: Any,
    ) -> None:
        """
        :param server: The FakeServer instance to use for this connection.
        :param version: The Redis version to use, as a tuple (major, minor).
        :param server_type: The type of server, e.g., "redis", "valkey".
        :param lua_modules: A set of Lua modules to load.
        :param client_class: The Redis client class to use, e.g., redis.Redis or valkey.Valkey.
        """
        kwds = convert_args_to_redis_init_kwargs(client_class, *args, **kwargs)
        kwds["server"] = server
        if not kwds.get("connection_pool", None):
            charset = kwds.get("charset", None)
            errors = kwds.get("errors", None)
            # Adapted from redis-py
            if charset is not None:
                warnings.warn(DeprecationWarning('"charset" is deprecated. Use "encoding" instead'))
                kwds["encoding"] = charset
            if errors is not None:
                warnings.warn(DeprecationWarning('"errors" is deprecated. Use "encoding_errors" instead'))
                kwds["encoding_errors"] = errors
            conn_pool_args = {
                "host",
                "port",
                "db",
                "username",
                "password",
                "socket_timeout",
                "encoding",
                "encoding_errors",
                "decode_responses",
                "retry_on_timeout",
                "max_connections",
                "health_check_interval",
                "client_name",
                "connected",
                "server",
                "protocol",
            }
            connection_kwargs = {
                "connection_class": FakeConnection,
                "version": version,
                "server_type": server_type,
                "lua_modules": lua_modules,
                "client_class": client_class,
            }
            connection_kwargs.update({arg: kwds[arg] for arg in conn_pool_args if arg in kwds})
            kwds["connection_pool"] = redis.connection.ConnectionPool(**connection_kwargs)
        kwds.pop("server", None)
        kwds.pop("connected", None)
        kwds.pop("version", None)
        kwds.pop("server_type", None)
        kwds.pop("lua_modules", None)
        if "lib_name" in kwds and "lib_version" in kwds:
            kwds["lib_name"] = "fakeredis"
            kwds["lib_version"] = lib_version
        super().__init__(**kwds)

    @classmethod
    def from_url(cls, *args: Any, **kwargs: Any) -> Self:
        kwargs.setdefault("version", "7.4")
        kwargs.setdefault("server_type", "redis")
        pool = redis.ConnectionPool.from_url(*args, **kwargs)
        # Now override how it creates connections
        pool.connection_class = FakeConnection
        return cls(connection_pool=pool, *args, **kwargs)


class FakeStrictRedis(FakeRedisMixin, redis.StrictRedis):
    pass


class FakeRedis(FakeRedisMixin, redis.Redis):
    pass
