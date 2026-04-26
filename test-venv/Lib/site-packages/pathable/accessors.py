"""Pathable accessors module"""

import stat
from collections import OrderedDict
from collections.abc import Hashable
from collections.abc import Mapping
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from typing import Generic
from typing import TypeVar

from pathable.protocols import Subscriptable
from pathable.types import LookupKey
from pathable.types import LookupNode
from pathable.types import LookupValue

K = TypeVar("K", bound=Hashable, contravariant=True)
V = TypeVar("V", covariant=True)
N = TypeVar("N")
SK = TypeVar("SK", bound=Hashable, contravariant=True)
SV = TypeVar("SV", covariant=True)
CSK = TypeVar("CSK", bound=Hashable, contravariant=True)
CSV = TypeVar("CSV", covariant=True)


class NodeAccessor(Generic[N, K, V]):
    """Node accessor."""

    def __init__(self, node: N):
        self._node = node

    @property
    def node(self) -> N:
        return self._node

    def __getitem__(self, parts: Sequence[K]) -> N:
        return self._get_node(self.node, parts)

    def __eq__(self, other: object) -> Any:
        if not isinstance(other, NodeAccessor):
            return NotImplemented
        return self.node == other.node

    def stat(self, parts: Sequence[K]) -> dict[str, Any] | None:
        raise NotImplementedError

    def keys(self, parts: Sequence[K]) -> Sequence[K]:
        """Return the keys of the node at `parts` if it is traversable, or raise `KeyError` if not.

        This performs a segment-by-segment traversal and raises `KeyError` with the failing segment if any part is missing or non-traversable.
        """
        raise NotImplementedError

    def is_traversable(self, parts: Sequence[K]) -> bool:
        """Return True if the node at `parts` can enumerate child keys.

        This is intended for control-flow ("can I call keys()/len()/iterate?")
        and must not raise for missing or non-traversable paths, but may raise
        OSError for permission or I/O errors.

        The default implementation attempts a cheap node inspection via
        `_is_traversable_node` after traversing to the node. If that is not
        implemented, it falls back to calling `keys()`.

        Note: the fallback may be expensive for accessors where `keys()`
        enumerates large containers.
        """
        try:
            node = self[parts]
        except KeyError:
            return False
        except NotImplementedError:
            try:
                self.keys(parts)
            except (KeyError, IndexError, TypeError, NotImplementedError):
                return False
            return True

        try:
            return self._is_traversable_node(node)
        except NotImplementedError:
            try:
                self.keys(parts)
            except (KeyError, IndexError, TypeError, NotImplementedError):
                return False
            return True

    def contains(self, parts: Sequence[K], key: K) -> bool:
        """Return True if `key` is a valid child of the node at `parts`.

        The default implementation tries to validate membership by traversing
        a single step (fast for accessors that implement `_get_subnode`). If
        traversal isn't available, it falls back to `keys()` for compatibility
        with accessors that only define enumeration.

        This method is intended to be used for membership checks (e.g. `key in
        path`) where errors should not be raised.
        """
        try:
            parent = self[parts]
            try:
                self._get_subnode(parent, key)
            except (KeyError, IndexError, TypeError):
                return False
            return True
        except KeyError:
            return False
        except NotImplementedError:
            try:
                return key in self.keys(parts)
            except (KeyError, IndexError, TypeError):
                return False

    def require_child(self, parts: Sequence[K], key: K) -> None:
        """Assert that `key` is a valid child of the node at `parts`.

        Raises `KeyError` with stable diagnostics.
        """
        try:
            # Validate the parent first to preserve intermediate segment
            # diagnostics.
            parent = self[parts]
            try:
                self._get_subnode(parent, key)
                return
            except KeyError as exc:
                raise KeyError(key) from exc
        except NotImplementedError:
            keys = self.keys(parts)
            if key not in keys:
                raise KeyError(key)

    def len(self, parts: Sequence[K]) -> int:
        raise NotImplementedError

    def read(self, parts: Sequence[K]) -> V:
        node = self[parts]
        return self._read_node(node)

    def validate(self, parts: Sequence[K]) -> None:
        """Validate that the node at `parts` exists.

        This performs a traversal only and raises `KeyError` (with the failing
        part when available) if the path is missing or non-traversable.
        """
        self[parts]

    @classmethod
    def _is_traversable_node(cls, node: N) -> bool:
        raise NotImplementedError

    @classmethod
    def _get_node(cls, node: N, parts: Sequence[K]) -> N:
        current = node
        get_subnode = cls._get_subnode
        for part in parts:
            current = get_subnode(current, part)
        return current

    @classmethod
    def _read_node(cls, node: N) -> V:
        raise NotImplementedError

    @classmethod
    def _get_subnode(cls, node: N, part: K) -> N:
        raise NotImplementedError


class PathAccessor(NodeAccessor[Path, str, bytes]):

    def stat(self, parts: Sequence[str]) -> dict[str, Any] | None:
        subpath = self.node.joinpath(*parts)
        try:
            stat = subpath.stat(follow_symlinks=False)
        except OSError:
            return None
        return {
            key: getattr(stat, key)
            for key in dir(stat)
            if key.startswith("st_")
        }

    def keys(self, parts: Sequence[str]) -> Sequence[str]:
        # Traverse using `get()` so missing intermediate segments are
        # reported by `_get_subnode()` with the first failing part.
        subpath = self[parts]
        try:
            return [path.name for path in subpath.iterdir()]
        except (FileNotFoundError, NotADirectoryError) as exc:
            if parts:
                raise KeyError(parts[-1]) from exc
            raise KeyError from exc

    @classmethod
    def _is_traversable_node(cls, node: Path) -> bool:
        # Avoid following symlinks for consistency with stat()
        # Use lstat to check the symlink itself, not its target
        try:
            return stat.S_ISDIR(node.lstat().st_mode)
        except OSError:
            return False

    def contains(self, parts: Sequence[str], key: str) -> bool:
        try:
            subpath = self[parts]
        except KeyError:
            return False
        return (subpath / key).exists()

    def require_child(self, parts: Sequence[str], key: str) -> None:
        subpath = self[parts]
        if not subpath.is_dir():
            if parts:
                raise KeyError(parts[-1])
            raise KeyError
        child = subpath / key
        if not child.exists():
            raise KeyError(key)

    def len(self, parts: Sequence[str]) -> int:
        # Traverse using `get()` so missing intermediate segments are
        # reported by `_get_subnode()` with the first failing part.
        subpath = self[parts]
        try:
            return sum(1 for _ in subpath.iterdir())
        except (FileNotFoundError, NotADirectoryError) as exc:
            if parts:
                raise KeyError(parts[-1]) from exc
            raise KeyError from exc

    def read(self, parts: Sequence[str]) -> bytes:
        node = self[parts]
        return self._read_node(node)

    @classmethod
    def _read_node(cls, node: Path) -> bytes:
        return node.read_bytes()

    @classmethod
    def _get_subnode(cls, node: Path, part: str) -> Path:
        subnode = node / part
        if not subnode.exists():
            raise KeyError(part)
        return subnode


class SubscriptableAccessor(
    NodeAccessor[Subscriptable[SK, SV] | SV, SK, SV], Generic[SK, SV]
):
    """Accessor for subscriptable content."""

    @classmethod
    def _get_subnode(
        cls, node: Subscriptable[SK, SV] | SV, part: SK
    ) -> Subscriptable[SK, SV] | SV:
        if not isinstance(node, Subscriptable):
            raise KeyError(part)
        try:
            return node[part]
        except (KeyError, IndexError, TypeError) as exc:
            raise KeyError(part) from exc


class CachedSubscriptableAccessor(
    SubscriptableAccessor[CSK, CSV], Generic[CSK, CSV]
):
    def __init__(self, node: Subscriptable[CSK, CSV] | CSV):
        super().__init__(node)

        # Per-instance cache: avoids global strong references and id-reuse hazards.
        # Default maxsize matches functools.lru_cache default (128).
        self._cache_enabled = True
        self._cache_maxsize: int | None = 128
        self._cache: OrderedDict[tuple[CSK, ...], CSV] = OrderedDict()

    def clear_cache(self) -> None:
        """Clear any cached reads for this accessor instance."""
        self._cache.clear()

    def disable_cache(self) -> None:
        """Disable caching for this accessor instance."""
        self._cache_enabled = False
        self._cache.clear()

    def enable_cache(self, *, maxsize: int | None = 128) -> None:
        """Enable caching for this accessor instance.

        Args:
            maxsize: Maximum number of distinct paths to cache.
                - 128 by default (matches functools.lru_cache)
                - None for unbounded
                - 0 to disable caching
        """
        self._cache_enabled = True
        self._cache_maxsize = maxsize
        self._cache.clear()

    def read(self, parts: Sequence[CSK]) -> CSV:
        key = tuple(parts)
        if (not self._cache_enabled) or self._cache_maxsize == 0:
            node = self[parts]
            return self._read_node(node)

        try:
            value = self._cache[key]
        except KeyError:
            node = self[parts]
            value = self._read_node(node)
            self._cache[key] = value
        else:
            # Mark as recently used.
            self._cache.move_to_end(key)
            return value

        # Enforce max size (LRU eviction).
        if self._cache_maxsize is not None:
            while len(self._cache) > self._cache_maxsize:
                self._cache.popitem(last=False)

        return value


class LookupAccessor(CachedSubscriptableAccessor[LookupKey, LookupValue]):

    @classmethod
    def _is_traversable_node(cls, node: LookupNode) -> bool:
        return isinstance(node, Mapping | list)

    def stat(self, parts: Sequence[LookupKey]) -> dict[str, Any] | None:
        try:
            node = self[parts]
        except KeyError:
            return None

        length: int | None
        match node:
            case Mapping() | list():
                length = len(node)
            case _:
                try:
                    length = len(node)
                except TypeError:
                    length = None

        return {
            "type": type(node).__name__,
            "length": length,
        }

    def contains(self, parts: Sequence[LookupKey], key: LookupKey) -> bool:
        try:
            node = self[parts]
        except KeyError:
            return False

        match node:
            case Mapping():
                return key in node
            case list() as items:
                return isinstance(key, int) and 0 <= key < len(items)
            case _:
                return False

    def require_child(
        self, parts: Sequence[LookupKey], key: LookupKey
    ) -> None:
        # Validate parent path for intermediate diagnostics.
        node = self[parts]

        match node:
            case Mapping():
                if key not in node:
                    raise KeyError(key)
                return
            case list() as items:
                if not (isinstance(key, int) and 0 <= key < len(items)):
                    raise KeyError(key)
                return
            case _:
                raise KeyError(key)

    def keys(self, parts: Sequence[LookupKey]) -> Sequence[LookupKey]:
        node = self[parts]
        match node:
            case Mapping():
                return list(node.keys())
            case list() as items:
                return list(range(len(items)))
        # Non-traversable leaf.
        if parts:
            raise KeyError(parts[-1])
        raise KeyError

    def len(self, parts: Sequence[LookupKey]) -> int:
        node = self[parts]
        # Define length as the number of child paths (consistent with keys()).
        if self._is_traversable_node(node):
            return len(node)
        # Non-traversable leaf.
        if parts:
            raise KeyError(parts[-1])
        raise KeyError

    @classmethod
    def _read_node(cls, node: LookupNode) -> LookupValue:
        return node
