from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from pathable.types import LookupKey
from pathable.types import LookupNode
from referencing import Registry
from referencing._core import Resolved
from referencing._core import Resolver

from jsonschema_path.caches import PrefixResolvedCache
from jsonschema_path.nodes import SchemaNode
from jsonschema_path.typing import Schema


@dataclass(frozen=True)
class ResolveResult:
    resolved: Resolved[LookupNode]
    registry_changed: bool


class CachedPathResolver:
    def __init__(self, resolver: Resolver[Schema]):
        self.resolver = resolver
        self.prefix_cache = PrefixResolvedCache()

    def resolve(
        self,
        node: LookupNode,
        parts: Sequence[LookupKey],
    ) -> ResolveResult:
        resolved = self._resolve_with_prefix_cache(node, parts)
        registry_changed = self._sync_registry(resolved.resolver._registry)
        return ResolveResult(
            resolved=resolved,
            registry_changed=registry_changed,
        )

    def _resolve_with_prefix_cache(
        self,
        node: LookupNode,
        parts: Sequence[LookupKey],
    ) -> Resolved[LookupNode]:

        parts_tuple = tuple(parts)
        cached_prefix = self.prefix_cache.longest_prefix_hit(parts_tuple)
        if cached_prefix is None:
            root_resolved_schema = SchemaNode._resolve_node(
                node,
                self.resolver,
            )
            resolved = cast(Resolved[LookupNode], root_resolved_schema)
            current_node = cast(LookupNode, root_resolved_schema.contents)
            current_resolver: Resolver[Schema] = root_resolved_schema.resolver
            start = 0
            self.prefix_cache.seed_root(resolved)
        else:
            start, resolved = cached_prefix
            current_node = resolved.contents
            current_resolver = cast(Resolver[Schema], resolved.resolver)

        for index in range(start, len(parts_tuple)):
            part = parts_tuple[index]
            current_node = SchemaNode._get_subnode(current_node, part)
            resolved_schema = SchemaNode._resolve_node(
                current_node,
                current_resolver,
            )
            resolved = cast(Resolved[LookupNode], resolved_schema)
            current_node, current_resolver = (
                resolved.contents,
                resolved_schema.resolver,
            )
            self.prefix_cache.store_intermediate(
                parts_tuple,
                index,
                resolved,
            )

        return resolved

    def _sync_registry(self, registry: Registry[LookupNode]) -> bool:
        if registry is self.resolver._registry:
            return False

        self.resolver = self.resolver._evolve(
            self.resolver._base_uri,
            registry=registry,
        )
        self.prefix_cache.invalidate()
        return True
