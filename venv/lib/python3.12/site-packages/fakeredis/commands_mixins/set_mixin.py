import random
from typing import Callable, Any, Optional, List, Union, Sequence

from fakeredis import _msgs as msgs
from fakeredis._commands import command, Key, Int, CommandItem
from fakeredis._helpers import OK, SimpleError, casematch, Database, SimpleString
from fakeredis.model import ExpiringMembersSet
from fakeredis._typing import VersionType


def _calc_setop(op: Callable[..., Any], stop_if_missing: bool, key: CommandItem, *keys: CommandItem) -> Any:
    if stop_if_missing and not key.value:
        return set()
    value = key.value
    if not isinstance(value, ExpiringMembersSet):
        raise SimpleError(msgs.WRONGTYPE_MSG)
    ans = value.copy()
    for other in keys:
        value = other.value if other.value is not None else ExpiringMembersSet()
        if not isinstance(value, ExpiringMembersSet):
            raise SimpleError(msgs.WRONGTYPE_MSG)
        if stop_if_missing and not value:
            return set()
        ans = op(ans, value)
    return ans


def _setop(
    op: Callable[..., Any], stop_if_missing: bool, dst: Optional[CommandItem], key: CommandItem, *keys: CommandItem
) -> Any:
    """Apply one of SINTER[STORE], SUNION[STORE], SDIFF[STORE].

    If `stop_if_missing`, the output will be made an empty set as soon as
    an empty input set is encountered (use for SINTER[STORE]). May assume
    that `key` is a set (or empty), but `keys` could be anything.
    """
    ans = _calc_setop(op, stop_if_missing, key, *keys)
    if dst is None:
        return list(ans)
    else:
        dst.value = ans
        return len(dst.value)


class SetCommandsMixin:
    _scan: Callable[[Sequence[bytes], int, bytes], List[Union[bytes, List[bytes]]]]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(SetCommandsMixin, self).__init__(*args, **kwargs)
        self.version: VersionType
        self._db: Database

    @command((Key(ExpiringMembersSet), bytes), (bytes,))
    def sadd(self, key: CommandItem, *members: bytes) -> int:
        old_size = len(key.value)
        key.value.update(members)
        key.updated()
        return len(key.value) - old_size

    @command((Key(ExpiringMembersSet),))
    def scard(self, key: CommandItem) -> int:
        return len(key.value)

    @command((Key(ExpiringMembersSet),), (Key(ExpiringMembersSet),))
    def sdiff(self, *keys: CommandItem) -> Any:
        return _setop(lambda a, b: a - b, False, None, *keys)

    @command((Key(), Key(ExpiringMembersSet)), (Key(ExpiringMembersSet),))
    def sdiffstore(self, dst: CommandItem, *keys: CommandItem) -> Any:
        return _setop(lambda a, b: a - b, False, dst, *keys)

    @command((Key(ExpiringMembersSet),), (Key(ExpiringMembersSet),))
    def sinter(self, *keys: CommandItem) -> Any:
        res = _setop(lambda a, b: a & b, True, None, *keys)
        return res

    @command((Int, bytes), (bytes,))
    def sintercard(self, numkeys: int, *args: bytes) -> int:
        if self.version < (7,):
            raise SimpleError(msgs.UNKNOWN_COMMAND_MSG.format("sintercard"))
        if numkeys < 1:
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        limit = 0
        if casematch(args[-2], b"limit"):
            limit = Int.decode(args[-1])
            args = args[:-2]
        if numkeys != len(args):
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        keys = [CommandItem(args[i], self._db, item=self._db.get(args[i], default=None)) for i in range(numkeys)]

        res = _setop(lambda a, b: a & b, False, None, *keys)
        return len(res) if limit == 0 else min(limit, len(res))

    @command((Key(), Key(ExpiringMembersSet)), (Key(ExpiringMembersSet),))
    def sinterstore(self, dst: CommandItem, *keys: CommandItem) -> Any:
        return _setop(lambda a, b: a & b, True, dst, *keys)

    @command((Key(ExpiringMembersSet), bytes))
    def sismember(self, key: CommandItem, member: bytes) -> int:
        return int(member in key.value)

    @command((Key(ExpiringMembersSet), bytes), (bytes,))
    def smismember(self, key: CommandItem, *members: bytes) -> List[int]:
        return [self.sismember(key, member) for member in members]

    @command((Key(ExpiringMembersSet),))
    def smembers(self, key: CommandItem) -> List[bytes]:
        return list(key.value)

    @command((Key(ExpiringMembersSet, 0), Key(ExpiringMembersSet), bytes))
    def smove(self, src: CommandItem, dst: CommandItem, member: bytes) -> int:
        try:
            src.value.remove(member)
            src.updated()
        except KeyError:
            return 0
        else:
            dst.value.add(member)
            dst.updated()  # TODO: is it updated if member was already present?
            return 1

    @command((Key(ExpiringMembersSet),), (Int,))
    def spop(self, key: CommandItem, count: Optional[int] = None) -> Union[bytes, List[bytes], None]:
        if count is None:
            if not key.value:
                return None
            item = random.sample(list(key.value), 1)[0]
            key.value.remove(item)
            key.updated()
            return item  # type: ignore
        else:
            if count < 0:
                raise SimpleError(msgs.INDEX_ERROR_MSG)
            items: Union[bytes, List[bytes]] = self.srandmember(key, count)
            for item in items:
                key.value.remove(item)
                key.updated()  # Inside the loop because redis special-cases count=0
            return items

    @command((Key(ExpiringMembersSet),), (Int,))
    def srandmember(self, key: CommandItem, count: Optional[int] = None) -> Union[bytes, List[bytes], None]:
        if count is None:
            if not key.value:
                return None
            else:
                return random.sample(list(key.value), 1)[0]  # type: ignore
        elif count >= 0:
            count = min(count, len(key.value))
            return random.sample(list(key.value), count)
        else:
            items = list(key.value)
            return [random.choice(items) for _ in range(-count)]

    @command((Key(ExpiringMembersSet), bytes), (bytes,))
    def srem(self, key: CommandItem, *members: bytes) -> int:
        old_size = len(key.value)
        for member in members:
            key.value.discard(member)
        deleted = old_size - len(key.value)
        if deleted:
            key.updated()
        return deleted

    @command((Key(ExpiringMembersSet), Int), (bytes, bytes))
    def sscan(self, key: CommandItem, cursor: int, *args: bytes) -> Any:
        return self._scan(key.value, cursor, *args)

    @command((Key(ExpiringMembersSet),), (Key(ExpiringMembersSet),))
    def sunion(self, *keys: CommandItem) -> Any:
        return _setop(lambda a, b: a | b, False, None, *keys)

    @command((Key(), Key(ExpiringMembersSet)), (Key(ExpiringMembersSet),))
    def sunionstore(self, dst: CommandItem, *keys: CommandItem) -> Any:
        return _setop(lambda a, b: a | b, False, dst, *keys)

    # Hyperloglog commands
    # These are not quite the same as the real redis ones, which are
    # approximate and store the results in a string. Instead, it is implemented
    # on top of sets.

    @command((Key(ExpiringMembersSet),), (bytes,))
    def pfadd(self, key: CommandItem, *elements: bytes) -> int:
        result = self.sadd(key, *elements)
        # Per the documentation:
        # - 1 if at least 1 HyperLogLog internal register was altered. 0 otherwise.
        return 1 if result > 0 else 0

    @command((Key(ExpiringMembersSet),), (Key(ExpiringMembersSet),))
    def pfcount(self, *keys: CommandItem) -> int:
        """Return the approximated cardinality of the set observed by the HyperLogLog at key(s)."""
        return len(self.sunion(*keys))

    @command((Key(ExpiringMembersSet), Key(ExpiringMembersSet)), (Key(ExpiringMembersSet),))
    def pfmerge(self, dest: CommandItem, *sources: CommandItem) -> SimpleString:
        """Merge N different HyperLogLogs into a single one."""
        self.sunionstore(dest, *sources)
        return OK
