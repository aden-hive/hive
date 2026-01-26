import time
from typing import Any, List

from fakeredis import _msgs as msgs
from fakeredis._commands import command, DbIndex
from fakeredis._helpers import OK, SimpleError, casematch, BGSAVE_STARTED, Database, SimpleString
from fakeredis.model import get_command_info, get_all_commands_info


class ServerCommandsMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        from fakeredis._server import FakeServer

        self._server: "FakeServer"
        self._db: Database

    @command((), (bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def bgsave(self, *args: bytes) -> SimpleString:
        if len(args) > 1 or (len(args) == 1 and not casematch(args[0], b"schedule")):
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        self._server.lastsave = int(time.time())
        return BGSAVE_STARTED

    @command(())
    def dbsize(self) -> int:
        return len(self._db)

    @command((), (bytes,))
    def flushdb(self, *args: bytes) -> SimpleString:
        if len(args) > 0 and (len(args) != 1 or not casematch(args[0], b"async")):
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        self._db.clear()
        return OK

    @command((), (bytes,))
    def flushall(self, *args: bytes) -> SimpleString:
        if len(args) > 0 and (len(args) != 1 or not casematch(args[0], b"async")):
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        for db in self._server.dbs.values():
            db.clear()
        # TODO: clear watches and/or pubsub as well?
        return OK

    @command(())
    def lastsave(self) -> int:
        return self._server.lastsave

    @command((), flags=msgs.FLAG_NO_SCRIPT)
    def save(self) -> SimpleString:
        self._server.lastsave = int(time.time())
        return OK

    @command(())
    def time(self) -> List[bytes]:
        now_us = round(time.time() * 1_000_000)
        now_s = now_us // 1_000_000
        now_us %= 1_000_000
        return [str(now_s).encode(), str(now_us).encode()]

    @command((DbIndex, DbIndex))
    def swapdb(self, index1: int, index2: int) -> SimpleString:
        if index1 != index2:
            db1 = self._server.dbs[index1]
            db2 = self._server.dbs[index2]
            db1.swap(db2)
        return OK

    @command(name="COMMAND INFO", fixed=(), repeat=(bytes,))
    def command_info(self, *commands: bytes) -> List[Any]:
        res = [get_command_info(cmd) for cmd in commands]
        return res

    @command(name="COMMAND COUNT", fixed=(), repeat=())
    def command_count(self) -> int:
        return len(get_all_commands_info())

    @command(name="COMMAND", fixed=(), repeat=())
    def command_(self) -> List[Any]:
        res = [get_command_info(cmd) for cmd in get_all_commands_info()]
        return res
