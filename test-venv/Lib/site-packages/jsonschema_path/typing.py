from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import TypeGuard

from pathable.types import LookupKey as SchemaKey
from pathable.types import LookupNode as SchemaNode
from pathable.types import LookupValue as SchemaValue

__all__ = [
    "ResolverHandlers",
    "Schema",
    "SchemaNode",
    "SchemaKey",
    "SchemaValue",
]

ResolverHandlers = Mapping[str, Any]
Schema = Mapping[str, Any]


def is_str_sequence(val: Sequence[object]) -> TypeGuard[Sequence[str]]:
    """Determines whether all objects in the list are strings"""
    return all(isinstance(x, str) for x in val)
