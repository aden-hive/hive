import inspect
import re
import threading
import time
import uuid
import weakref
from collections import defaultdict
from typing import Any, Set, Callable, Dict, Optional, Iterator, AnyStr, Type, MutableMapping

import redis


class SimpleString:
    def __init__(self, value: bytes) -> None:
        if not isinstance(value, bytes):
            raise TypeError("SimpleString value must be bytes")
        self.value = value

    @classmethod
    def decode(cls, value: bytes) -> bytes:
        return value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.value!r})"


class SimpleError(Exception):
    """Exception that will be turned into a frontend-specific exception."""

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("SimpleError value must be str")
        self.value = value


class NoResponse:
    """Returned by pub/sub commands to indicate that no response should be returned"""

    pass


OK = SimpleString(b"OK")
QUEUED = SimpleString(b"QUEUED")
BGSAVE_STARTED = SimpleString(b"Background saving started")


def current_time() -> int:
    """Return current_time in ms"""
    return int(time.time() * 1000)


def null_terminate(s: bytes) -> bytes:
    # Redis uses C functions on some strings, which means they stop at the
    # first NULL.
    ind = s.find(b"\0")
    if ind > -1:
        return s[:ind].lower()
    return s.lower()


def casematch(a: bytes, b: bytes) -> bool:
    return null_terminate(a) == null_terminate(b)


def decode_command_bytes(s: bytes) -> str:
    return s.decode(encoding="utf-8", errors="replace").lower()


def asbytes(value: AnyStr) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    return value


def compile_pattern(pattern_bytes: bytes) -> re.Pattern:  # type: ignore
    """Compile a glob pattern (e.g., for keys) to a `bytes` regex.

    `fnmatch.fnmatchcase` doesn't work for this because it uses different
    escaping rules to redis, uses ! instead of ^ to negate a character set,
    and handles invalid cases (such as a [ without a ]) differently. This
    implementation was written by studying the redis implementation.
    """
    # It's easier to work with text than bytes, because indexing bytes
    # doesn't behave the same in Python 3. Latin-1 will round-trip safely.
    pattern: str = pattern_bytes.decode(
        "latin-1",
    )
    parts = ["^"]
    i = 0
    pattern_len = len(pattern)
    while i < pattern_len:
        c = pattern[i]
        i += 1
        if c == "?":
            parts.append(".")
        elif c == "*":
            parts.append(".*")
        elif c == "\\":
            if i == pattern_len:
                i -= 1
            parts.append(re.escape(pattern[i]))
            i += 1
        elif c == "[":
            parts.append("[")
            if i < pattern_len and pattern[i] == "^":
                i += 1
                parts.append("^")
            parts_len = len(parts)  # To detect if anything was added
            while i < pattern_len:
                if pattern[i] == "\\" and i + 1 < pattern_len:
                    i += 1
                    parts.append(re.escape(pattern[i]))
                elif pattern[i] == "]":
                    i += 1
                    break
                elif i + 2 < pattern_len and pattern[i + 1] == "-":
                    start = pattern[i]
                    end = pattern[i + 2]
                    if start > end:
                        start, end = end, start
                    parts.append(re.escape(start) + "-" + re.escape(end))
                    i += 2
                else:
                    parts.append(re.escape(pattern[i]))
                i += 1
            if len(parts) == parts_len:
                if parts[-1] == "[":
                    # Empty group - will never match
                    parts[-1] = "(?:$.)"
                else:
                    # Negated empty group - matches any character
                    if parts[-1] != "^":
                        raise AssertionError("Invalid pattern")
                    parts.pop()
                    parts[-1] = "."
            else:
                parts.append("]")
        else:
            parts.append(re.escape(c))
    parts.append("\\Z")
    regex: bytes = "".join(parts).encode("latin-1")
    return re.compile(regex, flags=re.S)


class Database(MutableMapping):  # type: ignore
    def __init__(self, lock: Optional[threading.Lock], *args: Any, **kwargs: Any) -> None:
        self._dict: Dict[bytes, Any] = dict(*args, **kwargs)
        self.time = 0.0
        # key to the set of connections
        self._watches: Dict[bytes, weakref.WeakSet[Any]] = defaultdict(weakref.WeakSet)
        self.condition = threading.Condition(lock)
        self._change_callbacks: Set[Callable[[], None]] = set()

    def swap(self, other: "Database") -> None:
        self._dict, other._dict = other._dict, self._dict
        self.time, other.time = other.time, self.time

    def notify_watch(self, key: bytes) -> None:
        for sock in self._watches.get(key, set()):
            sock.notify_watch()
        self.condition.notify_all()
        for callback in self._change_callbacks:
            callback()

    def add_watch(self, key: bytes, sock: Any) -> None:
        self._watches[key].add(sock)

    def remove_watch(self, key: bytes, sock: Any) -> None:
        watches = self._watches[key]
        watches.discard(sock)
        if not watches:
            del self._watches[key]

    def add_change_callback(self, callback: Callable[[], None]) -> None:
        self._change_callbacks.add(callback)

    def remove_change_callback(self, callback: Callable[[], None]) -> None:
        self._change_callbacks.remove(callback)

    def clear(self) -> None:
        for key in self:
            self.notify_watch(key)
        self._dict.clear()

    def expired(self, item: Any) -> bool:
        return item.expireat is not None and item.expireat < self.time

    def _remove_expired(self) -> None:
        for key in list(self._dict):
            item = self._dict[key]
            if self.expired(item):
                del self._dict[key]

    def __getitem__(self, key: bytes) -> Any:
        item = self._dict[key]
        if self.expired(item):
            del self._dict[key]
            raise KeyError(key)
        return item

    def __setitem__(self, key: bytes, value: Any) -> None:
        self._dict[key] = value

    def __delitem__(self, key: bytes) -> None:
        del self._dict[key]

    def __iter__(self) -> Iterator[bytes]:
        self._remove_expired()
        return iter(self._dict)

    def __len__(self) -> int:
        self._remove_expired()
        return len(self._dict)

    def __hash__(self) -> int:
        return hash(super(object, self))

    def __eq__(self, other: object) -> bool:
        return super(object, self) == other


_VALID_RESPONSE_TYPES_RESP2 = (bytes, SimpleString, SimpleError, float, int, list)
_VALID_RESPONSE_TYPES_RESP3 = (bytes, SimpleString, SimpleError, float, int, list, dict, str)


def valid_response_type(value: Any, protocol_version: int, nested: bool = False) -> bool:
    if isinstance(value, NoResponse) and not nested:
        return True
    allowed_types = _VALID_RESPONSE_TYPES_RESP2 if protocol_version == 2 else _VALID_RESPONSE_TYPES_RESP3
    if value is not None and not isinstance(value, allowed_types):
        return False
    if isinstance(value, list):
        if any(not valid_response_type(item, protocol_version, True) for item in value):
            return False
    return True


class FakeSelector(object):
    def __init__(self, sock: Any):
        self.sock = sock

    def check_can_read(self, timeout: Optional[float]) -> bool:
        if self.sock.responses.qsize():
            return True
        if timeout is not None and timeout <= 0:
            return False

        # A sleep/poll loop is easier to mock out than messing with condition
        # variables.
        start = time.time()
        while True:
            if self.sock.responses.qsize():
                return True
            time.sleep(0.01)
            now = time.time()
            if timeout is not None and now > start + timeout:
                return False

    @staticmethod
    def check_is_ready_for_command(_: Any) -> bool:
        return True


def _get_args_to_warn() -> Set[str]:
    closure = redis.Redis.__init__.__closure__
    if closure is None:
        return set()
    for cell in closure:
        value = cell.cell_contents
        if isinstance(value, list) and len(value) > 0:
            return set(value)
    return set()


def convert_args_to_redis_init_kwargs(redis_class: Type[redis.Redis], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Interpret the positional and keyword arguments according to the version of redis in use"""
    parameters = list(inspect.signature(redis_class.__init__).parameters.values())[1:]
    args_to_warn = _get_args_to_warn()
    # Convert args => kwargs
    kwargs.update({parameters[i].name: args[i] for i in range(len(args))})
    kwargs.setdefault("host", uuid.uuid4().hex)
    kwds = {
        p.name: kwargs.get(p.name, p.default)
        for ind, p in enumerate(parameters)
        if p.default != inspect.Parameter.empty and (p.name not in args_to_warn or p.name in kwargs)
    }
    return kwds
