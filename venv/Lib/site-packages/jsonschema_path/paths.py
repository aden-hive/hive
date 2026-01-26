"""JSONSchema spec paths module."""

import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import Iterator
from typing import Optional
from typing import Type
from typing import TypeVar

from pathable.paths import AccessorPath
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

TSpec = TypeVar("TSpec", bound="SchemaPath")

SPEC_SEPARATOR = "#"


class SchemaPath(AccessorPath):
    def __init__(self, accessor: SchemaAccessor, *args: Any, **kwargs: Any):
        super().__init__(accessor, *args, **kwargs)
        self._resolved_cached: Optional[Resolved[Any]] = None

    @classmethod
    def from_dict(
        cls: Type[TSpec],
        data: Schema,
        *args: Any,
        separator: str = SPEC_SEPARATOR,
        specification: Specification[Schema] = DRAFT202012,
        base_uri: str = "",
        handlers: ResolverHandlers = default_handlers,
        spec_url: Optional[str] = None,
        ref_resolver_handlers: Optional[ResolverHandlers] = None,
    ) -> TSpec:
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
        )

        return cls(accessor, *args, separator=separator)

    @classmethod
    def from_path(
        cls: Type[TSpec],
        path: Path,
    ) -> TSpec:
        reader = PathReader(path)
        data, base_uri = reader.read()
        return cls.from_dict(data, base_uri=base_uri)

    @classmethod
    def from_file_path(
        cls: Type[TSpec],
        file_path: str,
    ) -> TSpec:
        reader = FilePathReader(file_path)
        data, base_uri = reader.read()
        return cls.from_dict(data, base_uri=base_uri)

    @classmethod
    def from_file(
        cls: Type[TSpec],
        fileobj: SupportsRead,
        base_uri: str = "",
        spec_url: Optional[str] = None,
    ) -> TSpec:
        reader = FileReader(fileobj)
        data, _ = reader.read()
        return cls.from_dict(data, base_uri=base_uri, spec_url=spec_url)

    def contents(self) -> Any:
        with self.open() as d:
            return d

    def exists(self) -> bool:
        try:
            self.contents()
        except KeyError:
            return False
        else:
            return True

    def as_uri(self) -> str:
        return f"#/{str(self)}"

    @contextmanager
    def open(self) -> Any:
        """Open the path."""
        # Cached path content
        with self.resolve() as resolved:
            yield resolved.contents

    @contextmanager
    def resolve(self) -> Iterator[Resolved[Any]]:
        """Resolve the path."""
        # Cached path content
        if self._resolved_cached is None:
            self._resolved_cached = self._get_resolved()
        yield self._resolved_cached

    def _get_resolved(self) -> Resolved[Any]:
        assert isinstance(self.accessor, SchemaAccessor)
        with self.accessor.resolve(self.parts) as resolved:
            return resolved
