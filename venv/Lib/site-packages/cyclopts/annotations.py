import inspect
import sys
from enum import Flag
from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin

import attrs

from cyclopts.utils import is_class_and_subclass

if sys.version_info < (3, 11):  # pragma: no cover
    from typing_extensions import NotRequired, Required
else:  # pragma: no cover
    from typing import NotRequired, Required

if sys.version_info >= (3, 12):  # pragma: no cover
    from typing import TypeAliasType
else:  # pragma: no cover
    TypeAliasType = None

# from types import NoneType is available >=3.10
NoneType = type(None)
AnnotatedType = type(Annotated[int, 0])


def is_nonetype(hint):
    return hint is NoneType


def is_union(type_: type | None) -> bool:
    """Checks if a type is a union."""
    # Direct checks are faster than checking if the type is in a set that contains the union-types.
    if type_ is Union or type_ is UnionType:
        return True

    # The ``get_origin`` call is relatively expensive, so we'll check common types
    # that are passed in here to see if we can avoid calling ``get_origin``.
    if type_ is str or type_ is int or type_ is float or type_ is bool or is_annotated(type_):
        return False
    origin = get_origin(type_)
    return origin is Union or origin is UnionType


def is_pydantic(hint) -> bool:
    return hasattr(hint, "__pydantic_core_schema__")


def is_pydantic_secret(hint) -> bool:
    """Check if a type is a Pydantic secret type (SecretStr, SecretBytes, Secret, etc.)."""
    return (
        hasattr(hint, "__module__")
        and hint.__module__ == "pydantic.types"
        and hasattr(hint, "get_secret_value")
        and callable(getattr(hint, "get_secret_value", None))
    )


def is_dataclass(hint) -> bool:
    return hasattr(hint, "__dataclass_fields__")


def is_namedtuple(hint) -> bool:
    return is_class_and_subclass(hint, tuple) and hasattr(hint, "_fields")


def is_attrs(hint) -> bool:
    return attrs.has(hint)


def is_enum_flag(hint) -> bool:
    """Check if a type hint is an enum.Flag subclass."""
    return is_class_and_subclass(hint, Flag)


def is_annotated(hint) -> bool:
    return type(hint) is AnnotatedType


def contains_hint(hint, target_type) -> bool:
    """Indicates if ``target_type`` is in a possibly annotated/unioned ``hint``.

    E.g. ``contains_hint(Union[int, str], str) == True``
    """
    hint = resolve(hint)
    if is_union(hint):
        return any(contains_hint(x, target_type) for x in get_args(hint))
    else:
        return is_class_and_subclass(hint, target_type)


def is_typeddict(hint) -> bool:
    """Determine if a type annotation is a TypedDict.

    This is surprisingly hard! Modified from Beartype's implementation:

        https://github.com/beartype/beartype/blob/main/beartype/_util/hint/pep/proposal/utilpep589.py
    """
    hint = resolve(hint)
    if is_union(hint):
        return any(is_typeddict(x) for x in get_args(hint))

    if not is_class_and_subclass(hint, dict):
        return False

    return (
        hasattr(hint, "__annotations__")
        and hasattr(hint, "__total__")
        and hasattr(hint, "__required_keys__")
        and hasattr(hint, "__optional_keys__")
    )


def resolve(
    type_: Any,
) -> type:
    """Perform all simplifying resolutions."""
    if type_ is inspect.Parameter.empty:
        return str

    type_prev = None
    while type_ != type_prev:
        type_prev = type_
        type_ = resolve_type_alias(type_)
        type_ = resolve_annotated(type_)
        type_ = resolve_optional(type_)
        type_ = resolve_required(type_)
        type_ = resolve_new_type(type_)
    return type_


def resolve_optional(type_: Any) -> Any:
    """Only resolves Union's of None + one other type (i.e. Optional)."""
    type_ = resolve_type_alias(type_)
    # Python will automatically flatten out nested unions when possible.
    # So we don't need to loop over resolution.
    if not is_union(type_):
        return type_

    non_none_types = [t for t in get_args(type_) if t is not NoneType]
    if not non_none_types:  # pragma: no cover
        # This should never happen; python simplifies:
        #    ``Union[None, None] -> NoneType``
        raise ValueError("Union type cannot be all NoneType")
    elif len(non_none_types) == 1:
        type_ = non_none_types[0]
    elif len(non_none_types) > 1:
        return Union[tuple(resolve_optional(x) for x in non_none_types)]  # pyright: ignore  # noqa: UP007
    else:
        raise NotImplementedError

    return type_


def resolve_annotated(type_: Any) -> type:
    type_ = resolve_type_alias(type_)
    if type(type_) is AnnotatedType:
        type_ = get_args(type_)[0]
    return type_


def resolve_required(type_: Any) -> type:
    if get_origin(type_) in (Required, NotRequired):
        type_ = get_args(type_)[0]
    return type_


def resolve_new_type(type_: Any) -> type:
    try:
        return resolve_new_type(type_.__supertype__)
    except AttributeError:
        return type_


def resolve_type_alias(type_: Any) -> Any:
    """Resolve TypeAliasType (Python 3.12+ 'type' statement) to its underlying type."""
    if TypeAliasType is not None and isinstance(type_, TypeAliasType):
        return type_.__value__
    return type_


def get_hint_name(hint) -> str:
    if isinstance(hint, str):
        return hint
    if is_nonetype(hint):
        return "None"
    if hint is Any:
        return "Any"
    if is_union(hint):
        return "|".join(get_hint_name(arg) for arg in get_args(hint))
    if origin := get_origin(hint):
        out = get_hint_name(origin)
        if args := get_args(hint):
            out += "[" + ", ".join(get_hint_name(arg) for arg in args) + "]"
        return out
    if hasattr(hint, "__name__"):
        return hint.__name__
    if getattr(hint, "_name", None) is not None:
        return hint._name
    return str(hint)
