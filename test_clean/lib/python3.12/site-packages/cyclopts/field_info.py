import inspect
import sys
from typing import (  # noqa: F401
    Annotated,
    Any,
    ClassVar,
    Optional,
    get_args,
    get_origin,
    get_type_hints,
)

import attrs
from attrs import field

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from cyclopts.annotations import (
    NotRequired,
    Required,
    is_annotated,
    is_attrs,
    is_dataclass,
    is_enum_flag,
    is_namedtuple,
    is_pydantic,
    is_pydantic_secret,
    is_typeddict,
    resolve,
    resolve_annotated,
    resolve_optional,
)
from cyclopts.utils import UNSET, is_builtin

POSITIONAL_OR_KEYWORD = inspect.Parameter.POSITIONAL_OR_KEYWORD
POSITIONAL_ONLY = inspect.Parameter.POSITIONAL_ONLY
KEYWORD_ONLY = inspect.Parameter.KEYWORD_ONLY
VAR_POSITIONAL = inspect.Parameter.VAR_POSITIONAL
VAR_KEYWORD = inspect.Parameter.VAR_KEYWORD


def _replace_annotated_type(src_type, dst_type):
    if not is_annotated(src_type):
        return dst_type
    return Annotated[(dst_type,) + get_args(src_type)[1:]]  # pyright: ignore


@attrs.define
class FieldInfo:
    """Extension of :class:`inspect.Parameter`."""

    names: tuple[str, ...] = ()
    kind: inspect._ParameterKind = inspect.Parameter.POSITIONAL_OR_KEYWORD

    required: bool = field(kw_only=True, default=False)
    default: Any = field(default=inspect.Parameter.empty, kw_only=True)
    annotation: Any = field(default=inspect.Parameter.empty, kw_only=True)

    help: str | None = field(default=None, kw_only=True)
    """Can be populated by additional metadata from another library; e.g. ``pydantic.FieldInfo.description``."""

    ###################
    # Class Variables #
    ###################
    empty: ClassVar = inspect.Parameter.empty
    POSITIONAL_OR_KEYWORD: ClassVar = inspect.Parameter.POSITIONAL_OR_KEYWORD
    POSITIONAL_ONLY: ClassVar = inspect.Parameter.POSITIONAL_ONLY
    KEYWORD_ONLY: ClassVar = inspect.Parameter.KEYWORD_ONLY
    VAR_POSITIONAL: ClassVar = inspect.Parameter.VAR_POSITIONAL
    VAR_KEYWORD: ClassVar = inspect.Parameter.VAR_KEYWORD
    POSITIONAL: ClassVar[frozenset[inspect._ParameterKind]] = frozenset(
        {POSITIONAL_OR_KEYWORD, POSITIONAL_ONLY, VAR_POSITIONAL}
    )
    KEYWORD: ClassVar[frozenset[inspect._ParameterKind]] = frozenset({POSITIONAL_OR_KEYWORD, KEYWORD_ONLY, VAR_KEYWORD})

    @classmethod
    def from_iparam(cls, iparam: inspect.Parameter, *, annotation: Any = UNSET, required: bool | None = None) -> Self:
        if required is None:
            required = (
                iparam.default is iparam.empty
                and iparam.kind != iparam.VAR_KEYWORD
                and iparam.kind != iparam.VAR_POSITIONAL
            )

        return cls(
            names=(iparam.name,),
            annotation=iparam.annotation if annotation is UNSET else annotation,
            kind=iparam.kind,
            default=iparam.default,
            required=required,
        )

    @property
    def hint(self):
        """Annotation with Optional-removed and cyclopts type-inferring."""
        hint = self.annotation
        if hint is inspect.Parameter.empty or resolve(hint) is Any:
            hint = _replace_annotated_type(
                hint, str if self.default is inspect.Parameter.empty or self.default is None else type(self.default)
            )
        hint = resolve_optional(hint)
        return hint

    @property
    def name(self):
        """The **first** provided name."""
        return self.names[0]

    @property
    def is_positional(self) -> bool:
        return self.kind in self.POSITIONAL

    @property
    def is_positional_only(self) -> bool:
        return self.kind in (POSITIONAL_ONLY, VAR_POSITIONAL)

    @property
    def is_keyword(self) -> bool:
        return self.kind in self.KEYWORD

    @property
    def is_keyword_only(self) -> bool:
        return self.kind in (KEYWORD_ONLY, VAR_KEYWORD)

    def evolve(self, **kwargs):
        return attrs.evolve(self, **kwargs)


def _typed_dict_field_infos(typeddict) -> dict[str, FieldInfo]:
    # The ``__required_keys__`` and ``__optional_keys__`` attributes of TypedDict are kind of broken in <cp3.11.
    out = {}
    for name, annotation in get_type_hints(typeddict, include_extras=True).items():
        origin = get_origin(resolve_annotated(annotation))
        if origin is Required:
            required = True
        elif origin is NotRequired:
            required = False
        elif typeddict.__total__:  # Fields are REQUIRED by default.
            required = True
        else:  # Fields are OPTIONAL by default
            required = False
        out[name] = FieldInfo((name,), FieldInfo.KEYWORD_ONLY, annotation=annotation, required=required)
    return out


def _generic_class_field_infos(
    f,
    include_var_positional=False,
    include_var_keyword=False,
) -> dict[str, FieldInfo]:
    out = {}
    for name, field_info in signature_parameters(f.__init__).items():
        if field_info.name == "self":
            continue
        if not include_var_positional and field_info.kind is field_info.VAR_POSITIONAL:
            continue
        if not include_var_keyword and field_info.kind is field_info.VAR_KEYWORD:
            continue
        out[name] = field_info
    return out


def _pydantic_field_infos(model) -> dict[str, FieldInfo]:
    from pydantic_core import PydanticUndefined

    out = {}
    for python_name, pydantic_field in model.model_fields.items():
        names = []
        if pydantic_field.alias:
            if model.model_config.get("populate_by_name", False):
                names.append(python_name)
            names.append(pydantic_field.alias)

            # Add legacy-compatible CLI form if not already present.
            # This allows both "user-name" (new) and "username" (legacy) to work as CLI options.
            # Old transform behavior: alias.lower() (no pascal_to_snake)
            # New transform behavior: _pascal_to_snake(alias).lower()
            legacy_form = pydantic_field.alias.lower()
            if legacy_form not in names:
                names.append(legacy_form)
        else:
            names.append(python_name)

        # Extract Field with description from metadata
        help = pydantic_field.description or None
        for meta in pydantic_field.metadata:
            if hasattr(meta, "description") and meta.description:
                help = meta.description

        # Pydantic places ``Annotated`` data into pydantic.FieldInfo.metadata, while
        # pydantic.FieldInfo.annotation contains the "real" resolved type-hint.
        # We have to re-combine them into a single Annotated hint.
        # For discriminated unions, pydantic stores discriminator separately (not in metadata),
        # so include pydantic_field itself to preserve the discriminator attribute.
        if pydantic_field.discriminator:
            annotation = Annotated[(pydantic_field.annotation, pydantic_field) + tuple(pydantic_field.metadata)]  # pyright: ignore
        elif pydantic_field.metadata:
            annotation = Annotated[(pydantic_field.annotation,) + tuple(pydantic_field.metadata)]  # pyright: ignore
        else:
            annotation = pydantic_field.annotation

        out[python_name] = FieldInfo(
            names=tuple(names),
            kind=inspect.Parameter.KEYWORD_ONLY if pydantic_field.kw_only else inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=annotation,
            default=FieldInfo.empty if pydantic_field.default is PydanticUndefined else pydantic_field.default,
            required=pydantic_field.is_required(),
            help=help,
        )
    return out


def _namedtuple_field_infos(hint) -> dict[str, FieldInfo]:
    out = {}
    type_hints = get_type_hints(hint)
    for name in hint._fields:
        out[name] = FieldInfo(
            names=(name,),
            kind=FieldInfo.POSITIONAL_OR_KEYWORD,
            annotation=type_hints.get(name, str),
            default=hint._field_defaults.get(name, FieldInfo.empty),
            required=name not in hint._field_defaults,
        )
    return out


def _attrs_field_infos(hint) -> dict[str, FieldInfo]:
    out = {}
    field_infos = signature_parameters(hint.__init__)
    for attribute in hint.__attrs_attrs__:
        if not attribute.init:
            continue

        field_info = field_infos[attribute.alias]

        if isinstance(attribute.default, attrs.Factory):  # pyright: ignore
            required = False
            default = None  # Not strictly True, but we don't want to invoke factory
        elif attribute.default is attrs.NOTHING:
            required = True
            default = FieldInfo.empty
        else:
            required = False
            default = attribute.default

        help = attribute.metadata.get("help") if attribute.metadata else None

        out[field_info.name] = field_info.evolve(
            names=(attribute.alias,), required=required, default=default, help=help
        )
    return out


def _dataclass_field_infos(hint) -> dict[str, FieldInfo]:
    import dataclasses

    out = {}
    fields = dataclasses.fields(hint)
    type_hints = get_type_hints(hint, include_extras=True)  # resolves stringified type hints
    for f in fields:
        if f.default_factory is not dataclasses.MISSING:
            default = f.default_factory()
            required = False
        elif f.default is not dataclasses.MISSING:
            default = f.default
            required = False
        else:
            default = FieldInfo.empty
            required = True

        annotation = type_hints.get(f.name, FieldInfo.empty)

        kind = FieldInfo.KEYWORD_ONLY if f.kw_only else FieldInfo.POSITIONAL_OR_KEYWORD

        # Extract help text with precedence order:
        # 1. metadata["help"] - explicit help in metadata
        # 2. metadata["doc"] - doc stored in metadata
        # 3. f.doc - Python 3.14+ field(doc=...) parameter
        help = None
        if f.metadata:
            help = f.metadata.get("help") or f.metadata.get("doc")
        if not help and hasattr(f, "doc"):
            help = f.doc  # type: ignore[attr-defined]

        out[f.name] = FieldInfo(
            names=(f.name,),
            kind=kind,
            required=required,
            annotation=annotation,
            default=default,
            help=help,
        )
    return out


def _enum_flag_field_infos(enum_flag) -> dict[str, FieldInfo]:
    """Extract field infos from a Flag enum, treating each member as a boolean field."""
    out = {}
    for member_name in enum_flag.__members__:
        out[member_name] = FieldInfo(
            names=(member_name,),
            kind=FieldInfo.KEYWORD_ONLY,
            # The Enum member should NEVER have a type-annotation.
            # Thusly, it by definition cannot have an Annotated[...].
            # see: https://typing.python.org/en/latest/spec/enums.html#defining-members
            annotation=bool,  # Each flag acts as a boolean
            default=False,  # Default to False (not included in combination)
            required=False,  # All flags are optional
        )
    return out


def get_field_infos(hint) -> dict[str, FieldInfo]:
    # Early return for builtin types (int, str, etc.) to avoid expensive introspection.
    # Provides ~5-6x speedup for argument parsing by skipping signature_parameters() calls.
    if is_builtin(hint):
        return {}

    # Pydantic secret types (SecretStr, SecretBytes) should be treated as simple types
    if is_pydantic_secret(hint):
        return {}

    # NewType is a runtime identity function that returns its argument unchanged.
    # Use the field_infos of the underlying supertype instead of NewType's misleading __init__.
    if hasattr(hint, "__supertype__"):
        return get_field_infos(hint.__supertype__)

    if is_dataclass(hint):
        # This must be before ``is_pydantic`` check so that we
        # can handle pydantic dataclasses as vanilla dataclasses.
        return _dataclass_field_infos(hint)
    elif is_pydantic(hint):
        return _pydantic_field_infos(hint)
    elif is_namedtuple(hint):
        return _namedtuple_field_infos(hint)
    elif is_typeddict(hint):
        return _typed_dict_field_infos(hint)
    elif is_attrs(hint):
        return _attrs_field_infos(hint)
    elif is_enum_flag(hint):
        return _enum_flag_field_infos(hint)
    else:
        return _generic_class_field_infos(hint)


def signature_parameters(f: Any) -> dict[str, FieldInfo]:
    if "functools" in sys.modules:
        from functools import partial

        func = f.func if isinstance(f, partial) else f
    else:
        func = f

    type_hints = get_type_hints(func, include_extras=True)

    out = {}
    for name, iparam in inspect.signature(f).parameters.items():
        annotation = type_hints.get(name, iparam.annotation)
        out[name] = FieldInfo.from_iparam(iparam, annotation=annotation)
    return out
