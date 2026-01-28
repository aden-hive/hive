from typing import Iterable, Optional, Any, Dict, Union, Set

from fakeredis import _msgs as msgs
from fakeredis._helpers import current_time
from fakeredis._typing import Self


class ExpiringMembersSet:
    DECODE_ERROR = msgs.INVALID_HASH_MSG
    redis_type = b"set"

    def __init__(self, values: Optional[Dict[bytes, Optional[int]]] = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._values: Dict[bytes, Optional[int]] = values or {}

    def _expire_members(self) -> None:
        now = current_time()
        removed = [k for k in self._values if (self._values[k] or (now + 1)) < now]
        for k in removed:
            self._values.pop(k)

    def set_member_expireat(self, key: bytes, when_ms: int) -> int:
        now = current_time()
        if when_ms <= now:
            self._values.pop(key, None)
            return 2
        self._values[key] = when_ms
        return 1

    def clear_key_expireat(self, key: bytes) -> bool:
        return self._values.pop(key, None) is not None

    def get_key_expireat(self, key: bytes) -> Optional[int]:
        self._expire_members()
        return self._values.get(key, None)

    def __contains__(self, key: bytes) -> bool:
        self._expire_members()
        return self._values.__contains__(key)

    def __delitem__(self, key: bytes) -> None:
        self._values.pop(key, None)

    def __len__(self) -> int:
        self._expire_members()
        return len(self._values)

    def __iter__(self) -> Iterable[bytes]:
        self._expire_members()
        now = current_time()
        return iter({k for k in self._values if (self._values[k] or (now + 1)) >= now})

    def __get__(self, instance: object, owner: None = None) -> Set[bytes]:
        self._expire_members()
        return set(self._values.keys())

    def __sub__(self, other: Self) -> "ExpiringMembersSet":
        self._expire_members()
        other._expire_members()
        return ExpiringMembersSet({k: v for k, v in self._values.items() if k not in other._values})

    def __and__(self, other: Self) -> "ExpiringMembersSet":
        self._expire_members()
        other._expire_members()
        return ExpiringMembersSet({k: v for k, v in self._values.items() if k in other._values})

    def __or__(self, other: Self) -> "ExpiringMembersSet":
        self._expire_members()
        other._expire_members()
        return ExpiringMembersSet(dict(self._values.items())).update(other)

    def update(self, other: Union[Self, Iterable[bytes]]) -> Self:
        self._expire_members()
        if isinstance(other, ExpiringMembersSet):
            self._values.update(other._values)
            return self
        for value in other:
            self._values[value] = None
        return self

    def discard(self, key: bytes) -> None:
        self._values.pop(key, None)

    def remove(self, key: bytes) -> None:
        self._values.pop(key)

    def add(self, key: bytes) -> None:
        self._values[key] = None

    def copy(self) -> "ExpiringMembersSet":
        return ExpiringMembersSet(self._values.copy())
