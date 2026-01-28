# Use CSafeFile if available
from typing import TYPE_CHECKING
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Tuple

if TYPE_CHECKING:
    from yaml import SafeLoader
else:
    try:
        from yaml import CSafeLoader as SafeLoader
    except ImportError:
        from yaml import SafeLoader


__all__ = [
    "SafeLoader",
]


class LimitedSafeLoader(type):
    """Meta YAML loader that skips the resolution of the specified YAML tags."""

    def __new__(
        cls,
        name: str,
        bases: Tuple[type, ...],
        namespace: Dict[str, Any],
        exclude_resolvers: Iterable[str],
    ) -> "LimitedSafeLoader":
        exclude_resolvers = set(exclude_resolvers)
        implicit_resolvers = {
            key: [
                (tag, regex)
                for tag, regex in mappings
                if tag not in exclude_resolvers
            ]
            for key, mappings in SafeLoader.yaml_implicit_resolvers.items()
        }
        return super().__new__(
            cls,
            name,
            (SafeLoader, *bases),
            {**namespace, "yaml_implicit_resolvers": implicit_resolvers},
        )


class JsonschemaSafeLoader(
    metaclass=LimitedSafeLoader,
    exclude_resolvers={"tag:yaml.org,2002:timestamp"},
):
    """A safe YAML loader that leaves timestamps as strings."""
