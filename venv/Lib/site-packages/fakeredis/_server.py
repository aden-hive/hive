import logging
import threading
import time
import weakref
from collections import defaultdict
from typing import Dict, Tuple, Any, List, Optional, Union

import redis

from fakeredis._helpers import Database, FakeSelector
from fakeredis._typing import VersionType, ServerType
from fakeredis.model import AccessControlList, ClientInfo

LOGGER = logging.getLogger("fakeredis")


def _create_version(v: Union[Tuple[int, ...], int, str]) -> VersionType:
    if isinstance(v, tuple):
        return v
    if isinstance(v, int):
        return (v,)
    if isinstance(v, str):
        v_split = v.split(".")
        return tuple(int(x) for x in v_split)
    return v


def _version_to_str(v: VersionType) -> str:
    if isinstance(v, tuple):
        return ".".join(str(x) for x in v)
    return str(v)


class FakeServer:
    _servers_map: Dict[str, "FakeServer"] = {}

    def __init__(
        self,
        version: VersionType = (7,),
        server_type: ServerType = "redis",
        config: Optional[Dict[bytes, bytes]] = None,
    ) -> None:
        """Initialize a new FakeServer instance.
        :param version: The version of the server (e.g. 6, 7.4, "7.4.1", can also be a tuple)
        :param server_type: The type of server (redis, dragonfly, valkey)
        :param config: A dictionary of configuration options.

        Configuration options:
        - `requirepass`: The password required to authenticate to the server.
        - `aclfile`: The path to the ACL file.
        """
        self.lock = threading.Lock()
        self.dbs: Dict[int, Database] = defaultdict(lambda: Database(self.lock))
        # Maps channel/pattern to a weak set of sockets
        self.script_cache: Dict[bytes, bytes] = {}  # Maps SHA1 to the script source
        self.subscribers: Dict[bytes, weakref.WeakSet[Any]] = defaultdict(weakref.WeakSet)
        self.psubscribers: Dict[bytes, weakref.WeakSet[Any]] = defaultdict(weakref.WeakSet)
        self.ssubscribers: Dict[bytes, weakref.WeakSet[Any]] = defaultdict(weakref.WeakSet)
        self.lastsave: int = int(time.time())
        self.connected = True
        # List of weakrefs to sockets that are being closed lazily
        self.sockets: List[Any] = []
        self.closed_sockets: List[Any] = []
        self.version: VersionType = _create_version(version)
        if server_type not in ("redis", "dragonfly", "valkey"):
            raise ValueError(f"Unsupported server type: {server_type}")
        self.server_type: ServerType = server_type
        self.config: Dict[bytes, bytes] = config or {}
        self.acl: AccessControlList = AccessControlList()
        self.clients: Dict[str, Dict[str, Any]] = {}
        self._next_client_id = 1

    def get_next_client_id(self) -> int:
        with self.lock:
            client_id = self._next_client_id
            self._next_client_id += 1
        return client_id

    @staticmethod
    def get_server(key: str, version: VersionType, server_type: ServerType) -> "FakeServer":
        if key not in FakeServer._servers_map:
            FakeServer._servers_map[key] = FakeServer(version=version, server_type=server_type)
        return FakeServer._servers_map[key]


class FakeBaseConnectionMixin(object):
    def __init__(
        self, *args: Any, version: VersionType = (7, 0), server_type: ServerType = "redis", **kwargs: Any
    ) -> None:
        self.client_name: Optional[str] = None
        self.server_key: str
        self._sock = None
        self._selector: Optional[FakeSelector] = None
        self._server = kwargs.pop("server", None)
        self._client_class = kwargs.pop("client_class", redis.Redis)
        self._lua_modules = kwargs.pop("lua_modules", set())
        self._writer = kwargs.pop("writer", None)
        path = kwargs.pop("path", None)
        connected = kwargs.pop("connected", True)
        if self._server is None:
            if path:
                self.server_key = path
            else:
                host, port = kwargs.get("host"), kwargs.get("port")
                self.server_key = f"{host}:{port}"
            self.server_key += f":{server_type}:v{_version_to_str(version)[0]}"
            self._server = FakeServer.get_server(self.server_key, server_type=server_type, version=version)
            self._server.connected = connected
        client_info = kwargs.pop("client_info", {})
        super().__init__(*args, **kwargs)
        protocol = getattr(self, "protocol", 2)

        client_info.update(
            dict(
                id=self._server.get_next_client_id(),
                addr="127.0.0.1:57275",  # TODO get IP
                laddr="127.0.0.1:6379",  # TODO get IP
                fd=8,
                name="",
                idle=0,
                flags="N",
                db=0,
                sub=0,
                psub=0,
                ssub=0,
                multi=-1,
                qbuf=48,
                qbuf_free=16842,
                argv_mem=25,
                multi_mem=0,
                rbs=1024,
                rbp=0,
                obl=0,
                oll=0,
                omem=0,
                tot_mem=18737,
                events="r",
                cmd="auth",
                redir=-1,
                resp=protocol,
            )
        )
        self._client_info = ClientInfo(**client_info)
