from typing import Iterable, Tuple, Optional, Any, Dict, AnyStr

from fakeredis import _msgs as msgs
from fakeredis._helpers import current_time, asbytes


class Hash:
    DECODE_ERROR = msgs.INVALID_HASH_MSG
    redis_type = b"hash"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._expirations: Dict[bytes, int] = {}
        self._values: Dict[bytes, bytes] = {}

    def _expire_keys(self) -> None:
        removed = []
        now = current_time()
        for k in self._expirations:
            if self._expirations[k] < now:
                self._values.pop(k, None)
                removed.append(k)
        for k in removed:
            self._expirations.pop(k, None)

    def set_key_expireat(self, key: AnyStr, when_ms: int) -> int:
        now = current_time()
        key_bytes = asbytes(key)
        if when_ms <= now:
            self._values.pop(key_bytes, None)
            self._expirations.pop(key_bytes, None)
            return 2
        self._expirations[key_bytes] = when_ms
        return 1

    def clear_key_expireat(self, key: AnyStr) -> bool:
        return self._expirations.pop(asbytes(key), None) is not None

    def get_key_expireat(self, key: AnyStr) -> Optional[int]:
        self._expire_keys()
        return self._expirations.get(asbytes(key), None)

    def __getitem__(self, key: AnyStr) -> Any:
        self._expire_keys()
        return self._values.get(asbytes(key))

    def __contains__(self, key: AnyStr) -> bool:
        self._expire_keys()
        return self._values.__contains__(asbytes(key))

    def __setitem__(self, key: AnyStr, value: Any) -> None:
        key_bytes = asbytes(key)
        self._expirations.pop(key_bytes, None)
        self._values[key_bytes] = value

    def __delitem__(self, key: AnyStr) -> None:
        key_bytes = asbytes(key)
        self._values.pop(key_bytes, None)
        self._expirations.pop(key_bytes, None)

    def __len__(self) -> int:
        self._expire_keys()
        return len(self._values)

    def __iter__(self) -> Iterable[str]:
        self._expire_keys()
        for k in self._values.keys():
            if isinstance(k, bytes):
                yield k.decode("utf-8")
            else:
                yield k

    def get(self, key: AnyStr, default: Any = None) -> Any:
        self._expire_keys()
        return self._values.get(asbytes(key), default)

    def keys(self) -> Iterable[bytes]:
        self._expire_keys()
        return [asbytes(k) for k in self._values.keys()]

    def values(self) -> Iterable[Any]:
        return [v for k, v in self.items()]

    def items(self) -> Iterable[Tuple[bytes, Any]]:
        self._expire_keys()
        return [(asbytes(k), asbytes(v)) for k, v in self._values.items()]

    def update(self, values: Dict[bytes, Any], clear_expiration: bool) -> None:
        self._expire_keys()
        if clear_expiration:
            for k, v in values.items():
                self.clear_key_expireat(k)
        for k, v in values.items():
            self._values[asbytes(k)] = v

    def getall(self) -> Dict[bytes, bytes]:
        self._expire_keys()
        res = self._values.copy()
        return {asbytes(k): asbytes(v) for k, v in res.items()}

    def pop(self, key: AnyStr, d: Any = None) -> Any:
        self._expire_keys()
        return self._values.pop(asbytes(key), d)
