"""ArgumentCollection class and related functionality."""

import inspect
import itertools
import json
from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING, Any, SupportsIndex, TypeVar, overload

if TYPE_CHECKING:
    from cyclopts.core import App

from cyclopts.exceptions import (
    UnknownOptionError,
)
from cyclopts.field_info import (
    signature_parameters,
)
from cyclopts.group import Group
from cyclopts.parameter import Parameter
from cyclopts.token import Token
from cyclopts.utils import UNSET, is_iterable

from ._argument import Argument
from .utils import (
    KIND_PARENT_CHILD_REASSIGNMENT,
    PARAMETER_SUBKEY_BLOCKER,
    extract_docstring_help,
    resolve_parameter_name,
    to_cli_option_name,
    walk_leaves,
)

T = TypeVar("T")


class ArgumentCollection(list[Argument]):
    """A list-like container for :class:`Argument`."""

    def __init__(self, *args):
        super().__init__(*args)

    def copy(self) -> "ArgumentCollection":
        """Returns a shallow copy of the :class:`ArgumentCollection`."""
        return type(self)(self)

    @overload
    def __getitem__(self, term: SupportsIndex, /) -> Argument: ...
    @overload
    def __getitem__(self, term: slice, /) -> list[Argument]: ...
    @overload
    def __getitem__(self, term: str, /) -> Argument: ...
    def __getitem__(
        self,
        term: str | SupportsIndex | slice,
    ) -> Argument | list[Argument]:
        if isinstance(term, (SupportsIndex, slice)):
            return super().__getitem__(term)

        return self.get(term)

    def __contains__(self, item: object, /) -> bool:
        """Check if an argument or argument name exists in the collection.

        Parameters
        ----------
        item : Argument | str
            Either an Argument object or a string name/alias to search for.

        Returns
        -------
        bool
            True if the item is in the collection.

        Examples
        --------
        >>> argument_collection = ArgumentCollection(
        ...     [
        ...         Argument(parameter=Parameter(name="--foo")),
        ...         Argument(parameter=Parameter(name=("--bar", "-b"))),
        ...     ]
        ... )
        >>> "--foo" in argument_collection
        True
        >>> "-b" in argument_collection  # Alias matching
        True
        >>> "--baz" in argument_collection
        False
        """
        if isinstance(item, str):
            try:
                self[item]
                return True
            except KeyError:
                return False
        else:
            return super().__contains__(item)

    @overload
    def get(
        self,
        term: str | int,
        default: type[UNSET] = ...,
        *,
        transform: Callable[[str], str] | None = None,
        delimiter: str = ".",
    ) -> Argument: ...
    @overload
    def get(
        self,
        term: str | int,
        default: T,
        *,
        transform: Callable[[str], str] | None = None,
        delimiter: str = ".",
    ) -> Argument | T: ...
    def get(
        self,
        term: str | int,
        default: Any = UNSET,
        *,
        transform: Callable[[str], str] | None = None,
        delimiter: str = ".",
    ) -> Argument | Any:
        """Get an :class:`Argument` by name or index.

        This is a convenience wrapper around :meth:`match` that returns just
        the :class:`Argument` object instead of a tuple.

        Parameters
        ----------
        term : str | int
            Either a string keyword or an integer positional index.
        default : Any
            Default value to return if term not found. If :data:`~cyclopts.utils.UNSET` (default),
            will raise :exc:`KeyError`/:exc:`IndexError`.
        transform : Callable[[str], str] | None
            Optional function to transform string terms before matching.
        delimiter : str
            Delimiter for nested field access.

        Returns
        -------
        Argument | None
            The matched :class:`Argument`, or ``default`` if provided and not found.

        Raises
        ------
        :exc:`KeyError`
            If ``term`` is a string and not found (when ``default`` is :data:`~cyclopts.utils.UNSET`).
        :exc:`IndexError`
            If ``term`` is an int and is out-of-range (when ``default`` is :data:`~cyclopts.utils.UNSET`).

        See Also
        --------
        :meth:`match` : Returns a tuple of (:class:`Argument`, keys, value) with more detailed information.
        """
        try:
            argument, _, _ = self.match(term, transform=transform, delimiter=delimiter)
            return argument
        except ValueError:
            if default is UNSET:
                if isinstance(term, str):
                    raise KeyError(f"No such Argument: {term}") from None
                else:
                    raise IndexError(f"Argument index {term} out of range") from None
            return default

    def match(
        self,
        term: str | int,
        *,
        transform: Callable[[str], str] | None = None,
        delimiter: str = ".",
    ) -> tuple[Argument, tuple[str, ...], Any]:
        """Matches CLI keyword or index to their :class:`Argument`.

        Parameters
        ----------
        term: str | int
            One of:

            * :obj:`str` keyword like ``"--foo"`` or ``"-f"`` or ``"--foo.bar.baz"``.

            * :obj:`int` global positional index.

        Raises
        ------
        ValueError
            If the provided ``term`` doesn't match.

        Returns
        -------
        Argument
            Matched :class:`Argument`.
        tuple[str, ...]
            Python keys into :class:`Argument`. Non-empty iff :class:`Argument` accepts keys.
        Any
            Implicit value (if a flag). :obj:`~.UNSET` otherwise.
        """
        best_match_argument, best_match_keys, best_implicit_value = None, None, UNSET
        for argument in self:
            try:
                match_keys, implicit_value = argument.match(term, transform=transform, delimiter=delimiter)
            except ValueError:
                continue
            if best_match_keys is None or len(match_keys) < len(best_match_keys):
                best_match_keys = match_keys
                best_match_argument = argument
                best_implicit_value = implicit_value
            if not match_keys:
                break

        if best_match_argument is None or best_match_keys is None:
            raise ValueError(f"No Argument matches {term!r}")

        return best_match_argument, best_match_keys, best_implicit_value

    def _set_marks(self, val: bool):
        for argument in self:
            argument._marked = val

    def _convert(self):
        """Convert and validate all elements."""
        self._set_marks(False)
        for argument in sorted(self, key=lambda x: x.keys):
            if argument._marked:
                continue
            argument.convert_and_validate()

    @classmethod
    def _from_type(
        cls,
        field_info,
        keys: tuple[str, ...],
        *default_parameters: Parameter | None,
        group_lookup: dict[str, Group],
        group_arguments: Group,
        group_parameters: Group,
        parse_docstring: bool = True,
        docstring_lookup: dict[tuple[str, ...], Parameter] | None = None,
        positional_index: int | None = None,
        _resolve_groups: bool = True,
    ):
        from cyclopts.parameter import get_parameters

        out = cls()

        if docstring_lookup is None:
            docstring_lookup = {}

        cyclopts_parameters_no_group = []

        hint = field_info.hint
        hint, hint_parameters = get_parameters(hint)
        cyclopts_parameters_no_group.extend(hint_parameters)

        if not keys:
            if field_info.kind is field_info.VAR_KEYWORD:
                hint = dict[str, hint]
            elif field_info.kind is field_info.VAR_POSITIONAL:
                hint = tuple[hint, ...]

        if _resolve_groups:
            cyclopts_parameters = []
            for cparam in cyclopts_parameters_no_group:
                resolved_groups = []
                for group in cparam.group:  # pyright:ignore
                    if isinstance(group, str):
                        group = group_lookup[group]
                    resolved_groups.append(group)
                    cyclopts_parameters.append(group.default_parameter)
                cyclopts_parameters.append(cparam)

                if resolved_groups:
                    has_visible_group = any(g.show for g in resolved_groups)
                    all_nameless = all(not g.name for g in resolved_groups)

                    if has_visible_group:
                        cyclopts_parameters.append(Parameter(group=resolved_groups))
                    elif all_nameless:
                        default_group = (
                            group_arguments
                            if field_info.kind in (field_info.POSITIONAL_ONLY, field_info.VAR_POSITIONAL)
                            else group_parameters
                        )
                        all_groups = (default_group,) + tuple(resolved_groups)
                        cyclopts_parameters.append(Parameter(group=all_groups))
                    else:
                        cyclopts_parameters.append(Parameter(group=resolved_groups))
        else:
            cyclopts_parameters = cyclopts_parameters_no_group

        upstream_parameter = Parameter.combine(
            (
                Parameter(group=group_arguments)
                if field_info.kind in (field_info.POSITIONAL_ONLY, field_info.VAR_POSITIONAL)
                else Parameter(group=group_parameters)
            ),
            *default_parameters,
        )
        immediate_parameter = Parameter.combine(*cyclopts_parameters)

        if keys:
            cparam = Parameter.combine(
                upstream_parameter,
                PARAMETER_SUBKEY_BLOCKER,
                immediate_parameter,
            )
            cparam = Parameter.combine(
                cparam,
                Parameter(
                    name=resolve_parameter_name(
                        upstream_parameter.name,  # pyright: ignore
                        (immediate_parameter.name or tuple(cparam.name_transform(x) for x in field_info.names))
                        + cparam.alias,  # pyright: ignore
                    )
                ),
            )
        else:
            cparam = Parameter.combine(
                upstream_parameter,
                immediate_parameter,
            )
            assert isinstance(cparam.alias, tuple)
            if cparam.name:
                if field_info.is_keyword:
                    assert isinstance(cparam.name, tuple)
                    cparam = Parameter.combine(
                        cparam, Parameter(name=resolve_parameter_name(cparam.name + cparam.alias))
                    )
            else:
                if field_info.kind in (field_info.POSITIONAL_ONLY, field_info.VAR_POSITIONAL):
                    cparam = Parameter.combine(cparam, Parameter(name=(name.upper() for name in field_info.names)))
                elif field_info.kind is field_info.VAR_KEYWORD:
                    cparam = Parameter.combine(cparam, Parameter(name=("--[KEYWORD]",)))
                else:
                    assert cparam.name_transform is not None
                    cparam = Parameter.combine(
                        cparam,
                        Parameter(
                            name=tuple("--" + cparam.name_transform(name) for name in field_info.names)
                            + resolve_parameter_name(cparam.alias)
                        ),
                    )

        if field_info.is_keyword_only:
            positional_index = None

        argument = Argument(field_info=field_info, parameter=cparam, keys=keys, hint=hint)

        if positional_index is not None:
            if not argument._accepts_keywords or argument._enum_flag_type:
                argument.index = positional_index
                positional_index += 1

        out.append(argument)
        if argument._accepts_keywords:
            hint_docstring_lookup = extract_docstring_help(argument.hint) if parse_docstring else {}
            hint_docstring_lookup.update(docstring_lookup)

            for sub_field_name, sub_field_info in argument._lookup.items():
                updated_kind = KIND_PARENT_CHILD_REASSIGNMENT[(argument.field_info.kind, sub_field_info.kind)]
                if updated_kind is None:
                    continue

                sub_field_info.kind = updated_kind

                if sub_field_info.is_keyword_only:
                    positional_index = None

                subkey_docstring_lookup = {
                    k[1:]: v for k, v in hint_docstring_lookup.items() if k[0] == sub_field_name and len(k) > 1
                }

                subkey_argument_collection = cls._from_type(
                    sub_field_info,
                    keys + (sub_field_name,),
                    cparam,
                    (
                        Parameter(help=sub_field_info.help)
                        if sub_field_info.help
                        else hint_docstring_lookup.get((sub_field_name,))
                    ),
                    Parameter(required=argument.required & sub_field_info.required),
                    group_lookup=group_lookup,
                    group_arguments=group_arguments,
                    group_parameters=group_parameters,
                    parse_docstring=parse_docstring,
                    docstring_lookup=subkey_docstring_lookup,
                    positional_index=positional_index,
                    _resolve_groups=_resolve_groups,
                )
                if subkey_argument_collection:
                    argument.children.append(subkey_argument_collection[0])
                    out.extend(subkey_argument_collection)

                    if positional_index is not None:
                        positional_index = subkey_argument_collection._max_index
                        if positional_index is not None:
                            positional_index += 1

        return out

    @classmethod
    def _from_callable(
        cls,
        func: Callable,
        *default_parameters: Parameter | None,
        group_lookup: dict[str, Group] | None = None,
        group_arguments: Group | None = None,
        group_parameters: Group | None = None,
        parse_docstring: bool = True,
        _resolve_groups: bool = True,
    ):
        out = cls()

        if group_arguments is None:
            group_arguments = Group.create_default_arguments()
        if group_parameters is None:
            group_parameters = Group.create_default_parameters()

        if _resolve_groups:
            group_lookup = {
                group.name: group
                for group in _resolve_groups_from_callable(
                    func,
                    *default_parameters,
                    group_arguments=group_arguments,
                    group_parameters=group_parameters,
                )
            }
        else:
            group_lookup = {}

        docstring_lookup = extract_docstring_help(func) if parse_docstring else {}
        positional_index = 0
        for field_info in signature_parameters(func).values():
            if parse_docstring:
                subkey_docstring_lookup = {
                    k[1:]: v for k, v in docstring_lookup.items() if k[0] == field_info.name and len(k) > 1
                }
            else:
                subkey_docstring_lookup = None
            iparam_argument_collection = cls._from_type(
                field_info,
                (),
                *default_parameters,
                Parameter(help=field_info.help) if field_info.help else docstring_lookup.get((field_info.name,)),
                group_lookup=group_lookup,
                group_arguments=group_arguments,
                group_parameters=group_parameters,
                positional_index=positional_index,
                parse_docstring=parse_docstring,
                docstring_lookup=subkey_docstring_lookup,
                _resolve_groups=_resolve_groups,
            )
            if positional_index is not None:
                positional_index = iparam_argument_collection._max_index
                if positional_index is not None:
                    positional_index += 1
            out.extend(iparam_argument_collection)

        return out

    @property
    def groups(self):
        groups = []
        for argument in self:
            assert isinstance(argument.parameter.group, tuple)
            for group in argument.parameter.group:
                if group not in groups:
                    groups.append(group)
        return groups

    @property
    def _root_arguments(self):
        for argument in self:
            if not argument.keys:
                yield argument

    @property
    def _max_index(self) -> int | None:
        return max((x.index for x in self if x.index is not None), default=None)

    def filter_by(
        self,
        *,
        group: Group | None = None,
        has_tokens: bool | None = None,
        has_tree_tokens: bool | None = None,
        keys_prefix: tuple[str, ...] | None = None,
        kind: inspect._ParameterKind | None = None,
        parse: bool | None = None,
        show: bool | None = None,
        value_set: bool | None = None,
    ) -> "ArgumentCollection":
        """Filter the :class:`ArgumentCollection`.

        All non-None filters will be applied.

        Parameters
        ----------
        group: Group | None
            The :class:`.Group` the arguments should be in.
        has_tokens: bool | None
            Immediately has tokens (not including children).
        has_tree_tokens: bool | None
            :class:`Argument` and/or it's children have parsed tokens.
        kind: inspect._ParameterKind | None
            The :attr:`~inspect.Parameter.kind` of the argument.
        parse: bool | None
            If the argument is intended to be parsed or not.
        show: bool | None
            The :class:`Argument` is intended to be show on the help page.
        value_set: bool | None
            The converted value is set.
        """
        ac = self.copy()
        cls = type(self)

        if group is not None:
            ac = cls(x for x in ac if group in x.parameter.group)  # pyright: ignore
        if kind is not None:
            ac = cls(x for x in ac if x.field_info.kind == kind)
        if has_tokens is not None:
            ac = cls(x for x in ac if not (bool(x.tokens) ^ bool(has_tokens)))
        if has_tree_tokens is not None:
            ac = cls(x for x in ac if not (bool(x.tokens) ^ bool(has_tree_tokens)))
        if keys_prefix is not None:
            ac = cls(x for x in ac if x.keys[: len(keys_prefix)] == keys_prefix)
        if show is not None:
            ac = cls(x for x in ac if not (x.show ^ bool(show)))
        if value_set is not None:
            ac = cls(x for x in ac if ((x.value is UNSET) ^ bool(value_set)))
        if parse is not None:
            ac = cls(x for x in ac if not (x.parse ^ parse))

        return ac


def _resolve_groups_from_callable(
    func: Callable[..., Any],
    *default_parameters: Parameter | None,
    group_arguments: Group | None = None,
    group_parameters: Group | None = None,
) -> list[Group]:
    argument_collection = ArgumentCollection._from_callable(
        func,
        *default_parameters,
        group_arguments=group_arguments,
        group_parameters=group_parameters,
        parse_docstring=False,
        _resolve_groups=False,
    )

    resolved_groups = []
    if group_arguments is not None:
        resolved_groups.append(group_arguments)
    if group_parameters is not None:
        resolved_groups.append(group_parameters)

    for argument in argument_collection:
        for group in argument.parameter.group:  # pyright: ignore
            if not isinstance(group, Group):
                continue

            if any(group != x and x._name == group._name for x in resolved_groups):
                raise ValueError("Cannot register 2 distinct Group objects with same name.")

            if group.default_parameter is not None and group.default_parameter.group:
                raise ValueError("Group.default_parameter cannot have a specified group.")  # pragma: no cover

            try:
                next(x for x in resolved_groups if x._name == group._name)
            except StopIteration:
                resolved_groups.append(group)

    for argument in argument_collection:
        for group in argument.parameter.group:  # pyright: ignore
            if not isinstance(group, str):
                continue
            try:
                next(x for x in resolved_groups if x.name == group)
            except StopIteration:
                resolved_groups.append(Group(group))

    return resolved_groups


def _meta_arguments(apps: Sequence["App"]) -> ArgumentCollection:
    argument_collection = ArgumentCollection()
    for app in apps:
        if app._meta is None:
            continue
        argument_collection.extend(app._meta.assemble_argument_collection())
    return argument_collection


def _is_valid_option_key(option_key: str, arguments: "ArgumentCollection") -> bool:
    """Check if option_key corresponds to a valid root argument.

    When processing nested config keys like {"p": {"timeout": 3}}, the fallback
    alias matching needs to verify that "p" is actually a valid parameter before
    matching nested fields. This prevents unknown keys like "np" from incorrectly
    matching against valid nested arguments.

    If no root argument exists (children-only collection, e.g., from JSON env var
    processing), returns True since the option_key is implicitly valid.

    Parameters
    ----------
    option_key : str
        The top-level config key to validate (e.g., "p" from {"p": {"timeout": 3}}).
    arguments : ArgumentCollection
        The argument collection to validate against.

    Returns
    -------
    bool
        True if option_key is valid, False otherwise.
    """
    root_arg = next((arg for arg in arguments if arg.keys == ()), None)
    if not root_arg:
        return True  # Children-only collection, implicitly valid
    cli_parent = to_cli_option_name(option_key)
    return bool(
        (root_arg.parameter.name and cli_parent in root_arg.parameter.name) or option_key in root_arg.field_info.names
    )


def update_argument_collection(
    config: dict,
    source: str,
    arguments: ArgumentCollection,
    apps: Sequence["App"] | None = None,
    *,
    root_keys: Iterable[str],
    allow_unknown: bool,
):
    """Updates an argument collection with values from a configuration dictionary.

    This function takes configuration data (typically from JSON, TOML, YAML files
    or environment variables) and populates the corresponding arguments in the
    ArgumentCollection with tokens representing those values.

    The function handles various naming conventions, including:
    - Exact matches (e.g., "storage_class" matches "storage_class")
    - Transformed matches (e.g., "storage-class" matches "storage_class")
    - Pydantic aliases (e.g., "storageClass" matches field with alias "storageClass")

    Parameters
    ----------
    config : dict
        Configuration dictionary with nested structure mapping to CLI arguments.
    source : str
        Source identifier (e.g., file path or "env") for error messages and tracking.
    arguments : ArgumentCollection
        Collection of arguments to populate with configuration values.
    apps : Optional[Sequence[App]]
        Stack of App instances for meta-argument handling.
        We need to know all the meta-apps leading up to the current application so that we can
        properly detect unknown keys.
    root_keys : Iterable[str]
        Base path keys to prepend to all configuration keys.
    allow_unknown : bool
        If True, ignore unrecognized configuration keys instead of raising errors.

    Raises
    ------
    UnknownOptionError
        If a configuration key doesn't match any argument and allow_unknown is False.

    Notes
    -----
    Arguments that already have tokens are skipped to preserve command-line
    precedence over configuration files.
    """
    meta_arguments = _meta_arguments(apps or ())

    do_not_update = {}

    for option_key, option_value in config.items():
        for subkeys, value in walk_leaves(option_value):
            cli_option_name = to_cli_option_name(option_key, *subkeys)
            complete_keyword = "".join(f"[{k}]" for k in itertools.chain(root_keys, (option_key,), subkeys))

            try:
                meta_arguments.match(cli_option_name)
                continue
            except ValueError:
                pass

            argument = None
            remaining_keys = ()
            try:
                argument, remaining_keys, _ = arguments.match(cli_option_name)
            except ValueError:
                if subkeys and _is_valid_option_key(option_key, arguments):
                    for arg in arguments:
                        if len(subkeys) != len(arg.keys):
                            continue

                        all_match = True
                        for i, (subkey, arg_key) in enumerate(zip(subkeys, arg.keys, strict=False)):
                            if subkey == arg_key:
                                continue

                            if i == len(arg.keys) - 1:
                                if subkey not in arg.field_info.names:
                                    all_match = False
                                    break
                            else:
                                parent_keys = arg.keys[: i + 1]
                                alias_found = False
                                for parent_arg in arguments:
                                    if parent_arg.keys == parent_keys and subkey in parent_arg.field_info.names:
                                        alias_found = True
                                        break
                                if not alias_found:
                                    all_match = False
                                    break

                        if all_match:
                            argument = arg
                            remaining_keys = ()
                            break

            if not argument:
                if allow_unknown:
                    continue
                if apps and apps[-1]._meta_parent:
                    continue
                raise UnknownOptionError(
                    token=Token(keyword=complete_keyword, source=source), argument_collection=arguments
                ) from None

            if do_not_update.setdefault(id(argument), bool(argument.tokens)):
                continue

            if not is_iterable(value):
                value = (value,)

            if value:
                for i, v in enumerate(value):
                    if v is None:
                        token = Token(
                            keyword=complete_keyword,
                            implicit_value=None,
                            source=source,
                            index=i,
                            keys=remaining_keys,
                        )
                    else:
                        if isinstance(v, dict | list):
                            # Serialize to JSON string; will be deserialized in Argument._json()
                            value_str = json.dumps(v)
                        else:
                            value_str = str(v)
                        token = Token(
                            keyword=complete_keyword, value=value_str, source=source, index=i, keys=remaining_keys
                        )
                    argument.append(token)
            else:
                token = Token(
                    keyword=complete_keyword, implicit_value=value, source=source, index=0, keys=remaining_keys
                )
                argument.append(token)
