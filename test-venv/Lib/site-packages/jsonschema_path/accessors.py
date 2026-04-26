"""JSONSchema spec accessors module."""

import warnings
from collections.abc import Hashable
from collections.abc import Iterator
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any
from typing import cast

from pathable.accessors import LookupAccessor
from pathable.types import LookupKey
from pathable.types import LookupNode
from pathable.types import LookupValue
from referencing import Registry
from referencing import Specification
from referencing._core import Resolved
from referencing._core import Resolver
from referencing.jsonschema import DRAFT202012

from jsonschema_path.caches import FullPathResolvedCache
from jsonschema_path.handlers import default_handlers
from jsonschema_path.resolvers import CachedPathResolver
from jsonschema_path.retrievers import SchemaRetriever
from jsonschema_path.typing import ResolverHandlers
from jsonschema_path.typing import Schema


class SchemaAccessor(LookupAccessor):
    def __init__(
        self,
        schema: Schema,
        resolver: Resolver[Schema],
        resolved_cache_maxsize: int = 0,
    ):
        if resolved_cache_maxsize < 0:
            raise ValueError("resolved_cache_maxsize must be >= 0")

        super().__init__(cast(LookupNode, schema))
        self._path_resolver: CachedPathResolver = CachedPathResolver(
            resolver,
        )
        self._resolved_cache_maxsize = resolved_cache_maxsize
        self._resolved_cache: FullPathResolvedCache = FullPathResolvedCache(
            maxsize=resolved_cache_maxsize
        )

    @classmethod
    def from_schema(
        cls,
        schema: Schema,
        specification: Specification[Schema] = DRAFT202012,
        base_uri: str = "",
        handlers: ResolverHandlers | None = None,
        resolved_cache_maxsize: int = 0,
    ) -> "SchemaAccessor":
        if handlers is None:
            handlers = default_handlers
        retriever = SchemaRetriever(handlers, specification)
        base_resource = specification.create_resource(schema)
        registry: Registry[Schema] = Registry(
            retrieve=retriever,  # type: ignore
        )
        registry = registry.with_resource(base_uri, base_resource)
        resolver = registry.resolver(base_uri=base_uri)
        return cls(
            schema,
            resolver,
            resolved_cache_maxsize=resolved_cache_maxsize,
        )

    @property
    def base_uri(self) -> str:
        return self._path_resolver.resolver._base_uri

    @property
    def resolver(self) -> Resolver[Schema]:
        warnings.warn(
            "SchemaAccessor.resolver is deprecated. "
            "Use SchemaPath.base_uri to access the base URI and "
            "SchemaPath.resolve() to resolve paths.",
            DeprecationWarning,
        )
        return self._path_resolver.resolver

    def __getitem__(self, parts: Sequence[LookupKey]) -> LookupNode:
        resolved = self.get_resolved(parts)
        return resolved.contents

    def stat(self, parts: Sequence[Hashable]) -> dict[str, Any] | None:
        try:
            node = self[cast(Sequence[LookupKey], parts)]
        except (KeyError, IndexError, TypeError):
            return None

        if self._is_traversable_node(node):
            return {
                "type": type(node).__name__,
                "length": len(node),
            }
        try:
            length = len(cast(Any, node))
        except TypeError:
            length = None

        return {
            "type": type(node).__name__,
            "length": length,
        }

    def keys(self, parts: Sequence[LookupKey]) -> Sequence[LookupKey]:
        node = self[parts]

        if isinstance(node, dict):
            # dict_keys has O(1) membership, no allocation.
            return cast(Sequence[LookupKey], node.keys())
        if isinstance(node, list):
            # range has O(1) membership and supports iteration.
            return cast(Sequence[LookupKey], range(len(node)))

        # Non-traversable leaf.
        if parts:
            raise KeyError(parts[-1])
        raise KeyError

    def len(self, parts: Sequence[LookupKey]) -> int:
        node = self[parts]
        if isinstance(node, (dict, list)):
            return len(node)
        if parts:
            raise KeyError(parts[-1])
        raise KeyError

    def contains(self, parts: Sequence[LookupKey], key: LookupKey) -> bool:
        try:
            node = self[parts]
        except (KeyError, IndexError, TypeError):
            return False

        if isinstance(node, dict):
            return key in node
        if isinstance(node, list):
            return isinstance(key, int) and 0 <= key < len(node)
        return False

    def require_child(
        self, parts: Sequence[LookupKey], key: LookupKey
    ) -> None:
        # Validate parent path for intermediate diagnostics.
        node = self[parts]

        if isinstance(node, dict):
            if key not in node:
                raise KeyError(key)
            return
        if isinstance(node, list):
            if not (isinstance(key, int) and 0 <= key < len(node)):
                raise KeyError(key)
            return

        raise KeyError(key)

    def read(self, parts: Sequence[LookupKey]) -> LookupValue:
        node = self[parts]
        return self._read_node(node)

    @contextmanager
    def resolve(
        self, parts: Sequence[LookupKey]
    ) -> Iterator[Resolved[LookupNode]]:
        try:
            yield self.get_resolved(parts)
        finally:
            pass

    def get_resolved(self, parts: Sequence[LookupKey]) -> Resolved[LookupNode]:
        cached_resolved = self._resolved_cache.get(parts)
        if cached_resolved is not None:
            return cached_resolved

        result = self._path_resolver.resolve(self.node, parts)
        if result.registry_changed:
            self._resolved_cache.invalidate()

        self._resolved_cache.set(parts, result.resolved)

        return result.resolved
