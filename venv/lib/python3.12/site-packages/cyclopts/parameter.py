import collections.abc
import inspect
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from copy import deepcopy
from typing import (  # noqa: UP035
    Any,
    List,
    Tuple,
    TypeVar,
    cast,
    get_args,
    get_origin,
)

import attrs
from attrs import define, field

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

import cyclopts._env_var
from cyclopts._convert import ITERABLE_TYPES
from cyclopts.annotations import (
    NoneType,
    is_annotated,
    is_nonetype,
    is_union,
    resolve,
    resolve_annotated,
    resolve_optional,
)
from cyclopts.field_info import get_field_infos, signature_parameters
from cyclopts.group import Group
from cyclopts.utils import (
    default_name_transform,
    frozen,
    optional_to_tuple_converter,
    record_init,
    to_tuple_converter,
)

ITERATIVE_BOOL_IMPLICIT_VALUE = frozenset(
    {
        Iterable[bool],
        Sequence[bool],
        collections.abc.Sequence[bool],
        list[bool],
        List[bool],  # noqa: UP006
        tuple[bool, ...],
        Tuple[bool, ...],  # noqa: UP006
    }
)


T = TypeVar("T")

_NEGATIVE_FLAG_TYPES = frozenset([bool, None, NoneType, *ITERABLE_TYPES, *ITERATIVE_BOOL_IMPLICIT_VALUE])


def _not_hyphen_validator(instance, attribute, values):
    for value in values:
        if value is not None and value.startswith("-"):
            raise ValueError(f'{attribute.alias} value must NOT start with "-".')


def _negative_converter(default: tuple[str, ...]):
    def converter(value) -> tuple[str, ...]:
        if value is None:
            return default
        else:
            return to_tuple_converter(value)

    return converter


def _parse_converter(value):
    """Convert string patterns to compiled regex, pass through other types.

    Note: re.compile() internally caches compiled patterns, so no additional
    caching is needed here.
    """
    if isinstance(value, str):
        return re.compile(value)
    return value


@record_init("_provided_args")
@frozen
class Parameter:
    """Cyclopts configuration for individual function parameters with :obj:`~typing.Annotated`.

    Example usage:

    .. code-block:: python

        from cyclopts import app, Parameter
        from typing import Annotated

        app = App()


        @app.default
        def main(foo: Annotated[int, Parameter(name="bar")]):
            print(foo)


        app()

    .. code-block:: console

        $ my-script 100
        100

        $ my-script --bar 100
        100
    """

    # All attribute docstrings has been moved to ``docs/api.rst`` for greater control with attrs.

    # This can ONLY ever be a Tuple[str, ...]
    # Usually starts with "--" or "-"
    name: None | str | Iterable[str] = field(
        default=None,
        converter=lambda x: cast(tuple[str, ...], to_tuple_converter(x)),
    )

    # Accepts regular converters (type, tokens) -> Any, bound methods (tokens) -> Any, or string references
    converter: Callable[..., Any] | str | None = field(
        default=None,
        kw_only=True,
    )

    # This can ONLY ever be a Tuple[Callable, ...]
    validator: None | Callable[[Any, Any], Any] | Iterable[Callable[[Any, Any], Any]] = field(
        default=(),
        converter=lambda x: cast(tuple[Callable[[Any, Any], Any], ...], to_tuple_converter(x)),
        kw_only=True,
    )

    # This can ONLY ever be a Tuple[str, ...]
    alias: None | str | Iterable[str] = field(
        default=None,
        converter=lambda x: cast(tuple[str, ...], to_tuple_converter(x)),
        kw_only=True,
    )

    # This can ONLY ever be ``None`` or ``Tuple[str, ...]``
    negative: None | str | Iterable[str] = field(
        default=None,
        converter=optional_to_tuple_converter,
        kw_only=True,
    )

    # This can ONLY ever be a Tuple[Union[Group, str], ...]
    group: None | Group | str | Iterable[Group | str] = field(
        default=None,
        converter=to_tuple_converter,
        kw_only=True,
        hash=False,
    )

    parse: bool | re.Pattern | None = field(
        default=None,
        converter=_parse_converter,
        kw_only=True,
    )

    _show: bool | None = field(
        default=None,
        alias="show",
        kw_only=True,
    )

    show_default: None | bool | Callable[[Any], Any] = field(
        default=None,
        kw_only=True,
    )

    show_choices: bool = field(
        default=None,
        converter=attrs.converters.default_if_none(True),
        kw_only=True,
    )

    help: str | None = field(default=None, kw_only=True)

    show_env_var: bool = field(
        default=None,
        converter=attrs.converters.default_if_none(True),
        kw_only=True,
    )

    # This can ONLY ever be a Tuple[str, ...]
    env_var: None | str | Iterable[str] = field(
        default=None,
        converter=lambda x: cast(tuple[str, ...], to_tuple_converter(x)),
        kw_only=True,
    )

    env_var_split: Callable = field(
        default=cyclopts._env_var.env_var_split,
        kw_only=True,
    )

    # This can ONLY ever be a Tuple[str, ...]
    negative_bool: None | str | Iterable[str] = field(
        default=None,
        converter=_negative_converter(("no-",)),
        validator=_not_hyphen_validator,
        kw_only=True,
    )

    # This can ONLY ever be a Tuple[str, ...]
    negative_iterable: None | str | Iterable[str] = field(
        default=None,
        converter=_negative_converter(("empty-",)),
        validator=_not_hyphen_validator,
        kw_only=True,
    )

    # This can ONLY ever be a Tuple[str, ...]
    negative_none: None | str | Iterable[str] = field(
        default=None,
        converter=_negative_converter(()),
        validator=_not_hyphen_validator,
        kw_only=True,
    )

    required: bool | None = field(
        default=None,
        kw_only=True,
    )

    allow_leading_hyphen: bool = field(
        default=False,
        kw_only=True,
    )

    _name_transform: Callable[[str], str] | None = field(
        alias="name_transform",
        default=None,
        kw_only=True,
    )

    accepts_keys: bool | None = field(
        default=None,
        kw_only=True,
    )

    consume_multiple: bool = field(
        default=None,
        converter=attrs.converters.default_if_none(False),
        kw_only=True,
    )

    json_dict: bool | None = field(default=None, kw_only=True)

    json_list: bool | None = field(default=None, kw_only=True)

    count: bool = field(
        default=None,
        converter=attrs.converters.default_if_none(False),
        kw_only=True,
    )

    n_tokens: int | None = field(
        default=None,
        kw_only=True,
    )

    # Populated by the record_attrs_init_args decorator.
    _provided_args: tuple[str, ...] = field(factory=tuple, init=False, eq=False)

    @property
    def show(self) -> bool | None:
        if self._show is not None:
            return self._show
        if self.parse is None or isinstance(self.parse, re.Pattern):
            return None  # For regex or None, let Argument.show handle it
        return bool(self.parse)

    @property
    def name_transform(self):
        return self._name_transform if self._name_transform else default_name_transform

    def get_negatives(self, type_) -> tuple[str, ...]:
        if self.count and self.negative is None:
            return ()

        type_ = resolve_annotated(type_)
        if is_union(type_):
            union_args = get_args(type_)
            # Sort union members by priority: non-None types first, then None/NoneType
            # This ensures that if bool | None both produce the same custom negative,
            # we only include it once from the higher-priority type (bool).
            sorted_args = sorted(union_args, key=lambda x: (is_nonetype(x) or x is None))
            out: list[str] = []
            for x in sorted_args:
                for neg in self.get_negatives(x):
                    if neg not in out:
                        out.append(neg)
            return tuple(out)

        origin = get_origin(type_)

        if type_ not in _NEGATIVE_FLAG_TYPES:
            if origin:
                if origin not in _NEGATIVE_FLAG_TYPES:
                    return ()
            else:
                return ()

        out, user_negatives = [], []
        if self.negative:
            for negative in self.negative:
                (out if negative.startswith("-") else user_negatives).append(negative)

            if not user_negatives:
                return tuple(out)

        assert isinstance(self.name, tuple)
        for name in self.name:
            if not name.startswith("--"):  # Only provide negation for option-like long flags.
                continue
            name = name[2:]
            name_components = name.split(".")

            if type_ is bool or type_ in ITERATIVE_BOOL_IMPLICIT_VALUE:
                negative_prefixes = self.negative_bool
            elif is_nonetype(type_) or type_ is None:
                negative_prefixes = self.negative_none
            else:
                negative_prefixes = self.negative_iterable
            name_prefix = ".".join(name_components[:-1])
            if name_prefix:
                name_prefix += "."
            assert isinstance(negative_prefixes, tuple)
            if self.negative is None:
                for negative_prefix in negative_prefixes:
                    if negative_prefix:
                        out.append(f"--{name_prefix}{negative_prefix}{name_components[-1]}")
            else:
                for negative in user_negatives:
                    out.append(f"--{name_prefix}{negative}")
        return tuple(out)

    def __repr__(self):
        """Only shows non-default values."""
        content = ", ".join(
            [
                f"{a.alias}={getattr(self, a.name)!r}"
                for a in self.__attrs_attrs__  # pyright: ignore[reportAttributeAccessIssue]
                if a.alias in self._provided_args
            ]
        )
        return f"{type(self).__name__}({content})"

    @classmethod
    def combine(cls, *parameters: "Parameter | None") -> "Parameter":
        """Returns a new Parameter with combined values of all provided ``parameters``.

        Parameters
        ----------
        *parameters : Parameter | None
             Parameters who's attributes override ``self`` attributes.
             Ordered from least-to-highest attribute priority.
        """
        kwargs = {}
        filtered = [x for x in parameters if x is not None]
        # In the common case of 0/1 parameters to combine, we can avoid
        # instantiating a new Parameter object.
        if len(filtered) == 1:
            return filtered[0]
        elif not filtered:
            return EMPTY_PARAMETER

        for parameter in filtered:
            for alias in parameter._provided_args:
                kwargs[alias] = getattr(parameter, _parameter_alias_to_name[alias])

        return cls(**kwargs)

    @classmethod
    def default(cls) -> Self:
        """Create a Parameter with all Cyclopts-default values.

        This is different than just :class:`Parameter` because the default
        values will be recorded and override all upstream parameter values.
        """
        return cls(
            **{a.alias: a.default for a in cls.__attrs_attrs__ if a.init}  # pyright: ignore[reportAttributeAccessIssue]
        )

    @classmethod
    def from_annotation(cls, type_: Any, *default_parameters: "Parameter | None") -> tuple[Any, "Parameter"]:
        """Resolve the immediate Parameter from a type hint."""
        if type_ is inspect.Parameter.empty:
            if default_parameters:
                return type_, cls.combine(*default_parameters)
            else:
                return type_, EMPTY_PARAMETER
        else:
            type_, parameters = get_parameters(type_)
            return type_, cls.combine(*default_parameters, *parameters)

    def __call__(self, obj: T) -> T:
        """Decorator interface for annotating a function/class with a :class:`Parameter`.

        Most commonly used for directly configuring a class:

        .. code-block:: python

            @Parameter(...)
            class Foo: ...
        """
        if not hasattr(obj, "__cyclopts__"):
            obj.__cyclopts__ = CycloptsConfig(obj=obj)  # pyright: ignore[reportAttributeAccessIssue]
        elif obj.__cyclopts__.obj != obj:  # pyright: ignore[reportAttributeAccessIssue]
            # Create a copy so that children class Parameter decorators don't impact the parent.
            obj.__cyclopts__ = deepcopy(obj.__cyclopts__)  # pyright: ignore[reportAttributeAccessIssue]
        obj.__cyclopts__.parameters.append(self)  # pyright: ignore[reportAttributeAccessIssue]
        return obj


_parameter_alias_to_name = {
    p.alias: p.name
    for p in Parameter.__attrs_attrs__  # pyright: ignore[reportAttributeAccessIssue]
    if p.init
}

EMPTY_PARAMETER = Parameter()


def validate_command(f: Callable):
    """Validate if a function abides by Cyclopts's rules.

    Raises
    ------
    ValueError
        Function has naming or parameter/signature inconsistencies.
    """
    if (f.__module__ or "").startswith("cyclopts"):  # Speed optimization.
        return
    for field_info in signature_parameters(f).values():
        # Speed optimization: if no annotation and no cyclopts config, skip validation
        field_info_is_annotated = is_annotated(field_info.annotation)
        if not field_info_is_annotated and not getattr(field_info.annotation, "__cyclopts__", None):
            # There is no annotation, so there is nothing to validate.
            continue

        # Check both annotated parameters and classes with __cyclopts__ attribute
        _, cparam = Parameter.from_annotation(field_info.annotation)

        if cparam.parse is not None and not isinstance(cparam.parse, re.Pattern) and not cparam.parse:
            is_keyword_only = field_info.kind is field_info.KEYWORD_ONLY
            has_default = field_info.default is not field_info.empty
            if not (is_keyword_only or has_default):
                raise ValueError(
                    "Parameter.parse=False must be used with either a KEYWORD_ONLY function parameter "
                    "or a parameter with a default value."
                )

        # Check for Parameter(name="*") without a default value when ALL class fields are optional
        # This is confusing for CLI users who expect the dataclass to be instantiated automatically
        if (
            "*" in cparam.name  # pyright: ignore[reportOperatorIssue]
            and field_info.default is field_info.empty
        ):
            # Get field info for the class to check if all fields have defaults
            annotated = field_info.annotation
            annotated = resolve(annotated)
            class_field_infos = get_field_infos(annotated)
            all_fields_optional = all(not field_info.required for field_info in class_field_infos.values())

            if all_fields_optional:
                param_name = field_info.names[0] if field_info.names else ""
                quoted_param_name = f'"{param_name}" ' if param_name else ""
                raise ValueError(
                    f'Parameter {quoted_param_name}in function {f} has all optional values, uses Parameter(name="*"), but itself has no default value. '
                    "Consider either:\n"
                    f'    1) If immutable, providing a default value "{param_name}: {field_info.annotation.__name__} = {field_info.annotation.__name__}()"\n'
                    f'    2) Otherwise, declaring it optional like "{param_name}: {field_info.annotation.__name__} | None = None" and instanting the {param_name} object in the function body:\n'
                    f"           if {param_name} is None:\n"
                    f"               {param_name} = {field_info.annotation.__name__}()"
                )


def get_parameters(hint: T, skip_converter_params: bool = False) -> tuple[T, list[Parameter]]:
    """At root level, checks for cyclopts.Parameter annotations.

    Includes checking the ``__cyclopts__`` attribute on both the type and any converter functions.

    Parameters
    ----------
    hint
        Type hint to extract parameters from.
    skip_converter_params
        If True, skip extracting parameters from converter's __cyclopts__.
        Used to prevent infinite recursion in token_count.

    Returns
    -------
    hint
        Annotation hint with :obj:`Annotated` and :obj:`Optional` resolved.
    list[Parameter]
        List of parameters discovered, ordered by priority (lowest to highest):
        converter-decoration < type-decoration < annotation.
    """
    hint = resolve_optional(hint)

    # Extract parameters from Annotated metadata
    annotated_params = []
    if is_annotated(hint):
        inner = get_args(hint)
        hint = inner[0]
        annotated_params.extend(x for x in inner[1:] if isinstance(x, Parameter))
        # Resolve Optional again after unwrapping Annotated, since hint could be Type | None
        hint = resolve_optional(hint)

    # Extract parameters from type's __cyclopts__ attribute (after unwrapping Annotated)
    type_cyclopts_config_params = []
    if cyclopts_config := getattr(hint, "__cyclopts__", None):
        type_cyclopts_config_params.extend(cyclopts_config.parameters)

    # Check if any parameter has a converter with __cyclopts__ and extract its parameters
    converter_params = []
    if not skip_converter_params:
        for param in annotated_params + type_cyclopts_config_params:
            if param.converter:
                converter = param.converter

                # Resolve string converters to methods on the type
                if isinstance(converter, str):
                    converter = getattr(hint, converter)

                # Check for __cyclopts__ on the converter
                if hasattr(converter, "__cyclopts__"):
                    converter_params.extend(converter.__cyclopts__.parameters)
                    break
                # For bound methods from classmethods/staticmethods, access the descriptor via __self__
                elif (
                    hasattr(converter, "__self__")
                    and hasattr(converter, "__name__")
                    and hasattr(converter.__self__, "__dict__")
                ):
                    # Get the descriptor from the class's __dict__
                    descriptor = converter.__self__.__dict__.get(converter.__name__)
                    if descriptor and hasattr(descriptor, "__cyclopts__"):
                        converter_params.extend(descriptor.__cyclopts__.parameters)
                        break

    # Return parameters in priority order (lowest to highest)
    # This allows Parameter.combine() to correctly prioritize later parameters
    parameters = converter_params + type_cyclopts_config_params + annotated_params

    return hint, parameters


@define
class CycloptsConfig:
    """
    Intended for storing additional data to a ``__cyclopts__`` attribute via decoration.
    """

    obj: Any = None
    parameters: list[Parameter] = field(factory=list, init=False)
