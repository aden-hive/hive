"""
Helper classes and methods used in mixins implementing various commands.
Unlike _helpers.py, here the methods should be used only in mixins.
"""

import functools
import math
import re
import sys
import time
from typing import Tuple, Union, Optional, Any, Type, List, Callable, Sequence, Dict, Set, Collection

from . import _msgs as msgs
from ._helpers import null_terminate, SimpleError, Database
from ._typing import VersionType, ServerType

MAX_STRING_SIZE = 512 * 1024 * 1024
SUPPORTED_COMMANDS: Dict[str, "Signature"] = {}  # Dictionary of supported commands name => Signature
COMMANDS_WITH_SUB: Set[str] = set()  # Commands with sub-commands


class Key:
    """Marker to indicate that argument in signature is a key"""

    UNSPECIFIED = object()

    def __init__(self, type_: Optional[Type[Any]] = None, missing_return: Any = UNSPECIFIED) -> None:
        self.type_ = type_
        self.missing_return = missing_return


class Item:
    """An item stored in the database"""

    __slots__ = ["value", "expireat"]

    def __init__(self, value: Any) -> None:
        self.value = value
        self.expireat = None


class CommandItem:
    """An item referenced by a command.

    It wraps an Item but has extra fields to manage updates and notifications.
    """

    def __init__(self, key: bytes, db: Database, item: Optional["CommandItem"] = None, default: Any = None) -> None:
        self._expireat: Optional[float]
        if item is None:
            self._value = default
            self._expireat = None
        else:
            self._value = item.value
            self._expireat = item.expireat
        self.key = key
        self.db = db
        self._modified = False
        self._expireat_modified = False

    @property
    def value(self) -> Any:
        return self._value

    @value.setter
    def value(self, new_value: Any) -> None:
        self._value = new_value
        self._modified = True
        self.expireat = None

    @property
    def expireat(self) -> Optional[float]:
        return self._expireat

    @expireat.setter
    def expireat(self, value: Optional[float]) -> None:
        self._expireat = value
        self._expireat_modified = True
        self._modified = True  # Since redis 6.0.7

    def get(self, default: Any) -> Any:
        return self._value if self else default

    def update(self, new_value: Any) -> None:
        self._value = new_value
        self._modified = True

    def updated(self) -> None:
        self._modified = True

    def writeback(self, remove_empty_val: bool = True) -> None:
        if self._modified:
            self.db.notify_watch(self.key)
            if not isinstance(self.value, bytes) and (self.value is None or (not self.value and remove_empty_val)):
                self.db.pop(self.key, None)
                return
            item = self.db.setdefault(self.key, Item(None))
            item.value = self.value
            item.expireat = self.expireat
            return

        if self._expireat_modified and self.key in self.db:
            self.db[self.key].expireat = self.expireat

    def __bool__(self) -> bool:
        return bool(self._value) or isinstance(self._value, bytes)

    __nonzero__ = __bool__  # For Python 2


class RedisType:
    @classmethod
    def decode(cls, *args, **kwargs):  # type:ignore
        raise NotImplementedError


class Int(RedisType):
    """Argument converter for 64-bit signed integers"""

    DECODE_ERROR = msgs.INVALID_INT_MSG
    ENCODE_ERROR = msgs.OVERFLOW_MSG
    MIN_VALUE = -(2**63)
    MAX_VALUE = 2**63 - 1

    @classmethod
    def valid(cls, value: int) -> bool:
        return cls.MIN_VALUE <= value <= cls.MAX_VALUE

    @classmethod
    def decode(cls, value: bytes, decode_error: Optional[str] = None) -> int:
        try:
            out = int(value)
            if not cls.valid(out) or str(out).encode() != value:
                raise ValueError
            return out
        except ValueError:
            raise SimpleError(decode_error or cls.DECODE_ERROR)

    @classmethod
    def encode(cls, value: int) -> bytes:
        if cls.valid(value):
            return str(value).encode()
        else:
            raise SimpleError(cls.ENCODE_ERROR)


class DbIndex(Int):
    """Argument converter for database indices"""

    DECODE_ERROR = msgs.INVALID_DB_MSG
    MIN_VALUE = 0
    MAX_VALUE = 15


class BitOffset(Int):
    """Argument converter for unsigned bit positions"""

    DECODE_ERROR = msgs.INVALID_BIT_OFFSET_MSG
    MIN_VALUE = 0
    MAX_VALUE = 8 * MAX_STRING_SIZE - 1  # Redis imposes 512MB limit on keys


class BitValue(Int):
    DECODE_ERROR = msgs.INVALID_BIT_VALUE_MSG
    MIN_VALUE = 0
    MAX_VALUE = 1


class Float(RedisType):
    """Argument converter for floating-point values.

    Redis uses long double for some cases (INCRBYFLOAT, HINCRBYFLOAT)
    and double for others (zset scores), but Python doesn't support
    `long double`.
    """

    DECODE_ERROR = msgs.INVALID_FLOAT_MSG

    @classmethod
    def decode(
        cls,
        value: bytes,
        allow_leading_whitespace: bool = False,
        allow_erange: bool = False,
        allow_empty: bool = False,
        crop_null: bool = False,
        decode_error: Optional[str] = None,
    ) -> float:
        # Redis has some quirks in float parsing, with several variants.
        # See https://github.com/antirez/redis/issues/5706
        try:
            if crop_null:
                value = null_terminate(value)
            if allow_empty and value == b"":
                value = b"0.0"
            if not allow_leading_whitespace and value[:1].isspace():
                raise ValueError
            if value[-1:].isspace():
                raise ValueError
            out = float(value)
            if math.isnan(out):
                raise ValueError
            if not allow_erange:
                # Values that over- or under-flow are explicitly rejected by
                # redis. This is a crude hack to determine whether the input
                # may have been such a value.
                if out in (math.inf, -math.inf, 0.0) and re.match(b"^[^a-zA-Z]*[1-9]", value):
                    raise ValueError
            return out
        except ValueError:
            raise SimpleError(decode_error or cls.DECODE_ERROR)

    @classmethod
    def encode(cls, value: float, humanfriendly: bool) -> bytes:
        if math.isinf(value):
            return str(value).encode()
        elif humanfriendly:
            # Algorithm from `ld2string` in redis
            out = "{:.17f}".format(value)
            out = re.sub(r"\.?0+$", "", out)
            return out.encode()
        else:
            return "{:.17g}".format(value).encode()


class Timeout(Float):
    """Argument converter for timeouts"""

    DECODE_ERROR = msgs.TIMEOUT_NEGATIVE_MSG
    MIN_VALUE = 0.0


class SortFloat(Float):
    DECODE_ERROR = msgs.INVALID_SORT_FLOAT_MSG

    @classmethod
    def decode(
        cls,
        value: bytes,
        allow_leading_whitespace: bool = True,
        allow_erange: bool = False,
        allow_empty: bool = True,
        crop_null: bool = True,
        decode_error: Optional[str] = None,
    ) -> float:
        return super().decode(value, allow_leading_whitespace=True, allow_empty=True, crop_null=True)


@functools.total_ordering
class BeforeAny:
    def __gt__(self, other: Any) -> bool:
        return False

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, BeforeAny)

    def __hash__(self) -> int:
        return 1


@functools.total_ordering
class AfterAny:
    def __lt__(self, other: Any) -> bool:
        return False

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, AfterAny)

    def __hash__(self) -> int:
        return 1


class ScoreTest(RedisType):
    """Argument converter for sorted set score endpoints."""

    def __init__(self, value: float, exclusive: bool = False, bytes_val: Optional[bytes] = None):
        self.value = value
        self.exclusive = exclusive
        self.bytes_val = bytes_val

    @classmethod
    def decode(cls, value: bytes) -> "ScoreTest":
        try:
            original_value = value
            exclusive = False
            if value[:1] == b"(":
                exclusive = True
                value = value[1:]
            fvalue = Float.decode(
                value,
                allow_leading_whitespace=True,
                allow_erange=True,
                allow_empty=True,
                crop_null=True,
            )
            return cls(fvalue, exclusive, original_value)
        except SimpleError:
            raise SimpleError(msgs.INVALID_MIN_MAX_FLOAT_MSG)

    def __str__(self) -> str:
        if self.exclusive:
            return "({!r}".format(self.value)
        else:
            return repr(self.value)

    @property
    def lower_bound(self) -> Tuple[float, Union[AfterAny, BeforeAny]]:
        return self.value, AfterAny() if self.exclusive else BeforeAny()

    @property
    def upper_bound(self) -> Tuple[float, Union[AfterAny, BeforeAny]]:
        return self.value, BeforeAny() if self.exclusive else AfterAny()


class StringTest(RedisType):
    """Argument converter for sorted set LEX endpoints."""

    def __init__(self, value: Union[bytes, BeforeAny, AfterAny], exclusive: bool):
        self.value = value
        self.exclusive = exclusive

    @classmethod
    def decode(cls, value: bytes) -> "StringTest":
        if value == b"-":
            return cls(BeforeAny(), True)
        elif value == b"+":
            return cls(AfterAny(), True)
        elif value[:1] == b"(":
            return cls(value[1:], True)
        elif value[:1] == b"[":
            return cls(value[1:], False)
        else:
            raise SimpleError(msgs.INVALID_MIN_MAX_STR_MSG)

    # def to_scoretest(self, zset: ZSet) -> ScoreTest:
    #     if isinstance(self.value, BeforeAny):
    #         return ScoreTest(float("-inf"), False)
    #     if isinstance(self.value, AfterAny):
    #         return ScoreTest(float("inf"), False)
    #     val: float = zset.get(self.value, None)
    #     return ScoreTest(val, self.exclusive)


class Signature:
    def __init__(
        self,
        name: str,
        func_name: str,
        fixed: Tuple[Type[Union[RedisType, bytes]]],
        repeat: Tuple[Type[Union[RedisType, bytes]]] = (),  # type:ignore
        args: Tuple[str] = (),  # type:ignore
        flags: str = "",
        server_types: Collection[ServerType] = (
            "redis",
            "valkey",
            "dragonfly",
        ),  # supported server types: redis, dragonfly, valkey
    ):
        self.name = name
        self.func_name = func_name
        self.fixed = fixed
        self.repeat = repeat
        self.flags = set(flags)
        self.command_args = args
        self.server_types: Set[ServerType] = set(server_types)

    def check_arity(self, args: Sequence[Any], version: VersionType) -> None:
        if len(args) == len(self.fixed):
            return
        delta = len(args) - len(self.fixed)
        if delta < 0 or not self.repeat:
            msg = msgs.WRONG_ARGS_MSG6.format(self.name)
            raise SimpleError(msg)
        if delta % len(self.repeat) != 0:
            msg = msgs.WRONG_ARGS_MSG7 if version >= (7,) else msgs.WRONG_ARGS_MSG6.format(self.name)
            raise SimpleError(msg)

    def apply(
        self, args: Sequence[Any], db: Database, version: VersionType
    ) -> Union[Tuple[Any], Tuple[List[Any], List[CommandItem]]]:
        """Returns a tuple, which is either:
        - transformed args and a dict of CommandItems; or
        - a single containing a short-circuit return value
        """
        self.check_arity(args, version)

        types = list(self.fixed)
        types.extend([self.repeat[i % len(self.repeat)] for i in range(len(args) - len(types))])

        args_list = list(args)
        # First pass: convert/validate non-keys, and short-circuit on missing keys
        for i, (arg, type_) in enumerate(zip(args_list, types)):
            if isinstance(type_, Key):
                if type_.missing_return is not Key.UNSPECIFIED and arg not in db:
                    return (type_.missing_return,)
            elif type_ is not bytes:
                args_list[i] = type_.decode(
                    args_list[i],
                )

        # Second pass: read keys and check their types
        command_items: List[CommandItem] = []
        for i, (arg, type_) in enumerate(zip(args_list, types)):
            if isinstance(type_, Key):
                item = db.get(arg)
                default = None
                if type_.type_ is not None and item is not None and type(item.value) is not type_.type_:
                    raise SimpleError(msgs.WRONGTYPE_MSG)
                if (
                    msgs.FLAG_DO_NOT_CREATE not in self.flags
                    and type_.type_ is not None
                    and item is None
                    and type_.type_ is not bytes
                ):
                    default = type_.type_()
                args_list[i] = CommandItem(arg, db, item, default=default)
                command_items.append(args_list[i])

        return args_list, command_items


def command(*args, **kwargs) -> Callable:  # type:ignore
    def create_signature(func: Callable[..., Any], cmd_name: str) -> None:
        if " " in cmd_name:
            COMMANDS_WITH_SUB.add(cmd_name.split(" ")[0])
        SUPPORTED_COMMANDS[cmd_name] = Signature(cmd_name, func.__name__, *args, **kwargs)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        cmd_names = kwargs.pop("name", func.__name__)
        if isinstance(cmd_names, list):  # Support for alias commands
            for cmd_name in cmd_names:
                create_signature(func, cmd_name.lower())
        elif isinstance(cmd_names, str):
            create_signature(func, cmd_names.lower())
        else:
            raise ValueError("command name should be a string or list of strings")
        return func

    return decorator


def delete_keys(*keys: CommandItem) -> int:
    ans = 0
    done = set()
    for key in keys:
        if key and key.key not in done:
            key.value = None
            done.add(key.key)
            ans += 1
    return ans


def fix_range(start: int, end: int, length: int) -> Tuple[int, int]:
    # Redis handles negative slightly differently for zrange
    if start < 0:
        start = max(0, start + length)
    if end < 0:
        end += length
    if start > end or start >= length:
        return -1, -1
    end = min(end, length - 1)
    return start, end + 1


def fix_range_string(start: int, end: int, length: int) -> Tuple[int, int]:
    # Negative number handling is based on the redis source code
    if 0 > start > end and end < 0:
        return -1, -1
    if start < 0:
        start = max(0, start + length)
    if end < 0:
        end = max(0, end + length)
    end = min(end, length - 1)
    return start, end + 1


class Timestamp(Int):
    """Argument converter for timestamps"""

    @classmethod
    def decode(cls, value: bytes, decode_error: Optional[str] = None) -> int:
        if value == b"*":
            return int(time.time() * 1000)
        if value == b"-":
            return -1
        if value == b"+":
            return sys.maxsize
        return super().decode(value, decode_error=msgs.INVALID_EXPIRE_MSG)
