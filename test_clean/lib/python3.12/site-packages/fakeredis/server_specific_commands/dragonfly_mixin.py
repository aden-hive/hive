from typing import Callable

from fakeredis._commands import command, Key, Int, CommandItem
from fakeredis._helpers import Database, current_time
from fakeredis.model import ExpiringMembersSet


class DragonflyCommandsMixin(object):
    _expireat: Callable[[CommandItem, int], int]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._db: Database

    @command(name="SADDEX", fixed=(Key(ExpiringMembersSet), Int, bytes), repeat=(bytes,), server_types=("dragonfly",))
    def saddex(self, key: CommandItem, seconds: int, *members: bytes) -> int:
        val = key.value
        old_size = len(val)
        new_members = set(members) - set(val)
        expire_at_ms = current_time() + seconds * 1000
        for member in new_members:
            val.set_member_expireat(member, expire_at_ms)
        key.updated()
        return len(val) - old_size
