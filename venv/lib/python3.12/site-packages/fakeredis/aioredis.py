from __future__ import annotations

import asyncio
import warnings
from typing import Union, Optional, Any, Callable, Iterable, Tuple, List, Set, Sequence

import redis.asyncio as redis_async
from redis import ResponseError
from redis.asyncio.connection import DefaultParser

from . import _fakesocket
from . import _helpers
from . import _msgs as msgs
from ._helpers import SimpleError, convert_args_to_redis_init_kwargs
from ._server import FakeBaseConnectionMixin, VersionType, FakeServer, ServerType
from ._typing import async_timeout, lib_version, Self, RaiseErrorTypes


class AsyncFakeSocket(_fakesocket.FakeSocket):
    _connection_error_class = redis_async.ConnectionError

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.responses: asyncio.Queue = asyncio.Queue()  # type:ignore

    def _decode_error(self, error: SimpleError) -> ResponseError:
        parser = DefaultParser(1)
        return parser.parse_error(error.value)

    def put_response(self, msg: Any) -> None:
        if not self.responses:
            return
        self.responses.put_nowait(msg)

    async def _async_blocking(
        self,
        timeout: Optional[Union[float, int]],
        func: Callable[[bool], Any],
        event: asyncio.Event,
        callback: Callable[[], None],
    ) -> None:
        result = None
        try:
            async with async_timeout(timeout if timeout else None):
                while True:
                    await event.wait()
                    event.clear()
                    # This is a coroutine outside the normal control flow that
                    # locks the server, so we have to take our own lock.
                    with self._server.lock:
                        ret = func(False)
                        if ret is not None:
                            result = self._decode_result(ret)
                            break
        except asyncio.TimeoutError:
            pass
        finally:
            with self._server.lock:
                self._db.remove_change_callback(callback)
            self.put_response(result)
            self.resume()

    def _blocking(
        self,
        timeout: Optional[Union[float, int]],
        func: Callable[[bool], None],
    ) -> Any:
        loop = asyncio.get_event_loop()
        ret = func(True)
        if ret is not None or self._in_transaction:
            return ret
        event = asyncio.Event()

        def callback() -> None:
            loop.call_soon_threadsafe(event.set)

        self._db.add_change_callback(callback)
        self.pause()
        loop.create_task(self._async_blocking(timeout, func, event, callback))
        return _helpers.NoResponse()


class FakeReader:
    def __init__(self, socket: AsyncFakeSocket) -> None:
        self._socket = socket

    async def read(self, _: int) -> bytes:
        return await self._socket.responses.get()  # type:ignore

    def at_eof(self) -> bool:
        return self._socket.responses.empty() and not self._socket._server.connected


class FakeWriter:
    def __init__(self, socket: AsyncFakeSocket) -> None:
        self._socket: Optional[AsyncFakeSocket] = socket

    def close(self) -> None:
        self._socket = None

    async def wait_closed(self) -> None:
        pass

    async def drain(self) -> None:
        pass

    def writelines(self, data: Iterable[Any]) -> None:
        if self._socket is None:
            return
        for chunk in data:
            self._socket.sendall(chunk)  # type:ignore


class FakeConnection(FakeBaseConnectionMixin, redis_async.Connection):
    async def _connect(self) -> None:
        if not self._server.connected:
            raise redis_async.ConnectionError(msgs.CONNECTION_ERROR_MSG)
        self._sock: Optional[AsyncFakeSocket] = AsyncFakeSocket(
            self._server, self.db, client_class=self._client_class, lua_modules=self._lua_modules
        )
        self._reader: Optional[FakeReader] = FakeReader(self._sock)
        self._writer: Optional[FakeWriter] = FakeWriter(self._sock)

    def __del__(self):
        # Ensure _writer is cleared even if disconnect() was never called
        # This prevents ResourceWarning on Python 3.13+ during garbage collection
        self._writer = None
        self._reader = None
        self._sock = None

    async def disconnect(self, nowait: bool = False, **kwargs: Any) -> None:
        # Clear these BEFORE calling super().disconnect() to prevent ResourceWarning
        self._sock = None
        self._reader = None
        self._writer = None
        await super().disconnect(**kwargs)

    async def can_read(self, timeout: Optional[float] = 0) -> bool:
        if not self.is_connected:
            await self.connect()
        if timeout == 0:
            return self._sock is not None and not self._sock.responses.empty()
        # asyncio.Queue doesn't have a way to wait for the queue to be
        # non-empty without consuming an item, so kludge it with a sleep/poll
        # loop.
        loop = asyncio.get_event_loop()
        start = loop.time()
        while True:
            if self._sock and not self._sock.responses.empty():
                return True
            await asyncio.sleep(0.01)
            now = loop.time()
            if timeout is not None and now > start + timeout:
                return False

    async def _get_from_local_cache(self, command: Sequence[str]) -> None:
        return None

    def _add_to_local_cache(self, command: Sequence[str], response: Any, keys: List[Any]) -> None:
        return None

    def _decode(self, response: Any) -> Any:
        if isinstance(response, list):
            return [self._decode(item) for item in response]
        elif isinstance(response, bytes):
            return self.encoder.decode(response)
        else:
            return response

    async def read_response(self, **kwargs: Any) -> Any:  # type: ignore
        if not self._sock:
            raise redis_async.ConnectionError(msgs.CONNECTION_ERROR_MSG)
        if not self._server.connected:
            try:
                response = self._sock.responses.get_nowait()
            except asyncio.QueueEmpty:
                if kwargs.get("disconnect_on_error", True):
                    await self.disconnect()
                raise redis_async.ConnectionError(msgs.CONNECTION_ERROR_MSG)
        else:
            timeout: Optional[float] = kwargs.pop("timeout", None)
            can_read = await self.can_read(timeout)
            response = await self._reader.read(0) if can_read and self._reader else None
        if isinstance(response, RaiseErrorTypes):
            raise response
        if kwargs.get("disable_decoding", False):
            return response
        return self._decode(response)

    def repr_pieces(self) -> List[Tuple[str, Any]]:
        pieces = [("server", self._server), ("db", self.db)]
        if self.client_name:
            pieces.append(("client_name", self.client_name))
        return pieces

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
        client_class=redis_async.Redis,
        **kwargs: Any,
    ) -> None:
        kwds = convert_args_to_redis_init_kwargs(client_class, *args, **kwargs)
        kwds["server"] = server
        kwds["connected"] = kwargs.get("connected", True)
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
            kwds["connection_pool"] = redis_async.connection.ConnectionPool(**connection_kwargs)  # type: ignore
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
    def from_url(cls, url: str, **kwargs: Any) -> Self:
        self: redis_async.Redis = super().from_url(url, **kwargs)
        pool = self.connection_pool  # Now override how it creates connections
        pool.connection_class = FakeConnection
        pool.connection_kwargs.setdefault("version", "7.4")
        pool.connection_kwargs.setdefault("server_type", "redis")
        return self


class FakeRedis(FakeRedisMixin, redis_async.Redis):
    pass
