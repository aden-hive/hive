"""JSONSchema spec accessors module."""

from collections import deque
from contextlib import contextmanager
from typing import Any
from typing import Deque
from typing import Hashable
from typing import Iterator
from typing import List
from typing import Optional
from typing import Union

from pathable.accessors import LookupAccessor
from referencing import Registry
from referencing import Specification
from referencing._core import Resolved
from referencing._core import Resolver
from referencing.jsonschema import DRAFT202012

from jsonschema_path.handlers import default_handlers
from jsonschema_path.retrievers import SchemaRetriever
from jsonschema_path.typing import Lookup
from jsonschema_path.typing import ResolverHandlers
from jsonschema_path.typing import Schema
from jsonschema_path.utils import is_ref


class ResolverAccessor(LookupAccessor):
    def __init__(self, lookup: Lookup, resolver: Resolver[Lookup]):
        super().__init__(lookup)
        self.resolver = resolver


class SchemaAccessor(ResolverAccessor):
    @classmethod
    def from_schema(
        cls,
        schema: Schema,
        specification: Specification[Schema] = DRAFT202012,
        base_uri: str = "",
        handlers: ResolverHandlers = default_handlers,
    ) -> "SchemaAccessor":
        retriever = SchemaRetriever(handlers, specification)
        base_resource = specification.create_resource(schema)
        registry: Registry[Schema] = Registry(
            retrieve=retriever,  # type: ignore
        )
        registry = registry.with_resource(base_uri, base_resource)
        resolver = registry.resolver(base_uri=base_uri)
        return cls(schema, resolver)

    @contextmanager
    def open(self, parts: List[Hashable]) -> Iterator[Union[Schema, Any]]:
        parts_deque = deque(parts)
        try:
            resolved = self._resolve(self.lookup, parts_deque)
            yield resolved.contents
        finally:
            pass

    @contextmanager
    def resolve(self, parts: List[Hashable]) -> Iterator[Resolved[Any]]:
        parts_deque = deque(parts)
        try:
            yield self._resolve(self.lookup, parts_deque)
        finally:
            pass

    def _resolve(
        self,
        contents: Schema,
        parts_deque: Deque[Hashable],
        resolver: Optional[Resolver[Schema]] = None,
    ) -> Resolved[Any]:
        resolver = resolver or self.resolver
        if is_ref(contents):
            ref = contents["$ref"]
            resolved = resolver.lookup(ref)
            self.resolver = self.resolver._evolve(
                self.resolver._base_uri,
                registry=resolved.resolver._registry,
            )
            return self._resolve(
                resolved.contents,
                parts_deque,
                resolver=resolved.resolver,
            )

        try:
            part = parts_deque.popleft()
        except IndexError:
            return Resolved(contents=contents, resolver=resolver)  # type: ignore
        else:
            target = contents[part]
            return self._resolve(target, parts_deque, resolver=resolver)
