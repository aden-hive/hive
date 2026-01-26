import random
from typing import Callable, List, Any, Optional, Sequence, Union, Mapping

import math

from fakeredis import _msgs as msgs
from fakeredis._command_args_parsing import extract_args
from fakeredis._commands import command, Key, Int, Float, CommandItem
from fakeredis._helpers import SimpleError, OK, casematch, SimpleString
from fakeredis._helpers import current_time
from fakeredis.model import Hash, ClientInfo


class HashCommandsMixin:
    _encodeint: Callable[
        [
            int,
        ],
        bytes,
    ]
    _encodefloat: Callable[[float, bool], bytes]
    _scan: Callable[[Sequence[bytes], int, bytes], List[Union[bytes, List[bytes]]]]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(HashCommandsMixin, self).__init__(*args, **kwargs)
        self._client_info: ClientInfo

    def _hset(self, key: CommandItem, *args: bytes) -> int:
        h = key.value
        previous_keys_count = len(h.keys())
        h.update(dict(zip(*[iter(args)] * 2)), clear_expiration=True)  # type: ignore  # https://stackoverflow.com/a/12739974/1056460
        created = len(h.keys()) - previous_keys_count

        key.updated()
        return created

    @command((Key(Hash), bytes), (bytes,))
    def hdel(self, key: CommandItem, *fields: bytes) -> int:
        h = key.value
        rem = 0
        for field in fields:
            if field in h:
                del h[field]
                key.updated()
                rem += 1
        return rem

    @command((Key(Hash), bytes))
    def hexists(self, key: CommandItem, field: bytes) -> int:
        return int(field in key.value)

    @command((Key(Hash), bytes))
    def hget(self, key: CommandItem, field: bytes) -> Any:
        return key.value.get(field)

    @command((Key(Hash),))
    def hgetall(self, key: CommandItem) -> Mapping[str, str]:
        return key.value.getall()

    @command(fixed=(Key(Hash), bytes, bytes))
    def hincrby(self, key: CommandItem, field: bytes, amount_bytes: bytes) -> int:
        amount = Int.decode(amount_bytes)
        field_value = Int.decode(key.value.get(field, b"0"), decode_error=msgs.INVALID_HASH_MSG)
        c = field_value + amount
        key.value.update({field: self._encodeint(c)}, clear_expiration=False)
        key.updated()
        return c

    @command((Key(Hash), bytes, bytes))
    def hincrbyfloat(self, key: CommandItem, field: bytes, amount: bytes) -> bytes:
        c = Float.decode(key.value.get(field, b"0")) + Float.decode(amount)
        if not math.isfinite(c):
            raise SimpleError(msgs.NONFINITE_MSG)
        encoded = self._encodefloat(c, True)
        key.value.update({field: encoded}, clear_expiration=False)
        key.updated()
        return encoded

    @command((Key(Hash),))
    def hkeys(self, key: CommandItem) -> List[bytes]:
        return list(key.value.keys())

    @command((Key(Hash),))
    def hlen(self, key: CommandItem) -> int:
        return len(key.value)

    @command((Key(Hash), bytes), (bytes,))
    def hmget(self, key: CommandItem, *fields: bytes) -> List[bytes]:
        return [key.value.get(field) for field in fields]

    @command((Key(Hash), bytes, bytes), (bytes, bytes))
    def hmset(self, key: CommandItem, *args: bytes) -> SimpleString:
        self.hset(key, *args)
        return OK

    @command((Key(Hash), Int), (bytes,))
    def hscan(self, key: CommandItem, cursor: int, *args: bytes) -> List[Any]:
        no_values = any(casematch(arg, b"novalues") for arg in args)
        if no_values:
            args = [arg for arg in args if not casematch(arg, b"novalues")]
        cursor, keys = self._scan(key.value, cursor, *args)
        keys = [k.encode("utf-8") for k in keys if isinstance(k, str)]
        if no_values:
            return [cursor, keys]
        items = []
        for k in keys:
            items.append(k)
            items.append(key.value[k])
        return [cursor, items]

    @command((Key(Hash), bytes, bytes), (bytes, bytes))
    def hset(self, key: CommandItem, *args: bytes) -> int:
        return self._hset(key, *args)

    @command((Key(Hash), bytes, bytes))
    def hsetnx(self, key: CommandItem, field: bytes, value: bytes) -> int:
        if field in key.value:
            return 0
        return self._hset(key, field, value)

    @command((Key(Hash), bytes))
    def hstrlen(self, key: CommandItem, field: bytes) -> int:
        return len(key.value.get(field, b""))

    @command((Key(Hash),))
    def hvals(self, key: CommandItem) -> List[bytes]:
        return list(key.value.values())

    @command(name="HRANDFIELD", fixed=(Key(Hash),), repeat=(bytes,))
    def hrandfield(self, key: CommandItem, *args: bytes) -> Union[List[List[str]], List[str], None]:
        if len(args) > 2:
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        if key.value is None or len(key.value) == 0:
            return None
        count = min(Int.decode(args[0]) if len(args) >= 1 else 1, len(key.value))
        withvalues = casematch(args[1], b"withvalues") if len(args) >= 2 else False
        if count == 0:
            return {}

        if count < 0:  # Allow repetitions
            res = random.choices(sorted(key.value.items()), k=-count)
        else:  # Unique values from hash
            res = random.sample(sorted(key.value.items()), count)

        if withvalues:
            if self._client_info.protocol_version == 2:
                res = [item for t in res for item in t]
            else:
                res = [list(t) for t in res]
        else:
            res = [t[0] for t in res]
        return res

    def _hexpire(self, key: CommandItem, when_ms: int, *args: bytes) -> List[int]:
        # Deal with input arguments
        (nx, xx, gt, lt), left_args = extract_args(
            args, ("nx", "xx", "gt", "lt"), left_from_first_unexpected=True, error_on_unexpected=False
        )
        if (nx, xx, gt, lt).count(True) > 1:
            raise SimpleError(msgs.NX_XX_GT_LT_ERROR_MSG)
        fields = _get_fields(left_args)
        hash_val: Hash = key.value
        if hash_val is None:
            return [-2] * len(fields)
        # process command
        res = []
        for field in fields:
            if field not in hash_val:
                res.append(-2)
                continue
            current_expiration = hash_val.get_key_expireat(field)
            if (
                (nx and current_expiration is not None)
                or (xx and current_expiration is None)
                or (gt and (current_expiration is None or when_ms <= current_expiration))
                or (lt and current_expiration is not None and when_ms >= current_expiration)
            ):
                res.append(0)
                continue
            res.append(hash_val.set_key_expireat(field, when_ms))
        return res

    def _get_expireat(self, command: bytes, key: CommandItem, *args: bytes) -> List[int]:
        fields = _get_fields(args)
        hash_val: Hash = key.value
        if hash_val is None:
            return [-2] * len(fields)
        res = []
        for field in fields:
            if field not in hash_val:
                res.append(-2)
                continue
            when_ms = hash_val.get_key_expireat(field)
            if when_ms is None:
                res.append(-1)
            else:
                res.append(when_ms)
        return res

    @command(name="HEXPIRE", fixed=(Key(Hash), Int), repeat=(bytes,))
    def hexpire(self, key: CommandItem, seconds: int, *args: bytes) -> List[int]:
        when_ms = current_time() + seconds * 1000
        return self._hexpire(key, when_ms, *args)

    @command(name="HPEXPIRE", fixed=(Key(Hash), Int), repeat=(bytes,))
    def hpexpire(self, key: CommandItem, milliseconds: int, *args: bytes) -> List[int]:
        when_ms = current_time() + milliseconds
        return self._hexpire(key, when_ms, *args)

    @command(name="HEXPIREAT", fixed=(Key(Hash), Int), repeat=(bytes,))
    def hexpireat(self, key: CommandItem, unix_time_seconds: int, *args: bytes) -> List[int]:
        when_ms = unix_time_seconds * 1000
        return self._hexpire(key, when_ms, *args)

    @command(name="HPEXPIREAT", fixed=(Key(Hash), Int), repeat=(bytes,))
    def hpexpireat(self, key: CommandItem, unix_time_ms: int, *args: bytes) -> List[int]:
        return self._hexpire(key, unix_time_ms, *args)

    @command(name="HPERSIST", fixed=(Key(Hash),), repeat=(bytes,))
    def hpersist(self, key: CommandItem, *args: bytes) -> List[int]:
        fields = _get_fields(args)
        hash_val: Hash = key.value
        res = []
        for field in fields:
            if field not in hash_val:
                res.append(-2)
                continue
            if hash_val.clear_key_expireat(field):
                res.append(1)
            else:
                res.append(-1)
        return res

    @command(
        name="HEXPIRETIME", fixed=(Key(Hash),), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE, server_types=("redis",)
    )
    def hexpiretime(self, key: CommandItem, *args: bytes) -> List[int]:
        res = self._get_expireat(b"HEXPIRETIME", key, *args)
        return [(i // 1000 if i > 0 else i) for i in res]

    @command(name="HPEXPIRETIME", fixed=(Key(Hash),), repeat=(bytes,), server_types=("redis",))
    def hpexpiretime(self, key: CommandItem, *args: bytes) -> List[float]:
        res = self._get_expireat(b"HPEXPIRETIME", key, *args)
        return res

    @command(name="HTTL", fixed=(Key(Hash),), repeat=(bytes,), server_types=("redis",))
    def httl(self, key: CommandItem, *args: bytes) -> List[int]:
        curr_expireat_ms = self._get_expireat(b"HTTL", key, *args)
        curr_time_ms = current_time()
        return [((i - curr_time_ms) // 1000) if i > 0 else i for i in curr_expireat_ms]

    @command(name="HPTTL", fixed=(Key(Hash),), repeat=(bytes,), server_types=("redis",))
    def hpttl(self, key: CommandItem, *args: bytes) -> List[int]:
        curr_expireat_ms = self._get_expireat(b"HPTTL", key, *args)
        curr_time_ms = current_time()
        return [(i - curr_time_ms) if i > 0 else i for i in curr_expireat_ms]

    @command(name="HGETDEL", fixed=(Key(Hash),), repeat=(bytes,), server_types=("redis",))
    def hgetdel(self, key: CommandItem, *args: bytes) -> List[Any]:
        fields = _get_fields(args)
        hash_val: Hash = key.value
        res = [hash_val.pop(field) for field in fields]
        return res

    @command(name="HGETEX", fixed=(Key(Hash),), repeat=(bytes,), server_types=("redis",))
    def hgetex(self, key: CommandItem, *args: bytes) -> Any:
        (ex, px, exat, pxat, persist), left_args = extract_args(
            args,
            ("+ex", "+px", "+exat", "+pxat", "persist"),
            left_from_first_unexpected=True,
            error_on_unexpected=False,
        )
        if (ex is not None, px is not None, exat is not None, pxat is not None, persist).count(True) > 1:
            raise SimpleError("Only one of EX, PX, EXAT, PXAT or PERSIST arguments can be specified")
        fields = _get_fields(left_args)
        hash_val: Hash = key.value

        when_ms = _get_when_ms(ex, px, exat, pxat)
        res = []
        for field in fields:
            res.append(hash_val.get(field))
            if persist:
                hash_val.clear_key_expireat(field)
            elif when_ms is not None:
                hash_val.set_key_expireat(field, when_ms)
        return res

    @command(name="HSETEX", fixed=(Key(Hash),), repeat=(bytes,), server_types=("redis",))
    def hsetex(self, key: CommandItem, *args: bytes) -> Any:
        (ex, px, exat, pxat, keepttl, fnx, fxx), left_args = extract_args(
            args,
            ("+ex", "+px", "+exat", "+pxat", "keepttl", "fnx", "fxx"),
            left_from_first_unexpected=True,
            error_on_unexpected=False,
        )
        if (ex is not None, px is not None, exat is not None, pxat is not None, keepttl).count(True) > 1:
            raise SimpleError("Only one of EX, PX, EXAT, PXAT or KEEPTTL arguments can be specified")
        if (fnx, fxx).count(True) > 1:
            raise SimpleError("Only one of FNX or FXX arguments can be specified")
        field_vals = _get_fields(left_args, with_values=True)
        hash_val: Hash = key.value
        when_ms = _get_when_ms(ex, px, exat, pxat)

        field_keys = set(field_vals[::2])
        if fxx and len(field_keys - hash_val.getall().keys()) > 0:
            return 0
        if fnx and len(field_keys - hash_val.getall().keys()) < len(field_keys):
            return 0
        res = 0
        for i in range(0, len(field_vals), 2):
            field, value = field_vals[i], field_vals[i + 1]
            hash_val[field] = value
            res = 1
            if not keepttl and when_ms is not None:
                hash_val.set_key_expireat(field, when_ms)
        key.updated()
        return res


def _get_fields(args: Sequence[bytes], with_values: bool = False) -> Sequence[bytes]:
    if len(args) < 3 or not casematch(args[0], b"fields"):
        raise SimpleError(msgs.WRONG_ARGS_MSG6.format(command))
    num_fields = Int.decode(args[1])
    if not with_values and num_fields != len(args) - 2:
        raise SimpleError(msgs.HEXPIRE_NUMFIELDS_DIFFERENT)
    if with_values and num_fields * 2 != len(args) - 2:
        raise SimpleError(msgs.HEXPIRE_NUMFIELDS_DIFFERENT)
    fields = args[2:]
    return fields


def _get_when_ms(ex: Optional[int], px: Optional[int], exat: Optional[int], pxat: Optional[int]) -> Optional[int]:
    if ex is not None:
        when_ms = current_time() + ex * 1000
    elif px is not None:
        when_ms = current_time() + px
    elif exat is not None:
        when_ms = exat * 1000
    elif pxat is not None:
        when_ms = pxat
    else:
        when_ms = None
    return when_ms
