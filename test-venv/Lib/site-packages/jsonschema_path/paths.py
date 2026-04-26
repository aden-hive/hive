"""JSONSchema spec paths module."""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator
from collections.abc import Sequence
from contextlib import contextmanager
from functools import cached_property
from pathlib import Path
from typing import Any
from typing import TypeVar
from typing import overload

from pathable import AccessorPath
from referencing import Specification
from referencing._core import Resolved
from referencing.jsonschema import DRAFT202012

from jsonschema_path.accessors import SchemaAccessor
from jsonschema_path.handlers import default_handlers
from jsonschema_path.handlers.protocols import SupportsRead
from jsonschema_path.readers import FilePathReader
from jsonschema_path.readers import FileReader
from jsonschema_path.readers import PathReader
from jsonschema_path.typing import ResolverHandlers
from jsonschema_path.typing import Schema
from jsonschema_path.typing import SchemaKey
from jsonschema_path.typing import SchemaNode
from jsonschema_path.typing import SchemaValue
from jsonschema_path.typing import is_str_sequence

TDefault = TypeVar("TDefault")
# Python 3.11+ shortcut: typing.Self
TSchemaPath = TypeVar("TSchemaPath", bound="SchemaPath")

SPEC_SEPARATOR = "#"
NOTSET = object()


class SchemaPath(AccessorPath[SchemaNode, SchemaKey, SchemaValue]):

    @classmethod
    def _parse_args(
        cls,
        args: Sequence[Any],
        sep: str = SPEC_SEPARATOR,
    ) -> tuple[SchemaKey, ...]:
        parts: list[SchemaKey] = []
        append = parts.append
        extend = parts.extend

        for a in args:
            if isinstance(a, cls):
                extend(a.parts)
                continue

            # Fast-path: benchmarks overwhelmingly pass `str`/`int` parts.
            if isinstance(a, int):
                append(a)
                continue

            if isinstance(a, bytes):
                a = a.decode("ascii")

            if isinstance(a, str):
                if a and a != ".":
                    if sep in a:
                        for x in a.split(sep):
                            if x and x != ".":
                                append(x)
                    else:
                        append(a)
                continue

            # PathLike is relatively expensive to check; keep it after common types.
            if isinstance(a, os.PathLike):
                a = os.fspath(a)
                if isinstance(a, bytes):
                    a = a.decode("ascii")
                if isinstance(a, str):
                    if a and a != ".":
                        if sep in a:
                            for x in a.split(sep):
                                if x and x != ".":
                                    append(x)
                        else:
                            append(a)
                    continue

            raise TypeError(
                "argument must be str, int, bytes, os.PathLike, or SchemaPath; got %r"
                % (type(a),)
            )

        return tuple(parts)

    @classmethod
    def from_dict(
        cls: type[TSchemaPath],
        data: Schema,
        *args: Any,
        separator: str = SPEC_SEPARATOR,
        specification: Specification[Schema] = DRAFT202012,
        base_uri: str = "",
        handlers: ResolverHandlers = default_handlers,
        resolved_cache_maxsize: int = 0,
        spec_url: str | None = None,
        ref_resolver_handlers: ResolverHandlers | None = None,
    ) -> TSchemaPath:
        if spec_url is not None:
            warnings.warn(
                "spec_url parameter is deprecated. " "Use base_uri instead.",
                DeprecationWarning,
            )
            base_uri = spec_url
        if ref_resolver_handlers is not None:
            warnings.warn(
                "ref_resolver_handlers parameter is deprecated. "
                "Use handlers instead.",
                DeprecationWarning,
            )
            handlers = ref_resolver_handlers

        accessor: SchemaAccessor = SchemaAccessor.from_schema(
            data,
            specification=specification,
            base_uri=base_uri,
            handlers=handlers,
            resolved_cache_maxsize=resolved_cache_maxsize,
        )

        return cls(accessor, *args, separator=separator)

    @classmethod
    def from_path(
        cls: type[TSchemaPath],
        path: Path,
        resolved_cache_maxsize: int = 0,
    ) -> TSchemaPath:
        reader = PathReader(path)
        data, base_uri = reader.read()
        return cls.from_dict(
            data,
            base_uri=base_uri,
            resolved_cache_maxsize=resolved_cache_maxsize,
        )

    @classmethod
    def from_file_path(
        cls: type[TSchemaPath],
        file_path: str,
        resolved_cache_maxsize: int = 0,
    ) -> TSchemaPath:
        reader = FilePathReader(file_path)
        data, base_uri = reader.read()
        return cls.from_dict(
            data,
            base_uri=base_uri,
            resolved_cache_maxsize=resolved_cache_maxsize,
        )

    @classmethod
    def from_file(
        cls: type[TSchemaPath],
        fileobj: SupportsRead,
        base_uri: str = "",
        spec_url: str | None = None,
        resolved_cache_maxsize: int = 0,
    ) -> TSchemaPath:
        reader = FileReader(fileobj)
        data, _ = reader.read()
        return cls.from_dict(
            data,
            base_uri=base_uri,
            spec_url=spec_url,
            resolved_cache_maxsize=resolved_cache_maxsize,
        )

    @property
    def base_uri(self) -> str:
        assert isinstance(self.accessor, SchemaAccessor)
        return self.accessor.base_uri

    def str_keys(self) -> Sequence[str]:
        keys = list(self.keys())
        if not is_str_sequence(keys):
            raise TypeError(
                f"Expected string keys, got {[type(x) for x in keys]}"
            )
        return keys

    def str_items(self) -> Iterator[tuple[str, SchemaPath]]:
        for key, value in self.items():
            if not isinstance(key, str):
                raise TypeError(f"Expected string keys, got {type(key)}")
            yield key, value

    @overload
    def read_str(self) -> str: ...

    @overload
    def read_str(self, default: TDefault) -> str | TDefault: ...

    def read_str(self, default: object = NOTSET) -> object:
        try:
            value = self.read_value()
        except KeyError:
            if default is not NOTSET:
                return default
            raise
        if not isinstance(value, str):
            raise TypeError(f"Expected a string value, got {type(value)}")
        return value

    @overload
    def read_str_or_list(self) -> str | list[str]: ...

    @overload
    def read_str_or_list(
        self, default: TDefault
    ) -> str | list[str] | TDefault: ...

    def read_str_or_list(self, default: object = NOTSET) -> object:
        try:
            value = self.read_value()
        except KeyError:
            if default is not NOTSET:
                return default
            raise
        if not isinstance(value, (str, list)):
            raise TypeError(
                f"Expected a string or a list of strings, got {type(value)}"
            )
        return value

    @overload
    def read_bool(self) -> bool: ...

    @overload
    def read_bool(self, default: TDefault) -> bool | TDefault: ...

    def read_bool(self, default: object = NOTSET) -> object:
        try:
            value = self.read_value()
        except KeyError:
            if default is not NOTSET:
                return default
            raise
        if not isinstance(value, bool):
            if default is not NOTSET:
                return default
            raise TypeError(f"Expected a bool value, got {type(value)}")
        return value

    def as_uri(self) -> str:
        return f"#/{str(self)}"

    @contextmanager
    def open(self) -> Any:
        """Open the path."""
        # Cached path content
        with self.resolve() as resolved:
            yield resolved.contents

    @contextmanager
    def resolve(self) -> Iterator[Resolved[SchemaNode]]:
        """Resolve the path."""
        # Cached path content
        yield self._get_resolved

    @cached_property
    def _get_resolved(self) -> Resolved[SchemaNode]:
        assert isinstance(self.accessor, SchemaAccessor)
        with self.accessor.resolve(self.parts) as resolved:
            return resolved
