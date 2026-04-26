"""Pathable paths module"""

import os
from collections.abc import Hashable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any
from typing import Generic
from typing import Sequence
from typing import TypeVar
from typing import cast
from typing import overload

from pathable.accessors import K
from pathable.accessors import LookupAccessor
from pathable.accessors import N
from pathable.accessors import NodeAccessor
from pathable.accessors import PathAccessor
from pathable.accessors import V
from pathable.parsers import SEPARATOR
from pathable.parsers import parse_parts
from pathable.types import LookupKey
from pathable.types import LookupNode
from pathable.types import LookupValue

# Python 3.11+ shortcut: typing.Self
TBasePath = TypeVar("TBasePath", bound="BasePath")
TAccessorPath = TypeVar("TAccessorPath", bound="AccessorPath[Any, Any, Any]")
TDefault = TypeVar("TDefault")


@dataclass(frozen=True, init=False)
class BasePath:
    """Base path."""

    parts: tuple[Hashable, ...]
    separator: str = SEPARATOR

    def __init__(self, *args: Any, separator: str | None = None):
        object.__setattr__(self, "separator", separator or self.separator)
        parts = self._parse_args(args, sep=self.separator)
        object.__setattr__(self, "parts", parts)

    @classmethod
    def _parse_args(
        cls,
        args: Sequence[Any],
        sep: str = SEPARATOR,
    ) -> tuple[Hashable, ...]:
        """Parse constructor arguments into canonical parts.

        Subclasses may override this class method to customize parsing rules
        (e.g. accepted part types) while preserving the public constructor
        behavior.
        """
        parts: list[Hashable] = []
        append = parts.append
        extend = parts.extend

        for arg in args:
            part: Any = arg

            if isinstance(part, cls):
                extend(part.parts)
                continue

            if isinstance(part, bytes):
                append(part.decode("ascii"))
                continue

            if isinstance(part, os.PathLike):
                part = os.fspath(part)
                if isinstance(part, bytes):
                    append(part.decode("ascii"))
                    continue

            if isinstance(part, (str, int)):
                append(part)
                continue

            if isinstance(part, Hashable):
                append(part)
                continue

            raise TypeError(
                "argument must be Hashable, bytes, os.PathLike, or BasePath; got %r"
                % (type(part),)
            )
        return tuple(parse_parts(parts, sep))

    @classmethod
    def _from_parts(
        cls: type[TBasePath],
        args: Sequence[Any],
        separator: str | None = None,
    ) -> TBasePath:
        return cls(*args, separator=separator)

    @classmethod
    def _from_parsed_parts(
        cls: type[TBasePath],
        parts: tuple[Hashable, ...],
        separator: str | None = None,
    ) -> "TBasePath":
        instance = cls.__new__(cls)
        object.__setattr__(instance, "parts", parts)
        object.__setattr__(
            instance, "separator", separator or instance.separator
        )
        return instance

    @cached_property
    def _cparts(self) -> tuple[str, ...]:
        # Cached stringified parts for display.
        return tuple(str(p) for p in self.parts)

    @cached_property
    def _cmp_parts(self) -> tuple[tuple[str, str], ...]:
        """Stable, type-aware comparison key for ordering.

        We include a fully-qualified type identifier so that e.g. `0` and "0"
        compare deterministically without being considered equal, and so that
        similarly-named types from different modules do not collide.
        """
        return tuple(
            (f"{type(p).__module__}.{type(p).__qualname__}", c)
            for p, c in zip(self.parts, self._cparts, strict=True)
        )

    def _make_child(self: TBasePath, args: list[Any]) -> TBasePath:
        parts = self._parse_args(args, sep=self.separator)
        parts_joined = self.parts + parts
        return self._clone_with_parts(parts_joined)

    def _make_child_relpath(self: TBasePath, part: Hashable) -> TBasePath:
        # This is an optimization used for dir walking.  `part` must be
        # a single part relative to this path.
        parts = self.parts + (part,)
        return self._clone_with_parts(parts)

    def _clone_with_parts(
        self: TBasePath, parts: tuple[Hashable, ...]
    ) -> TBasePath:
        """Create a new instance of the same class with the given parts.

        Subclasses like `AccessorPath` require extra constructor state (e.g. accessor).
        This helper attempts to preserve that state.
        """
        return self._from_parsed_parts(parts, separator=self.separator)

    def __fspath__(self) -> str:
        return str(self)

    def as_posix(self) -> str:
        """Return the path as a POSIX path (always uses '/')."""
        return "/".join(str(p) for p in self.parts)

    @cached_property
    def name(self) -> str:
        """Final path component."""
        if not self.parts:
            return ""
        return str(self.parts[-1])

    @staticmethod
    def _split_stem_suffix(name: str) -> tuple[str, str]:
        # Mirrors pathlib semantics for suffix handling, including dotfiles.
        if name in ("", ".", ".."):
            return name, ""
        dot = name.rfind(".")
        if dot <= 0:
            # no dot, or dotfile with no other suffix
            if dot == 0 and "." not in name[1:]:
                return name, ""
            return name, ""
        return name[:dot], name[dot:]

    @cached_property
    def suffix(self) -> str:
        """Final component's last suffix, including the leading dot."""
        stem, suffix = self._split_stem_suffix(self.name)
        return suffix

    @cached_property
    def suffixes(self) -> list[str]:
        """Final component's suffixes, each including the leading dot."""
        name = self.name
        if name in ("", ".", ".."):
            return []
        if name.startswith("."):
            rest = name[1:]
            if "." not in rest:
                return []
            name = rest
        parts = name.split(".")
        if len(parts) <= 1:
            return []
        return ["." + p for p in parts[1:]]

    @cached_property
    def stem(self) -> str:
        """Final component without its last suffix."""
        stem, _ = self._split_stem_suffix(self.name)
        return stem

    @cached_property
    def parent(self: TBasePath) -> TBasePath:
        """Logical parent path."""
        if not self.parts:
            return self
        return self._clone_with_parts(self.parts[:-1])

    @cached_property
    def parents(self: TBasePath) -> tuple[TBasePath, ...]:
        """Logical ancestors (like pathlib's `.parents`)."""
        if not self.parts:
            return ()
        return tuple(
            self._clone_with_parts(self.parts[:-i])
            for i in range(1, len(self.parts) + 1)
        )

    def joinpath(self: TBasePath, *other: Any) -> TBasePath:
        """Combine this path with one or more segments."""
        return self._make_child(list(other))

    def with_name(self: TBasePath, name: str) -> TBasePath:
        """Return a new path with the final component replaced."""
        if not self.parts:
            raise ValueError("with_name() requires a non-empty path")
        if not isinstance(name, str):
            raise TypeError("name must be a str")
        if not name:
            raise ValueError("name must be non-empty")
        if self.separator in name:
            raise ValueError("name must not contain path separator")
        new_parts = self.parts[:-1] + (name,)
        return self._clone_with_parts(new_parts)

    def with_suffix(self: TBasePath, suffix: str) -> TBasePath:
        """Return a new path with the final component's suffix changed."""
        if not self.parts:
            raise ValueError("with_suffix() requires a non-empty path")
        if not isinstance(suffix, str):
            raise TypeError("suffix must be a str")
        if suffix and not suffix.startswith("."):
            raise ValueError("Invalid suffix; must start with '.'")
        name = self.name
        if name in ("", ".", ".."):
            raise ValueError("Invalid name for with_suffix()")
        new_name = self.stem + suffix
        return self.with_name(new_name)

    def is_relative_to(self, *other: Any) -> bool:
        """Return True if the path is relative to `other`."""
        other_parts = self._parse_args(other, sep=self.separator)
        if len(other_parts) > len(self.parts):
            return False
        return self.parts[: len(other_parts)] == other_parts

    def relative_to(self: TBasePath, *other: Any) -> TBasePath:
        """Return the relative path from `other` to self.

        Raises ValueError if self is not under other.
        """
        other_parts = self._parse_args(other, sep=self.separator)
        if not self.is_relative_to(*other_parts):
            raise ValueError(
                f"{self!r} is not in the subpath of {BasePath._from_parsed_parts(other_parts, separator=self.separator)!r}"
            )
        return self._clone_with_parts(self.parts[len(other_parts) :])

    def __str__(self) -> str:
        return self.separator.join(self._cparts)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({str(self)!r})"

    def __hash__(self) -> int:
        return hash((self.separator, self.parts))

    def __truediv__(self: TBasePath, key: Any) -> TBasePath:
        try:
            return self._make_child(
                [
                    key,
                ]
            )
        except TypeError:
            return NotImplemented

    def __rtruediv__(self: TBasePath, key: Hashable) -> TBasePath:
        try:
            return self._from_parts(
                (key,) + self.parts, separator=self.separator
            )
        except TypeError:
            return NotImplemented

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, BasePath):
            return NotImplemented
        return (self.separator, self.parts) == (other.separator, other.parts)

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, BasePath):
            return NotImplemented
        return (self.separator, self._cmp_parts) < (
            other.separator,
            other._cmp_parts,
        )

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, BasePath):
            return NotImplemented
        return (self.separator, self._cmp_parts) <= (
            other.separator,
            other._cmp_parts,
        )

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, BasePath):
            return NotImplemented
        return (self.separator, self._cmp_parts) > (
            other.separator,
            other._cmp_parts,
        )

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, BasePath):
            return NotImplemented
        return (self.separator, self._cmp_parts) >= (
            other.separator,
            other._cmp_parts,
        )


class AccessorPath(BasePath, Generic[N, K, V]):
    """Path for object that can be read by accessor."""

    parts: tuple[K, ...]
    accessor: NodeAccessor[N, K, V]

    def __init__(
        self,
        accessor: NodeAccessor[N, K, V],
        *args: Any,
        separator: str | None = None,
    ):
        object.__setattr__(self, "accessor", accessor)
        super().__init__(*args, separator=separator)

    @classmethod
    def _from_parts(
        cls: type[TAccessorPath],
        args: Sequence[Any],
        separator: str | None = None,
        accessor: NodeAccessor[N, K, V] | None = None,
    ) -> TAccessorPath:
        if accessor is None:
            raise ValueError("accessor must be provided")
        return cls(accessor, *args, separator=separator)

    @classmethod
    def _from_parsed_parts(
        cls: type[TAccessorPath],
        parts: tuple[Hashable, ...],
        separator: str | None = None,
        accessor: NodeAccessor[N, K, V] | None = None,
    ) -> TAccessorPath:
        if accessor is None:
            raise ValueError("accessor must be provided")
        instance = cls.__new__(cls)
        object.__setattr__(instance, "parts", parts)
        object.__setattr__(
            instance, "separator", separator or instance.separator
        )
        object.__setattr__(instance, "accessor", accessor)
        return instance

    def _clone_with_parts(
        self: TAccessorPath, parts: tuple[Hashable, ...]
    ) -> TAccessorPath:
        """Create a new instance of the same class with the given parts."""
        return self._from_parsed_parts(
            parts,
            separator=self.separator,
            accessor=self.accessor,
        )

    def __rtruediv__(self: TAccessorPath, key: Hashable) -> TAccessorPath:
        try:
            return self._from_parts(
                (key,) + self.parts,
                separator=self.separator,
                accessor=self.accessor,
            )
        except TypeError:
            return NotImplemented

    def __floordiv__(self: TAccessorPath, key: K) -> TAccessorPath:
        """Return a new existing path with the key appended."""
        self.accessor.require_child(self.parts, key)
        return self._make_child_relpath(key)

    def __rfloordiv__(self: TAccessorPath, key: K) -> TAccessorPath:
        """Return a new existing path with the key prepended."""
        new = key / self
        # Validate existence in a way that preserves meaningful KeyError
        # diagnostics for missing/non-traversable intermediate nodes.
        #
        # We intentionally avoid `exists()` here because `exists()` uses
        # `accessor.stat()`, and `stat()` returns `None` for missing paths.
        # That behavior is useful for boolean checks, but it discards which
        # segment was missing.
        new.accessor.validate(new.parts)
        return new

    def __iter__(self: TAccessorPath) -> Iterator[TAccessorPath]:
        """Iterate over all child paths.

        Raises KeyError if the path is missing or non-traversable.
        """
        for key in self.accessor.keys(self.parts):
            yield self._make_child_relpath(key)

    def __getitem__(self: TAccessorPath, key: K) -> V | TAccessorPath:
        """Access a child path's value."""
        path: TAccessorPath | None = None

        # Fast path: if accessor supports direct traversal helpers, resolve the
        # child once and classify it without repeating full-path lookups.
        try:
            parent = self.accessor[self.parts]
            child = self.accessor._get_subnode(parent, key)
        except NotImplementedError:
            # Compatibility path for accessors that only implement keys/read.
            path = self // key
            if path.is_traversable():
                return path
            return cast(V, path.read_value())

        try:
            if self.accessor._is_traversable_node(child):
                path = self._make_child_relpath(key)
                return path
        except NotImplementedError:
            if path is None:
                path = self // key
            if path.is_traversable():
                return path

        try:
            return cast(V, self.accessor._read_node(child))
        except NotImplementedError:
            if path is None:
                path = self // key
            return cast(V, path.read_value())

    def __contains__(self, key: K) -> bool:
        """Check if a key exists in the path.

        This mirrors typical container semantics: membership checks return a
        boolean and do not raise for missing/non-traversable intermediate
        nodes.
        """
        return self.accessor.contains(self.parts, key)

    def __len__(self) -> int:
        """Return the number of child paths.

        Raises KeyError if the path is missing or non-traversable.
        """
        return self.accessor.len(self.parts)

    def exists(self) -> bool:
        """Check if the path exists."""
        return self.accessor.stat(self.parts) is not None

    def is_traversable(self) -> bool:
        """Return True if the path can enumerate child keys.

        This is a convenience wrapper around `accessor.is_traversable(...)`.
        """
        return self.accessor.is_traversable(self.parts)

    def keys(self) -> Sequence[K]:
        """Return all keys at the current path.

        Raises KeyError if the path is missing or non-traversable.
        """
        return self.accessor.keys(self.parts)

    def items(self: TAccessorPath) -> Iterator[tuple[K, TAccessorPath]]:
        """Return path's items."""
        for key in self.accessor.keys(self.parts):
            yield key, self._make_child_relpath(key)

    @overload
    def get(self, key: K) -> V | None: ...

    @overload
    def get(self, key: K, default: TDefault) -> V | TDefault: ...

    def get(self, key: K, default: object = None) -> object:
        """Return the value for key if key is in the path, else default."""
        try:
            return self[key]
        except KeyError:
            return default

    def read_value(self) -> V:
        """Return the path's value."""
        return self.accessor.read(self.parts)

    def stat(self) -> dict[str, Any] | None:
        """Return metadata for the path, or None if it doesn't exist."""
        return self.accessor.stat(self.parts)

    @contextmanager
    def open(self) -> Iterator[V]:
        """Context manager that yields the current path's value.

        This mirrors a file-like "open" API but works for any accessor.
        """
        yield self.read_value()


class FilesystemPath(AccessorPath[Path, str, bytes]):
    """Path for filesystem objects."""

    @classmethod
    def from_path(
        cls: type["FilesystemPath"],
        path: Path,
    ) -> "FilesystemPath":
        """Public constructor for a Path-backed path."""
        accessor = PathAccessor(path)
        return cls(accessor)


class LookupPath(AccessorPath[LookupNode, LookupKey, LookupValue]):
    """Path for object that supports __getitem__ lookups."""

    @classmethod
    def from_lookup(
        cls: type["LookupPath"],
        lookup: LookupNode,
        *args: Any,
        **kwargs: Any,
    ) -> "LookupPath":
        """Public constructor for a lookup-backed path."""
        return cls._from_lookup(lookup, *args, **kwargs)

    @classmethod
    def _from_lookup(
        cls: type["LookupPath"],
        lookup: LookupNode,
        *args: Any,
        **kwargs: Any,
    ) -> "LookupPath":
        accessor = LookupAccessor(lookup)
        return cls(accessor, *args, **kwargs)
