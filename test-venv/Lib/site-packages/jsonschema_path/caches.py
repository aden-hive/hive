"""JSONSchema path caches module."""

from collections import OrderedDict
from collections.abc import Sequence

from pathable.types import LookupKey
from pathable.types import LookupNode
from referencing._core import Resolved


class FullPathResolvedCache:
    def __init__(self, maxsize: int):
        self._maxsize = maxsize
        self._generation = 0
        self._cache: OrderedDict[
            tuple[tuple[LookupKey, ...], int],
            Resolved[LookupNode],
        ] = OrderedDict()

    def _make_key(
        self,
        parts: Sequence[LookupKey],
    ) -> tuple[tuple[LookupKey, ...], int] | None:
        if self._maxsize <= 0:
            return None

        parts_tuple = tuple(parts)
        try:
            hash(parts_tuple)
        except TypeError:
            return None

        return (parts_tuple, self._generation)

    def get(
        self,
        parts: Sequence[LookupKey],
    ) -> Resolved[LookupNode] | None:
        key = self._make_key(parts)
        if key is None:
            return None

        cached = self._cache.get(key)
        if cached is None:
            return None

        self._cache.move_to_end(key)
        return cached

    def set(
        self,
        parts: Sequence[LookupKey],
        resolved: Resolved[LookupNode],
    ) -> None:
        key = self._make_key(parts)
        if key is None:
            return

        self._cache[key] = resolved
        self._cache.move_to_end(key)
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

    def invalidate(self) -> None:
        self._generation += 1
        self._cache.clear()


class PrefixResolvedCache:
    def __init__(self) -> None:
        self._cache: dict[tuple[LookupKey, ...], Resolved[LookupNode]] = {}

    def seed_root(self, resolved: Resolved[LookupNode]) -> None:
        self._cache[()] = resolved

    def longest_prefix_hit(
        self,
        parts: tuple[LookupKey, ...],
    ) -> tuple[int, Resolved[LookupNode]] | None:
        for idx in range(len(parts) - 1, -1, -1):
            prefix = parts[:idx]
            try:
                cached = self._cache.get(prefix)
            except TypeError:
                continue

            if cached is not None:
                return idx, cached

        return None

    def store_intermediate(
        self,
        parts: tuple[LookupKey, ...],
        index: int,
        resolved: Resolved[LookupNode],
    ) -> None:
        if index >= len(parts) - 1:
            return

        prefix = parts[: index + 1]
        try:
            self._cache[prefix] = resolved
        except TypeError:
            pass

    def invalidate(self) -> None:
        self._cache.clear()
