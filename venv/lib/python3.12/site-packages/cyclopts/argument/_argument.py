"""Argument class and related functionality."""

import inspect
import json
import operator
import re
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from functools import partial, reduce
from typing import TYPE_CHECKING, Any, get_args, get_origin

from attrs import define, field

from cyclopts._convert import (
    ITERABLE_TYPES,
    _validate_json_extra_keys,
    convert,
    instantiate_from_dict,
    token_count,
)
from cyclopts.annotations import (
    contains_hint,
    is_attrs,
    is_dataclass,
    is_enum_flag,
    is_namedtuple,
    is_nonetype,
    is_pydantic,
    is_typeddict,
    is_union,
    resolve,
    resolve_annotated,
    resolve_optional,
)
from cyclopts.exceptions import (
    CoercionError,
    CycloptsError,
    MissingArgumentError,
    MixedArgumentError,
    RepeatArgumentError,
    ValidationError,
)
from cyclopts.field_info import (
    FieldInfo,
    _attrs_field_infos,
    _generic_class_field_infos,
    _pydantic_field_infos,
    _typed_dict_field_infos,
    get_field_infos,
    signature_parameters,
)
from cyclopts.parameter import ITERATIVE_BOOL_IMPLICIT_VALUE, Parameter
from cyclopts.token import Token
from cyclopts.utils import UNSET, grouper, is_builtin

from .utils import (
    enum_flag_from_dict,
    get_annotated_discriminator,
    get_choices_from_hint,
    missing_keys_factory,
    startswith,
)

if TYPE_CHECKING:
    from cyclopts.argument._collection import ArgumentCollection


@define(kw_only=True)
class Argument:
    """Encapsulates functionality and additional contextual information for parsing a parameter.

    An argument is defined as anything that would have its own entry in the help page.
    """

    tokens: list[Token] = field(factory=list)
    """
    List of :class:`.Token` parsed from various sources.
    Do not directly mutate; see :meth:`append`.
    """

    field_info: FieldInfo = field(factory=FieldInfo)
    """
    Additional information about the parameter from surrounding python syntax.
    """

    parameter: Parameter = field(factory=Parameter)
    """
    Fully resolved user-provided :class:`.Parameter`.
    """

    hint: Any = field(default=str, converter=resolve)
    """
    The type hint for this argument; may be different from :attr:`.FieldInfo.annotation`.
    """

    index: int | None = field(default=None)
    """
    Associated python positional index for argument.
    If ``None``, then cannot be assigned positionally.
    """

    keys: tuple[str, ...] = field(default=())
    """
    **Python** keys that lead to this leaf.

    ``self.parameter.name`` and ``self.keys`` can naively disagree!
    For example, a ``self.parameter.name="--foo.bar.baz"`` could be aliased to "--fizz".
    The resulting ``self.keys`` would be ``("bar", "baz")``.

    This is populated based on type-hints and class-structure, not ``Parameter.name``.

    .. code-block:: python

        from cyclopts import App, Parameter
        from dataclasses import dataclass
        from typing import Annotated

        app = App()


        @dataclass
        class User:
            id: int
            name: Annotated[str, Parameter(name="--fullname")]


        @app.default
        def main(user: User):
            pass


        for argument in app.assemble_argument_collection():
            print(f"name: {argument.name:16} hint: {str(argument.hint):16} keys: {str(argument.keys)}")

    .. code-block:: bash

        $ my-script
        name: --user.id        hint: <class 'int'>    keys: ('id',)
        name: --fullname       hint: <class 'str'>    keys: ('name',)
    """

    _value: Any = field(alias="value", default=UNSET)
    """
    Converted value from last :meth:`convert` call.
    This value may be stale if fields have changed since last :meth:`convert` call.
    :class:`.UNSET` if :meth:`convert` has not yet been called with tokens.
    """

    _accepts_keywords: bool = field(default=False, init=False, repr=False)

    _default: Any = field(default=None, init=False, repr=False)
    _lookup: dict[str, FieldInfo] = field(factory=dict, init=False, repr=False)

    children: "ArgumentCollection" = field(init=False, repr=False)
    """
    Collection of other :class:`Argument` that eventually culminate into the python variable represented by :attr:`field_info`.
    """

    _marked_converted: bool = field(default=False, init=False, repr=False)
    _mark_converted_override: bool = field(default=False, init=False, repr=False)

    _missing_keys_checker: Callable | None = field(default=None, init=False, repr=False)

    _internal_converter: Callable | None = field(default=None, init=False, repr=False)

    _enum_flag_type: Any | None = field(default=None, init=False, repr=False)

    def __attrs_post_init__(self):
        from cyclopts.argument._collection import ArgumentCollection

        self.children = ArgumentCollection()

        hint = resolve(self.hint)
        hints = get_args(hint) if is_union(hint) else (hint,)

        if self.parameter.count:
            # Perform type-annotation validation.
            resolved_hint = resolve_optional(hint)
            # Technically, bool is a subclass of int, so we need to explicitly check.
            if resolved_hint is bool or not (
                resolved_hint is int or (isinstance(resolved_hint, type) and issubclass(resolved_hint, int))
            ):
                raise ValueError(
                    f"Parameter(count=True) requires an int type hint, got {self.hint}. "
                    f"Use 'Annotated[int, Parameter(count=True)]' for counting flags."
                )

        if not self.parse:
            # Validate that non-parsed parameters are keyword-only or have defaults
            is_keyword_only = self.field_info.kind is self.field_info.KEYWORD_ONLY
            has_default = self.field_info.default is not self.field_info.empty
            if not (is_keyword_only or has_default):
                raise ValueError(
                    f"Non-parsed parameter '{self.field_info.name}' must be a KEYWORD_ONLY function parameter "
                    "or have a default value."
                )
            return

        if self.parameter.accepts_keys is False:
            return

        for hint in hints:
            origin = get_origin(hint)
            hint_origin = {hint, origin}

            field_infos = get_field_infos(hint)
            if dict in hint_origin:
                self._accepts_keywords = True
                key_type, val_type = str, str
                args = get_args(hint)
                with suppress(IndexError):
                    key_type = args[0]
                    val_type = args[1]
                if key_type is not str:
                    raise TypeError('Dictionary type annotations must have "str" keys.')
                self._default = val_type
            elif is_typeddict(hint):
                self._missing_keys_checker = missing_keys_factory(_typed_dict_field_infos)
                self._accepts_keywords = True
                self._update_lookup(field_infos)
            elif is_dataclass(hint):
                self._missing_keys_checker = missing_keys_factory(_generic_class_field_infos)
                self._accepts_keywords = True
                self._update_lookup(field_infos)
            elif is_namedtuple(hint):
                self._missing_keys_checker = missing_keys_factory(_generic_class_field_infos)
                self._accepts_keywords = True
                if not hasattr(hint, "__annotations__"):
                    raise ValueError("Cyclopts cannot handle collections.namedtuple without type annotations.")
                self._update_lookup(field_infos)
            elif is_attrs(hint):
                self._missing_keys_checker = missing_keys_factory(_attrs_field_infos)
                self._accepts_keywords = True
                self._update_lookup(field_infos)
            elif is_pydantic(hint):
                self._missing_keys_checker = missing_keys_factory(_pydantic_field_infos)
                self._accepts_keywords = True
                self._update_lookup(field_infos)
            elif is_enum_flag(hint):
                self._enum_flag_type = hint
                self._accepts_keywords = True
                self._update_lookup(field_infos)
            elif not is_builtin(hint) and field_infos:
                self._missing_keys_checker = missing_keys_factory(_generic_class_field_infos)
                self._accepts_keywords = True
                self._update_lookup(field_infos)
            elif self.parameter.accepts_keys is None:
                continue

            if self.parameter.accepts_keys is None:
                continue

            self._accepts_keywords = True
            self._missing_keys_checker = missing_keys_factory(_generic_class_field_infos)
            for i, field_info in enumerate(signature_parameters(hint.__init__).values()):
                if i == 0 and field_info.name == "self":
                    continue
                if field_info.kind is field_info.VAR_KEYWORD:
                    self._default = field_info.annotation
                else:
                    self._update_lookup({field_info.name: field_info})

    def _update_lookup(self, field_infos: dict[str, FieldInfo]):
        from typing import Literal

        discriminator = get_annotated_discriminator(self.field_info.annotation)

        for key, field_info in field_infos.items():
            if existing_field_info := self._lookup.get(key):
                if existing_field_info == field_info:
                    pass
                elif discriminator and discriminator in field_info.names and discriminator in existing_field_info.names:
                    existing_field_info.annotation = Literal[existing_field_info.annotation, field_info.annotation]
                    existing_field_info.default = FieldInfo.empty
                else:
                    raise NotImplementedError
            else:
                self._lookup[key] = field_info

    @property
    def value(self):
        """Converted value from last :meth:`convert` call.

        This value may be stale if fields have changed since last :meth:`convert` call.
        :class:`.UNSET` if :meth:`convert` has not yet been called with tokens.
        """
        return self._value

    @value.setter
    def value(self, val):
        if self._marked:
            self._mark_converted_override = True
        self._marked = True
        self._value = val

    @property
    def _marked(self):
        """If ``True``, then this node in the tree has already been converted and ``value`` has been populated."""
        return self._marked_converted | self._mark_converted_override

    @_marked.setter
    def _marked(self, value: bool):
        self._marked_converted = value

    @property
    def _accepts_arbitrary_keywords(self) -> bool:
        args = get_args(self.hint) if is_union(self.hint) else (self.hint,)
        return any(dict in (arg, get_origin(arg)) for arg in args)

    @property
    def show_default(self) -> bool | Callable[[Any], str]:
        """Show the default value on the help page."""
        if self.required:
            return False
        elif self.parameter.show_default is None:
            return self.field_info.default not in (None, self.field_info.empty)
        elif (self.field_info.default is self.field_info.empty) or not self.parameter.show_default:
            return False
        else:
            return self.parameter.show_default

    @property
    def _use_pydantic_type_adapter(self) -> bool:
        return bool(
            is_pydantic(self.hint)
            or (
                is_union(self.hint)
                and (
                    any(is_pydantic(x) for x in get_args(self.hint))
                    or get_annotated_discriminator(self.field_info.annotation)
                )
            )
        )

    def _type_hint_for_key(self, key: str):
        try:
            return self._lookup[key].annotation
        except KeyError:
            if self._default is None:
                raise
            return self._default

    def _should_attempt_json_dict(self, tokens: Sequence[Token | str] | None = None) -> bool:
        """When parsing, should attempt to parse the token(s) as json dict data."""
        if tokens is None:
            tokens = self.tokens
        if not tokens:
            return False
        value = tokens[0].value if isinstance(tokens[0], Token) else tokens[0]
        if not value.strip().startswith("{"):
            return False

        if self._accepts_keywords:
            if self.parameter.json_dict is not None:
                return self.parameter.json_dict
            if contains_hint(self.field_info.annotation, str):
                return False
            return True

        hint = resolve(self.hint)
        origin = get_origin(hint)
        if origin in ITERABLE_TYPES:
            args = get_args(hint)
            if args and args[0] is not str:
                return True

        return False

    def _should_attempt_json_list(
        self, tokens: Sequence[Token | str] | Token | str | None = None, keys: tuple[str, ...] = ()
    ) -> bool:
        """When parsing, should attempt to parse the token(s) as json list data."""
        if tokens is None:
            tokens = self.tokens
        if not tokens:
            return False
        _, consume_all = self.token_count(keys)
        if not consume_all:
            return False
        if isinstance(tokens, Token):
            value = tokens.value
        elif isinstance(tokens, str):
            value = tokens
        else:
            value = tokens[0].value if isinstance(tokens[0], Token) else tokens[0]
        if not value.strip().startswith("["):
            return False
        if self.parameter.json_list is not None:
            return self.parameter.json_list
        for arg in get_args(self.field_info.annotation) or (str,):
            if contains_hint(arg, str):
                return False
        return True

    def match(
        self,
        term: str | int,
        *,
        transform: Callable[[str], str] | None = None,
        delimiter: str = ".",
    ) -> tuple[tuple[str, ...], Any]:
        """Match a name search-term, or a positional integer index.

        Raises
        ------
        ValueError
            If no match is found.

        Returns
        -------
        tuple[str, ...]
            Leftover keys after matching to this argument.
            Used if this argument accepts_arbitrary_keywords.
        Any
            Implicit value.
            :obj:`~.UNSET` if no implicit value is applicable.
        """
        if not self.parse:
            raise ValueError
        return (
            self._match_index(term)
            if isinstance(term, int)
            else self._match_name(term, transform=transform, delimiter=delimiter)
        )

    def _match_name(
        self,
        term: str,
        *,
        transform: Callable[[str], str] | None = None,
        delimiter: str = ".",
    ) -> tuple[tuple[str, ...], Any]:
        """Check how well this argument matches a token keyword identifier.

        Parameters
        ----------
        term: str
            Something like "--foo"
        transform: Callable
            Function that converts the cyclopts Parameter name(s) into
            something that should be compared against ``term``.

        Raises
        ------
        ValueError
            If no match found.

        Returns
        -------
        tuple[str, ...]
            Leftover keys after matching to this argument.
            Used if this argument accepts_arbitrary_keywords.
        Any
            Implicit value.
        """
        if self.field_info.kind is self.field_info.VAR_KEYWORD:
            return tuple(term.lstrip("-").split(delimiter)), UNSET

        trailing = term
        implicit_value = UNSET

        assert self.parameter.name
        for name in self.parameter.name:
            if transform:
                name = transform(name)
            if startswith(term, name):
                trailing = term[len(name) :]
                implicit_value = True if self.hint is bool or self.hint in ITERATIVE_BOOL_IMPLICIT_VALUE else UNSET
                if trailing:
                    if trailing[0] == delimiter:
                        trailing = trailing[1:]
                        break
                else:
                    return (), implicit_value
        else:
            hint = resolve_annotated(self.field_info.annotation)
            if is_union(hint):
                hints = get_args(hint)
            else:
                hints = (hint,)
            for hint in hints:
                hint = resolve_annotated(hint)
                double_break = False
                for name in self.parameter.get_negatives(hint):
                    if transform:
                        name = transform(name)
                    if startswith(term, name):
                        trailing = term[len(name) :]
                        if hint in ITERATIVE_BOOL_IMPLICIT_VALUE:
                            implicit_value = False
                        elif is_nonetype(hint) or hint is None:
                            implicit_value = None
                        else:
                            hint = resolve_optional(hint)
                            implicit_value = (get_origin(hint) or hint)()
                        if trailing:
                            if trailing[0] == delimiter:
                                trailing = trailing[1:]
                                double_break = True
                                break
                        else:
                            return (), implicit_value
                if double_break:
                    break
            else:
                raise ValueError

        if not self._accepts_arbitrary_keywords:
            raise ValueError

        return tuple(trailing.split(delimiter)), implicit_value

    def _match_index(self, index: int) -> tuple[tuple[str, ...], Any]:
        if self.index is None:
            raise ValueError
        elif self.field_info.kind is self.field_info.VAR_POSITIONAL:
            if index < self.index:
                raise ValueError
        elif index != self.index:
            raise ValueError
        return (), UNSET

    def append(self, token: Token):
        """Safely add a :class:`Token`."""
        if not self.parse:
            raise ValueError

        if any(x.address == token.address for x in self.tokens):
            _, consume_all = self.token_count(token.keys)
            if not consume_all and not self.parameter.count:
                raise RepeatArgumentError(token=token)

        if self.tokens:
            if bool(token.keys) ^ any(x.keys for x in self.tokens):
                raise MixedArgumentError(argument=self)
        self.tokens.append(token)

    @property
    def has_tokens(self) -> bool:
        """This argument, or a child argument, has at least 1 parsed token."""  # noqa: D404
        return bool(self.tokens) or any(x.has_tokens for x in self.children)

    @property
    def children_recursive(self) -> "ArgumentCollection":
        from cyclopts.argument._collection import ArgumentCollection

        out = ArgumentCollection()
        for child in self.children:
            out.append(child)
            out.extend(child.children_recursive)
        return out

    def _convert_pydantic(self):
        if self.has_tokens:
            import pydantic

            unstructured_data = self._json()
            try:
                return pydantic.TypeAdapter(self.field_info.annotation).validate_python(unstructured_data)
            except pydantic.ValidationError as e:
                self._handle_pydantic_validation_error(e)
        else:
            return UNSET

    def _convert(self, converter: Callable | None = None):
        from cyclopts.argument._collection import update_argument_collection

        if self.parameter.converter:
            # Resolve string converters to methods on the type
            if isinstance(self.parameter.converter, str):
                converter = getattr(self.hint, self.parameter.converter)
            else:
                converter = self.parameter.converter
        elif converter is None:
            converter = partial(convert, name_transform=self.parameter.name_transform)

        assert converter is not None  # Ensure converter is set at this point

        def safe_converter(hint, tokens):
            if isinstance(tokens, dict):
                try:
                    return converter(hint, tokens)  # pyright: ignore
                except (AssertionError, ValueError, TypeError) as e:
                    raise CoercionError(msg=e.args[0] if e.args else None, argument=self, target_type=hint) from e
            else:
                try:
                    # Detect bound methods (classmethods/instance methods)
                    if inspect.ismethod(converter):
                        # Call with just tokens - cls/self already bound
                        return converter(tokens)  # pyright: ignore[reportCallIssue]
                    else:
                        # Regular function - pass type and tokens
                        return converter(hint, tokens)  # pyright: ignore[reportCallIssue]
                except (AssertionError, ValueError, TypeError) as e:
                    token = tokens[0] if len(tokens) == 1 else None
                    raise CoercionError(
                        msg=e.args[0] if e.args else None, argument=self, target_type=hint, token=token
                    ) from e

        if not self.parse:
            out = UNSET
        elif self.parameter.count:
            out = sum(token.implicit_value for token in self.tokens if token.implicit_value is not UNSET)
        elif not self.children:
            positional: list[Token] = []
            keyword = {}

            def expand_tokens(tokens):
                for token in tokens:
                    if self._should_attempt_json_list(token):
                        try:
                            parsed_json = json.loads(token.value)
                        except json.JSONDecodeError as e:
                            raise CoercionError(token=token, target_type=self.hint) from e

                        if not isinstance(parsed_json, list):
                            raise CoercionError(token=token, target_type=self.hint)

                        if not parsed_json:
                            yield token.evolve(value="", implicit_value=[])
                        else:
                            for element in parsed_json:
                                if element is None:
                                    yield token.evolve(value="", implicit_value=element)
                                elif isinstance(element, dict):
                                    yield token.evolve(value=json.dumps(element))
                                else:
                                    yield token.evolve(value=str(element))
                    else:
                        yield token

            expanded_tokens = list(expand_tokens(self.tokens))
            for token in expanded_tokens:
                resolved_hint = resolve_optional(self.hint)
                if token.implicit_value is not UNSET and isinstance(
                    token.implicit_value, get_origin(resolved_hint) or resolved_hint
                ):
                    assert len(expanded_tokens) == 1
                    return token.implicit_value

                if token.keys:
                    lookup = keyword
                    for key in token.keys[:-1]:
                        lookup = lookup.setdefault(key, {})
                    lookup.setdefault(token.keys[-1], []).append(token)
                else:
                    positional.append(token)

                if positional and keyword:  # pragma: no cover
                    raise MixedArgumentError(argument=self)

            if positional:
                if self.field_info and self.field_info.kind is self.field_info.VAR_POSITIONAL:
                    hint = get_args(self.hint)[0]
                    tokens_per_element, _ = self.token_count()
                    out = tuple(safe_converter(hint, values) for values in grouper(positional, tokens_per_element))
                else:
                    out = safe_converter(self.hint, tuple(positional))
            elif keyword:
                if self.field_info and self.field_info.kind is self.field_info.VAR_KEYWORD and not self.keys:
                    out = {key: safe_converter(get_args(self.hint)[1], value) for key, value in keyword.items()}
                else:
                    out = safe_converter(self.hint, keyword)
            elif self.required:
                raise MissingArgumentError(argument=self)
            else:
                return UNSET
        else:
            data = {}
            out = UNSET

            if self._enum_flag_type:
                out = self._enum_flag_type(0)

            if self._enum_flag_type and self.tokens:
                converted_flags = safe_converter(self._enum_flag_type, self.tokens)
                out |= reduce(operator.or_, converted_flags) if isinstance(converted_flags, list) else converted_flags

            if self._should_attempt_json_dict():
                while self.tokens:
                    token = self.tokens.pop(0)
                    try:
                        parsed_json = json.loads(token.value)
                    except json.JSONDecodeError as e:
                        raise CoercionError(token=token, target_type=self.hint) from e
                    _validate_json_extra_keys(parsed_json, self.hint, token)
                    update_argument_collection(
                        {self.name.lstrip("-"): parsed_json},
                        token.source,
                        self.children_recursive,
                        root_keys=(),
                        allow_unknown=False,
                    )

            if self._use_pydantic_type_adapter:
                return self._convert_pydantic()

            if self.tokens and not self._enum_flag_type:
                positional_tokens = [token for token in self.tokens if not token.keys]
                if positional_tokens:
                    return safe_converter(self.hint, tuple(positional_tokens))

            for child in self.children:
                assert len(child.keys) == (len(self.keys) + 1)
                if child.has_tokens:
                    data[child.keys[-1]] = child.convert_and_validate(converter=converter)
                elif child.required:
                    obj = data
                    for k in child.keys:
                        try:
                            obj = obj[k]
                        except Exception:
                            raise MissingArgumentError(argument=child) from None
                    child._marked = True

            self._run_missing_keys_checker(data)

            if self._enum_flag_type:
                out |= enum_flag_from_dict(self._enum_flag_type, data, self.parameter.name_transform)
                if not out:
                    out = UNSET
            elif data:
                out = instantiate_from_dict(self.hint, data)
            elif self.required:
                raise MissingArgumentError(argument=self)  # pragma: no cover
            else:
                out = UNSET

        return out

    def convert(self, converter: Callable | None = None):
        """Converts :attr:`tokens` into :attr:`value`.

        Parameters
        ----------
        converter: Callable | None
            Converter function to use. Overrides ``self.parameter.converter``

        Returns
        -------
        Any
            The converted data. Same as :attr:`value`.
        """
        if not self._marked:
            try:
                self.value = self._convert(converter=converter)
            except CoercionError as e:
                if e.argument is None:
                    e.argument = self
                if e.target_type is None:
                    e.target_type = self.hint
                raise
            except CycloptsError as e:
                if e.argument is None:
                    e.argument = self
                raise

        return self.value

    def validate(self, value):
        """Validates provided value.

        Parameters
        ----------
        value:
            Value to validate.

        Returns
        -------
        Any
            The converted data. Same as :attr:`value`.
        """
        assert isinstance(self.parameter.validator, tuple)

        if "pydantic" in sys.modules:
            import pydantic

            pydantic_version = tuple(int(x) for x in pydantic.__version__.split("."))
            if pydantic_version < (2,):
                pydantic = None
        else:
            pydantic = None

        def validate_pydantic(hint, val):
            if not pydantic:
                return
            if self._use_pydantic_type_adapter:
                return

            try:
                pydantic.TypeAdapter(hint).validate_python(val)
            except pydantic.ValidationError as e:
                self._handle_pydantic_validation_error(e)
            except pydantic.PydanticUserError:
                pass

        try:
            if not self.keys and self.field_info and self.field_info.kind is self.field_info.VAR_KEYWORD:
                hint = get_args(self.hint)[1]
                for validator in self.parameter.validator:
                    for val in value.values():
                        validator(hint, val)
                validate_pydantic(dict[str, self.field_info.annotation], value)
            elif self.field_info and self.field_info.kind is self.field_info.VAR_POSITIONAL:
                hint = get_args(self.hint)[0]
                for validator in self.parameter.validator:
                    for val in value:
                        validator(hint, val)
                validate_pydantic(tuple[self.field_info.annotation, ...], value)
            else:
                for validator in self.parameter.validator:
                    validator(self.hint, value)
                validate_pydantic(self.field_info.annotation, value)
        except (AssertionError, ValueError, TypeError) as e:
            raise ValidationError(exception_message=e.args[0] if e.args else "", argument=self) from e

    def convert_and_validate(self, converter: Callable | None = None):
        """Converts and validates :attr:`tokens` into :attr:`value`.

        Parameters
        ----------
        converter: Callable | None
            Converter function to use. Overrides ``self.parameter.converter``

        Returns
        -------
        Any
            The converted data. Same as :attr:`value`.
        """
        val = self.convert(converter=converter)
        if val is not UNSET:
            self.validate(val)
        elif self.field_info.default is not FieldInfo.empty:
            self.validate(self.field_info.default)
        return val

    def token_count(self, keys: tuple[str, ...] = ()):
        """The number of string tokens this argument consumes.

        Parameters
        ----------
        keys: tuple[str, ...]
            The **python** keys into this argument.
            If provided, returns the number of string tokens that specific
            data type within the argument consumes.

        Returns
        -------
        int
            Number of string tokens to create 1 element.
        consume_all: bool
            :obj:`True` if this data type is iterable.
        """
        if self.parameter.count:
            return 0, False

        # Check for explicit n_tokens override
        # This applies to values at any level: root values (keys=()) or nested values (keys=(...))
        # For example, **kwargs: Annotated[str, Parameter(n_tokens=2)] means each kwarg value needs 2 tokens
        if self.parameter.n_tokens is not None:
            if self.parameter.n_tokens == -1:
                return 1, True
            else:
                # Determine consume_all based on the hint at the requested level
                # by recursively calling token_count on the hint
                if len(keys) > 1:
                    hint = self._default
                elif len(keys) == 1:
                    hint = self._type_hint_for_key(keys[0])
                else:
                    hint = self.hint

                # Recursively call token_count to get the consume_all behavior
                # We ignore the token count from the recursive call and use our explicit n_tokens
                _, consume_all_from_type = token_count(hint)
                return self.parameter.n_tokens, consume_all_from_type

        if len(keys) > 1:
            hint = self._default
        elif len(keys) == 1:
            hint = self._type_hint_for_key(keys[0])
        else:
            hint = self.hint
            if self._enum_flag_type and not keys:
                return 1, True
        tokens_per_element, consume_all = token_count(hint)
        return tokens_per_element, consume_all

    @property
    def negatives(self):
        """Negative flags from :meth:`.Parameter.get_negatives`."""
        return self.parameter.get_negatives(resolve_annotated(self.field_info.annotation))

    @property
    def name(self) -> str:
        """The **first** provided name this argument goes by."""
        return self.names[0]

    @property
    def names(self) -> tuple[str, ...]:
        """Names the argument goes by (both positive and negative)."""
        import itertools

        assert isinstance(self.parameter.name, tuple)
        return tuple(itertools.chain(self.parameter.name, self.negatives))

    def env_var_split(self, value: str, delimiter: str | None = None) -> list[str]:
        """Split a given value with :meth:`.Parameter.env_var_split`."""
        return self.parameter.env_var_split(self.hint, value, delimiter=delimiter)

    @property
    def show(self) -> bool:
        """Show this argument on the help page.

        If an argument has child arguments, don't show it on the help-page.
        Returns False for arguments that won't be parsed (including underscore-prefixed params).
        """
        if self.children:
            return False
        if self.parameter.show is not None:
            # User explicitly set show
            return self.parameter.show
        # Default to whether this argument is parsed
        return self.parse

    @property
    def parse(self) -> bool:
        """Whether this argument should be parsed from CLI tokens.

        If ``Parameter.parse`` is a regex pattern, parse if the pattern matches
        the field name; otherwise don't parse.
        """
        if self.parameter.parse is None:
            return True
        if isinstance(self.parameter.parse, re.Pattern):
            return bool(self.parameter.parse.search(self.field_info.name))
        return bool(self.parameter.parse)

    @property
    def required(self) -> bool:
        """Whether or not this argument requires a user-provided value."""
        if self.parameter.required is None:
            return self.field_info.required
        else:
            return self.parameter.required

    def is_positional_only(self) -> bool:
        return self.field_info.is_positional_only

    def is_var_positional(self) -> bool:
        return self.field_info.kind == self.field_info.VAR_POSITIONAL

    def is_flag(self) -> bool:
        """Check if this argument is a flag (consumes no CLI tokens).

        Flags are arguments that don't consume command-line tokens after the option name.
        They typically have implicit values (e.g., `--verbose` for bool, `--no-items` for list).

        Returns
        -------
        bool
            True if the argument consumes zero tokens from the command line.

        Examples
        --------
        >>> from cyclopts import Parameter
        >>> bool_arg = Argument(hint=bool, parameter=Parameter(name="--verbose"))
        >>> bool_arg.is_flag()
        True
        >>> str_arg = Argument(hint=str, parameter=Parameter(name="--name"))
        >>> str_arg.is_flag()
        False
        """
        return self.token_count() == (0, False)

    def get_choices(self, force: bool = False) -> tuple[str, ...] | None:
        """Extract completion choices from type hint.

        Extracts choices from Literal types, Enum types, and Union types containing them.
        Respects the Parameter.show_choices setting unless force=True.

        Parameters
        ----------
        force : bool
            If True, return choices even when show_choices=False.
            Used by shell completion to always provide choices.

        Returns
        -------
        tuple[str, ...] | None
            Tuple of choice strings if choices exist and should be shown, None otherwise.

        Examples
        --------
        >>> argument = Argument(hint=Literal["dev", "staging", "prod"], parameter=Parameter(show_choices=True))
        >>> argument.get_choices()
        ('dev', 'staging', 'prod')
        >>> argument = Argument(hint=Literal["dev", "staging", "prod"], parameter=Parameter(show_choices=False))
        >>> argument.get_choices()  # Returns None for help text
        >>> argument.get_choices(force=True)  # Returns choices for completion
        ('dev', 'staging', 'prod')
        """
        if not force and not self.parameter.show_choices:
            return None
        choices = get_choices_from_hint(self.hint, self.parameter.name_transform)
        return tuple(choices) if choices else None

    def _json(self) -> dict:
        """Convert argument to be json-like for pydantic.

        All values will be str/list/dict. JSON-serialized strings (from sources
        like config files or environment variables) are deserialized back to their
        original dict/list structure.
        """
        out = {}
        if self._accepts_keywords:
            for token in self.tokens:
                node = out
                for key in token.keys[:-1]:
                    node = node.setdefault(key, {})
                node[token.keys[-1]] = token.value if token.implicit_value is UNSET else token.implicit_value
        for child in self.children:
            child._marked = True
            if not child.has_tokens:
                continue
            keys = child.keys[len(self.keys) :]
            if child._accepts_keywords:
                result = child._json()
                if result:
                    out[keys[0]] = result
            elif (get_origin(child.hint) or child.hint) in ITERABLE_TYPES:
                for token in child.tokens:
                    if token.implicit_value is not UNSET:
                        out.setdefault(keys[-1], []).extend(token.implicit_value)
                    else:
                        value = token.value
                        # Deserialize JSON strings (from update_argument_collection) back to dict/list
                        if isinstance(value, str) and value.strip() and value.strip()[0] in ("{", "["):
                            try:
                                value = json.loads(value)
                            except json.JSONDecodeError:
                                pass
                        out.setdefault(keys[-1], []).append(value)
            else:
                token = child.tokens[0]
                out[keys[0]] = token.value if token.implicit_value is UNSET else token.implicit_value
        return out

    def _run_missing_keys_checker(self, data):
        if not self._missing_keys_checker or (not self.required and not data):
            return
        if not (missing_keys := self._missing_keys_checker(self, data)):
            return
        missing_key = missing_keys[0]
        keys = self.keys + (missing_key,)
        missing_arguments = self.children.filter_by(keys_prefix=keys)
        if missing_arguments:
            raise MissingArgumentError(argument=missing_arguments[0])
        else:
            missing_description = self.field_info.names[0] + "->" + "->".join(keys)
            raise ValueError(
                f'Required field "{missing_description}" is not accessible by Cyclopts; possibly due to conflicting POSITIONAL/KEYWORD requirements.'
            )

    def _handle_pydantic_validation_error(self, exc):
        import pydantic

        error = exc.errors()[0]
        if error["type"] == "missing":
            # Try normal lookup first
            loc = error["loc"]
            missing_arguments = self.children_recursive.filter_by(keys_prefix=self.keys + loc)

            # For discriminated/tagged unions, Pydantic includes the discriminator value
            # in the error location. e.g., for a Cat|Dog union discriminated by "type",
            # a missing "rainbow" field on Cat will have loc=('cat', 'rainbow') instead
            # of just ('rainbow'). Strip discriminator values to find the actual child.
            while not missing_arguments and len(loc) > 1:
                loc = loc[1:]
                missing_arguments = self.children_recursive.filter_by(keys_prefix=self.keys + loc)

            if missing_arguments:
                raise MissingArgumentError(argument=missing_arguments[0]) from exc
            # Fall through to ValidationError if we can't find the missing argument

        if isinstance(exc, pydantic.ValidationError):
            raise ValidationError(exception_message=str(exc), argument=self) from exc
        else:
            raise exc
