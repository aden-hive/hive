from typing import Any, List, Union, Dict

import fakeredis
from fakeredis import _msgs as msgs
from fakeredis._commands import command, DbIndex, Int
from fakeredis._helpers import SimpleError, OK, SimpleString, Database, casematch
from fakeredis.model import ClientInfo

PONG = SimpleString(b"PONG")


class ConnectionCommandsMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(ConnectionCommandsMixin, self).__init__(*args, **kwargs)
        self._db: Database
        self._db_num: int
        self._pubsub: int
        self._client_info: ClientInfo
        self._server: Any

    @command((bytes,))
    def echo(self, message: bytes) -> bytes:
        return message

    @command((), (bytes,))
    def ping(self, *args: bytes) -> Union[List[bytes], bytes, SimpleString]:
        if len(args) > 1:
            msg = msgs.WRONG_ARGS_MSG6.format("ping")
            raise SimpleError(msg)
        if self._pubsub and self._client_info.protocol_version == 2:
            return [b"pong", args[0] if args else b""]
        else:
            return args[0] if args else PONG

    @command(name="SELECT", fixed=(DbIndex,))
    def select(self, index: DbIndex) -> SimpleString:
        self._db = self._server.dbs[index]
        self._db_num = index  # type: ignore
        return OK

    @command(name="CLIENT SETINFO", fixed=(bytes, bytes), repeat=())
    def client_setinfo(self, lib_data: bytes, value: bytes) -> SimpleString:
        if casematch(lib_data, b"LIB-NAME"):
            self._client_info["lib-name"] = value.decode("utf-8")
            return OK
        if casematch(lib_data, b"LIB-VER"):
            self._client_info["lib-ver"] = value.decode("utf-8")
            return OK
        raise SimpleError(msgs.SYNTAX_ERROR_MSG)

    @command(name="CLIENT SETNAME", fixed=(bytes,), repeat=())
    def client_setname(self, value: bytes) -> SimpleString:
        self._client_info["name"] = value.decode("utf-8")
        return OK

    @command(name="CLIENT GETNAME", fixed=(), repeat=())
    def client_getname(self) -> bytes:
        return self._client_info.get("name", "").encode("utf-8")

    @command(name="CLIENT ID", fixed=(), repeat=())
    def client_getid(self) -> int:
        return self._client_info.get("id", 1)

    @command(name="CLIENT INFO", fixed=(), repeat=())
    def client_info_cmd(self) -> bytes:
        return self._client_info.as_bytes()

    @command(name="CLIENT LIST", fixed=(), repeat=(bytes,))
    def client_list_cmd(self, *args: bytes) -> bytes:
        sockets = self._server.sockets.copy()
        i = 0
        filter_ids = set()
        while i < len(args):
            if casematch(args[i], b"TYPE") and i + 1 < len(args):
                i += 2
            if casematch(args[i], b"ID") and i + 1 < len(args):
                i += 1
                while i < len(args):
                    filter_ids.add(Int.decode(args[i]))
                    i += 1
            else:
                raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        if len(filter_ids) > 0:
            sockets = [sock for sock in sockets if sock._client_info["id"] in filter_ids]
        res = [item._client_info.as_bytes() for item in sockets]
        return b"\n".join(res)

    @command(name="HELLO", fixed=(), repeat=(bytes,))
    def hello(self, *args: bytes) -> Dict[str, str]:
        self._client_info["resp"] = 2 if len(args) == 0 else Int.decode(args[0])
        i = 1
        while i < len(args):
            if args[i] == b"SETNAME" and i + 1 < len(args):
                self._client_info["name"] = args[i + 1].decode("utf-8")
                i += 2
            elif args[i] == b"AUTH" and i + 2 < len(args):
                user = args[i + 1]
                password = args[i + 2]
                self._server._acl.get_user_acl(user).check_password(password)
                i += 3
            else:
                raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        data = {
            "server": "fakeredis",
            "version": fakeredis.__version__,
            "proto": self._client_info["resp"],
            "id": self._client_info.get("id", 1),
            "mode": "standalone",
            "role": "master",
            "modules": [],
        }
        return data

    @command(name="CLIENT MAINT_NOTIFICATIONS", fixed=(), repeat=(bytes,))
    def client_maint_notifications(self, *args: bytes) -> SimpleString:
        pass
