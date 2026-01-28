from fakeredis._helpers import SimpleError

try:
    import fcntl

    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
import logging
import os
import time
from dataclasses import dataclass
from io import BufferedIOBase
from itertools import count
from socketserver import ThreadingTCPServer, StreamRequestHandler
from typing import Dict, Tuple, Any, Union

from redis.connection import DefaultParser

from fakeredis import FakeServer, FakeConnection
from fakeredis._typing import VersionType, ServerType

LOGGER = logging.getLogger("fakeredis")
# LOGGER.setLevel(logging.DEBUG)

# logging.basicConfig(level=logging.DEBUG)

try:
    import lupa  # noqa: F401

    lua_scripts_supported = True
except ImportError:
    lua_scripts_supported = False


def to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode()


_EXCEPTION_PREFIX_MAP: Dict[Exception, str] = {
    v: k for k, v in DefaultParser.EXCEPTION_CLASSES.items() if type(v) is not dict
}


def _get_exception_prefix(e: Exception) -> str:
    for k, v in _EXCEPTION_PREFIX_MAP.items():
        if isinstance(e, k):
            return v
    return "ERR"


@dataclass
class Writer:
    client_address: Tuple[str, int]
    writer: BufferedIOBase
    request_handler: StreamRequestHandler

    def write(self, value: bytes) -> None:
        LOGGER.debug(f"<<< {self.client_address}: {value}")
        self.writer.write(value)
        self.writer.flush()

    def dump(self, value: Any, dump_bulk: bool = False) -> None:
        if isinstance(value, int):
            self.write(f":{value}\r\n".encode())
        elif isinstance(value, (str, bytes)):
            value = to_bytes(value)
            if value.upper() == b"SHUTDOWN":
                self.request_handler.shutdown_request = True
            if dump_bulk or b"\r" in value or b"\n" in value:
                self.write(b"$" + str(len(value)).encode() + b"\r\n" + value + b"\r\n")
            else:
                self.write(b"+" + value + b"\r\n")
        elif isinstance(value, (list, set)):
            self.write(f"*{len(value)}\r\n".encode())
            for item in value:
                self.dump(item, dump_bulk=True)
        elif value is None:
            self.write("$-1\r\n".encode())
        elif isinstance(value, Exception):
            if isinstance(value, SimpleError):
                self.write(f"-{value.args[0]}\r\n".encode())
            else:
                prefix = _get_exception_prefix(value)
                self.write(f"-{prefix} {value.args[0]}\r\n".encode())


class TCPFakeRequestHandler(StreamRequestHandler):
    server: "TcpFakeServer"  # type: ignore
    shutdown_request: bool = False

    def setup(self) -> None:
        super().setup()
        fd = self.rfile.fileno()
        if HAS_FCNTL:
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        if self.client_address in self.server.clients:
            self.current_client = self.server.clients[self.client_address]
        else:
            self.writer = Writer(self.client_address, self.wfile, self)
            self.current_client = FakeConnection(
                server=self.server.fake_server,
                writer=self.writer,
                client_info={"raddr": self.client_address},
            )

            self.server.clients[self.client_address] = self.current_client

    def handle(self) -> None:
        LOGGER.debug(f"+++ {self.client_address[0]} connected")
        while True:
            try:
                if self.shutdown_request:
                    break
                if self.current_client.can_read():
                    response = self.current_client.read_response()
                    self.writer.dump(response)
                    continue

                data = self.rfile.readline()
                if data == b"":
                    time.sleep(0)
                else:
                    self.current_client.get_socket().sendall(data)

            except Exception as e:
                LOGGER.debug(f"!!! {self.client_address[0]}: {e}")
                self.writer.dump(e)
                break

    def finish(self) -> None:
        self.current_client.disconnect()
        LOGGER.debug(f"--- {self.client_address[0]} disconnected")
        self.rfile.close()
        self.wfile.close()
        del self.server.clients[self.client_address]
        super().finish()


class TcpFakeServer(ThreadingTCPServer):
    def __init__(
        self,
        server_address: Tuple[Union[str, bytes, bytearray], int],
        bind_and_activate: bool = True,
        server_type: ServerType = "redis",
        server_version: VersionType = (8, 0),
    ):
        self.allow_reuse_address = True
        self.daemon_threads = True
        super().__init__(server_address, TCPFakeRequestHandler, bind_and_activate)
        self.fake_server = FakeServer(server_type=server_type, version=server_version)
        self.client_ids = count(0)
        self.clients: Dict[int, FakeConnection] = {}


TCP_SERVER_TEST_PORT = 19000
if __name__ == "__main__":
    server = TcpFakeServer(("localhost", TCP_SERVER_TEST_PORT))
    server.serve_forever()
    server.server_close()
    server.shutdown()
