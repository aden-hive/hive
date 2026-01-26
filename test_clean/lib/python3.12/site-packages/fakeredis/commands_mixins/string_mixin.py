import math
from typing import Tuple, Callable, List, Any, Optional, Dict

from fakeredis import _msgs as msgs
from fakeredis._command_args_parsing import extract_args
from fakeredis._commands import (
    command,
    Key,
    Int,
    Float,
    MAX_STRING_SIZE,
    delete_keys,
    fix_range_string,
    CommandItem,
)
from fakeredis._helpers import OK, SimpleError, casematch, Database, SimpleString
from fakeredis._typing import VersionType


def _lcs(s1: bytes, s2: bytes) -> Tuple[int, bytes, List[List[object]]]:
    l1 = len(s1)
    l2 = len(s2)

    # Opt array to store the optimal solution value till ith and jth position for 2 strings
    opt: List[List[int]] = [[0] * (l2 + 1) for _ in range(0, l1 + 1)]

    # Pi array to store the direction when calculating the actual sequence
    pi: List[List[int]] = [[0] * (l2 + 1) for _ in range(0, l1 + 1)]

    # Algorithm to calculate the length of the longest common subsequence
    for r in range(1, l1 + 1):
        for c in range(1, l2 + 1):
            if s1[r - 1] == s2[c - 1]:
                opt[r][c] = opt[r - 1][c - 1] + 1
                pi[r][c] = 0
            elif opt[r][c - 1] >= opt[r - 1][c]:
                opt[r][c] = opt[r][c - 1]
                pi[r][c] = 1
            else:
                opt[r][c] = opt[r - 1][c]
                pi[r][c] = 2
    # Length of the longest common subsequence is saved at opt[n][m]

    # Algorithm to calculate the longest common subsequence using the Pi array
    # Also calculate the list of matches
    r, c = l1, l2
    result = ""
    matches = []
    s1ind, s2ind, curr_length = None, None, 0

    while r > 0 and c > 0:
        if pi[r][c] == 0:
            result = chr(s1[r - 1]) + result
            r -= 1
            c -= 1
            curr_length += 1
        elif pi[r][c] == 2:
            r -= 1
        else:
            c -= 1

        if pi[r][c] == 0 and curr_length == 1:
            s1ind = r
            s2ind = c
        elif pi[r][c] > 0 and curr_length > 0:
            matches.append([[r, s1ind], [c, s2ind], curr_length])
            s1ind, s2ind, curr_length = None, None, 0
    if curr_length:
        matches.append([[s1ind, r], [s2ind, c], curr_length])

    return opt[l1][l2], result.encode(), matches


class StringCommandsMixin:
    _encodeint: Callable[
        [
            int,
        ],
        bytes,
    ]
    _encodefloat: Callable[[float, bool], bytes]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(StringCommandsMixin, self).__init__(*args, **kwargs)
        self._db: Database
        self.version: VersionType

    def _incrby(self, key: CommandItem, amount: int) -> int:
        c = Int.decode(key.get(b"0")) + amount
        key.update(self._encodeint(c))
        return c

    @command((Key(bytes), bytes))
    def append(self, key: CommandItem, value: bytes) -> int:
        old = key.get(b"")
        if len(old) + len(value) > MAX_STRING_SIZE:
            raise SimpleError(msgs.STRING_OVERFLOW_MSG)
        key.update(key.get(b"") + value)
        return len(key.value)

    @command((Key(bytes),))
    def decr(self, key: CommandItem) -> int:
        return self._incrby(key, -1)

    @command((Key(bytes), Int))
    def decrby(self, key: CommandItem, amount: int) -> int:
        return self._incrby(key, -amount)

    @command((Key(bytes),))
    def get(self, key: CommandItem) -> bytes:
        res: bytes = key.get(None)
        return res

    @command((Key(bytes),))
    def getdel(self, key: CommandItem) -> bytes:
        res: bytes = key.get(None)
        delete_keys(key)
        return res

    @command(name=["GETRANGE", "SUBSTR"], fixed=(Key(bytes), Int, Int))
    def getrange(self, key: CommandItem, start: int, end: int) -> bytes:
        value: bytes = key.get(b"")
        start, end = fix_range_string(start, end, len(value))
        return value[start:end]

    @command(fixed=(Key(bytes), bytes))
    def getset(self, key: CommandItem, value: bytes) -> bytes:
        old: bytes = key.value
        key.value = value
        return old

    @command(fixed=(Key(bytes), Int))
    def incrby(self, key: CommandItem, amount: int) -> int:
        return self._incrby(key, amount)

    @command(fixed=(Key(bytes),))
    def incr(self, key: CommandItem) -> int:
        return self._incrby(key, 1)

    @command(fixed=(Key(bytes), Float))
    def incrbyfloat(self, key: CommandItem, amount: float) -> bytes:
        c = Float.decode(key.get(b"0")) + amount
        if not math.isfinite(amount):
            raise SimpleError(msgs.NONFINITE_MSG)
        encoded = self._encodefloat(c, True)
        key.update(encoded)
        return encoded

    @command(fixed=(Key(),), repeat=(Key(),))
    def mget(self, *keys: CommandItem) -> List[Optional[bytes]]:
        return [key.value if isinstance(key.value, bytes) else None for key in keys]

    @command((Key(), bytes), (Key(), bytes))
    def mset(self, *args: Any) -> SimpleString:
        for i in range(0, len(args), 2):
            args[i].value = args[i + 1]
        return OK

    @command((Key(), bytes), (Key(), bytes))
    def msetnx(self, *args: Any) -> int:
        for i in range(0, len(args), 2):
            if args[i]:
                return 0
        for i in range(0, len(args), 2):
            args[i].value = args[i + 1]
        return 1

    @command((Key(), Int, bytes))
    def psetex(self, key: CommandItem, ms: int, value: bytes) -> SimpleString:
        if ms <= 0 or self._db.time * 1000 + ms >= 2**63:
            raise SimpleError(msgs.INVALID_EXPIRE_MSG.format("psetex"))
        key.value = value
        key.expireat = int(self._db.time + ms / 1000.0)
        return OK

    @command(name="SET", fixed=(Key(), bytes), repeat=(bytes,))
    def set_(self, key: CommandItem, value: bytes, *args: bytes) -> Any:
        (ex, px, exat, pxat, xx, nx, keepttl, get), _ = extract_args(
            args, ("+ex", "+px", "+exat", "+pxat", "xx", "nx", "keepttl", "get")
        )
        if ex is not None and (ex <= 0 or (self._db.time + ex) * 1000 >= 2**63):
            raise SimpleError(msgs.INVALID_EXPIRE_MSG.format("set"))
        if px is not None and (px <= 0 or self._db.time * 1000 + px >= 2**63):
            raise SimpleError(msgs.INVALID_EXPIRE_MSG.format("set"))
        if exat is not None and (exat <= 0 or exat * 1000 >= 2**63):
            raise SimpleError(msgs.INVALID_EXPIRE_MSG.format("set"))
        if pxat is not None and (pxat <= 0 or pxat >= 2**63):
            raise SimpleError(msgs.INVALID_EXPIRE_MSG.format("set"))

        if (xx and nx) or (sum(x is not None for x in [ex, px, exat, pxat]) + keepttl > 1):
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        if nx and get and self.version < (7,):
            # The command docs say this is allowed from Redis 7.0.
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)

        old_value = None
        if get:
            if key.value is not None and type(key.value) is not bytes:
                raise SimpleError(msgs.WRONGTYPE_MSG)
            old_value = key.value

        if nx and key:
            return old_value
        if xx and not key:
            return old_value
        if not keepttl:
            key.value = value
        else:
            key.update(value)
        if exat is not None:
            key.expireat = exat
        if pxat is not None:
            key.expireat = pxat / 1000.0
        if ex is not None:
            key.expireat = self._db.time + ex
        if px is not None:
            key.expireat = self._db.time + px / 1000.0
        return OK if not get else old_value

    @command((Key(), Int, bytes))
    def setex(self, key: CommandItem, seconds: int, value: bytes) -> SimpleString:
        if seconds <= 0 or (self._db.time + seconds) * 1000 >= 2**63:
            raise SimpleError(msgs.INVALID_EXPIRE_MSG.format("setex"))
        key.value = value
        key.expireat = int(self._db.time + seconds)
        return OK

    @command((Key(), bytes))
    def setnx(self, key: CommandItem, value: bytes) -> int:
        if key:
            return 0
        key.value = value
        return 1

    @command((Key(bytes), Int, bytes))
    def setrange(self, key: CommandItem, offset: int, value: bytes) -> int:
        if offset < 0:
            raise SimpleError(msgs.INVALID_OFFSET_MSG)
        elif not value:
            return len(key.get(b""))
        elif offset + len(value) > MAX_STRING_SIZE:
            raise SimpleError(msgs.STRING_OVERFLOW_MSG)
        out = key.get(b"")
        if len(out) < offset:
            out += b"\x00" * (offset - len(out))
        out = out[0:offset] + value + out[offset + len(value) :]
        key.update(out)
        return len(out)

    @command((Key(bytes),))
    def strlen(self, key: CommandItem) -> int:
        return len(key.get(b""))

    @command((Key(bytes),), (bytes,))
    def getex(self, key: CommandItem, *args: bytes) -> Any:
        i, count_options, expire_time, diff = 0, 0, None, None

        while i < len(args):
            count_options += 1
            if casematch(args[i], b"ex") and i + 1 < len(args):
                diff = Int.decode(args[i + 1])
                expire_time = self._db.time + diff
                i += 2
            elif casematch(args[i], b"px") and i + 1 < len(args):
                diff = Int.decode(args[i + 1])
                expire_time = (self._db.time * 1000 + diff) / 1000.0
                i += 2
            elif casematch(args[i], b"exat") and i + 1 < len(args):
                expire_time = Int.decode(args[i + 1])
                i += 2
            elif casematch(args[i], b"pxat") and i + 1 < len(args):
                expire_time = Int.decode(args[i + 1]) / 1000.0
                i += 2
            elif casematch(args[i], b"persist"):
                expire_time = None
                i += 1
            else:
                raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        if (expire_time is not None and (expire_time <= 0 or expire_time * 1000 >= 2**63)) or (
            diff is not None and (diff <= 0 or diff * 1000 >= 2**63)
        ):
            raise SimpleError(msgs.INVALID_EXPIRE_MSG.format("getex"))
        if count_options > 1:
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)

        key.expireat = None if expire_time is None else int(expire_time)
        return key.get(None)

    @command(fixed=(Key(bytes), Key(bytes)), repeat=(bytes,))
    def lcs(self, k1: CommandItem, k2: CommandItem, *args: bytes) -> Dict[bytes, Any]:
        s1 = k1.value or b""
        s2 = k2.value or b""

        (arg_idx, arg_len, arg_minmatchlen, arg_withmatchlen), _ = extract_args(
            args, ("idx", "len", "+minmatchlen", "withmatchlen")
        )
        if arg_idx and arg_len:
            raise SimpleError(msgs.LCS_CANT_HAVE_BOTH_LEN_AND_IDX)
        lcs_len, lcs_val, matches = _lcs(s1, s2)
        if not arg_idx and not arg_len:
            return lcs_val
        if arg_len:
            return lcs_len
        arg_minmatchlen = arg_minmatchlen if arg_minmatchlen else 0
        results = list(filter(lambda x: x[2] >= arg_minmatchlen, matches))
        if not arg_withmatchlen:
            results = [[x[0], x[1]] for x in results]
        return {b"matches": results, b"len": lcs_len}

    @command(name="MSETEX", fixed=(Int,), repeat=(bytes,))
    def msetex(self, num_keys: int, *args: Any) -> int:
        if num_keys <= 0:
            raise SimpleError("ERR invalid numkeys value")
        if len(args) < num_keys * 2:
            raise SimpleError("ERR wrong number of key-value pairs")
        mapping = {args[i]: args[i + 1] for i in range(0, num_keys * 2, 2)}
        args = args[num_keys * 2 :]
        (ex, px, exat, pxat, xx, nx, keepttl), _ = extract_args(
            args, ("+ex", "+px", "+exat", "+pxat", "xx", "nx", "keepttl")
        )
        if ex is not None and (ex <= 0 or (self._db.time + ex) * 1000 >= 2**63):
            raise SimpleError(msgs.INVALID_EXPIRE_MSG_REDIS_8.format("msetex"))
        if px is not None and (px <= 0 or self._db.time * 1000 + px >= 2**63):
            raise SimpleError(msgs.INVALID_EXPIRE_MSG_REDIS_8.format("msetex"))
        if exat is not None and (exat <= 0 or exat * 1000 >= 2**63):
            raise SimpleError(msgs.INVALID_EXPIRE_MSG_REDIS_8.format("msetex"))
        if pxat is not None and (pxat <= 0 or pxat >= 2**63):
            raise SimpleError(msgs.INVALID_EXPIRE_MSG_REDIS_8.format("msetex"))

        if (xx and nx) or (sum(x is not None for x in [ex, px, exat, pxat]) + keepttl > 1):
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)

        should_set = True
        for k in mapping:
            item = CommandItem(k, self._db, item=self._db.get(k))
            if nx and item.value is not None:
                should_set = False
                break
            if xx and item.value is None:
                should_set = False
                break
        if not should_set:
            return 0

        expireat = None
        if exat is not None:
            expireat = exat
        if pxat is not None:
            expireat = pxat / 1000.0
        if ex is not None:
            expireat = self._db.time + ex
        if px is not None:
            expireat = self._db.time + px / 1000.0

        for k, v in mapping.items():
            item = CommandItem(k, self._db, item=self._db.get(k))
            item.update(v)
            if not keepttl:
                item.expireat = expireat
            item.writeback()

        return 1
