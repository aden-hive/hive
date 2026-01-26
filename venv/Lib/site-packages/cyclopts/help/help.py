import inspect
import sys
from collections.abc import Iterable, Sequence
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
)

from attrs import converters, define, evolve, field

from cyclopts.annotations import resolve_annotated
from cyclopts.core import _get_root_module_name
from cyclopts.group import Group
from cyclopts.help.inline_text import InlineText
from cyclopts.help.silent import SILENT, SilentRich
from cyclopts.utils import SortHelper, frozen, is_class_and_subclass, resolve_callables

if TYPE_CHECKING:
    from rich.console import RenderableType

    from cyclopts.argument import ArgumentCollection
    from cyclopts.core import App


@lru_cache(maxsize=16)
def docstring_parse(doc: str, format: str):
    """Addon to :func:`docstring_parser.parse` that supports multi-line `short_description`."""
    import docstring_parser

    cleaned_doc = inspect.cleandoc(doc)
    short_description_and_maybe_remainder = cleaned_doc.split("\n\n", 1)

    # Place multi-line summary into a single line.
    # This kind of goes against PEP-0257, but any reasonable CLI command will
    # have either no description, or it will have both a short and long description.
    short = short_description_and_maybe_remainder[0].replace("\n", " ")
    if len(short_description_and_maybe_remainder) == 1:
        cleaned_doc = short
    else:
        cleaned_doc = short + "\n\n" + short_description_and_maybe_remainder[1]

    res = docstring_parser.parse(cleaned_doc)

    # Ensure a short description exists if there's a long description
    assert not res.long_description or res.short_description

    return res


def _text_factory():
    from rich.text import Text

    return Text()


@frozen(kw_only=True)
class HelpEntry:
    """Container for help table entry data."""

    positive_names: tuple[str, ...] = ()
    """Positive long option names (e.g., "--verbose", "--dry-run")."""

    positive_shorts: tuple[str, ...] = ()
    """Positive short option names (e.g., "-v", "-n")."""

    negative_names: tuple[str, ...] = ()
    """Negative long option names (e.g., "--no-verbose", "--no-dry-run")."""

    negative_shorts: tuple[str, ...] = ()
    """Negative short option names (e.g., "-N"). Rarely used."""

    @property
    def names(self) -> tuple[str, ...]:
        """All long option names (positive + negative). For backward compatibility."""
        return self.positive_names + self.negative_names

    @property
    def shorts(self) -> tuple[str, ...]:
        """All short option names (positive + negative). For backward compatibility."""
        return self.positive_shorts + self.negative_shorts

    @property
    def all_options(self) -> tuple[str, ...]:
        """All options in display order: positive longs, positive shorts, negative longs, negative shorts."""
        return self.positive_names + self.positive_shorts + self.negative_names + self.negative_shorts

    description: Any = None
    """Help text description for this entry.

    Typically a :class:`str` or a :obj:`~rich.console.RenderableType`
    """

    required: bool = False
    """Whether this parameter/command is required."""

    sort_key: Any = None
    """Custom sorting key for ordering entries."""

    type: Any | None = None
    """Type annotation of the parameter."""

    choices: tuple[str, ...] | None = None
    """Available choices for this parameter."""

    env_var: tuple[str, ...] | None = None
    """Environment variable names that can set this parameter."""

    default: str | None = None
    """Default value for this parameter to display. None means no default to show."""

    def copy(self, **kwargs):
        return evolve(self, **kwargs)


@define
class HelpPanel:
    """Data container for help panel information."""

    format: Literal["command", "parameter"]
    """Panel format type."""

    title: "RenderableType"
    """The title text displayed at the top of the help panel."""

    description: Any = field(
        default=None,
        converter=converters.default_if_none(factory=_text_factory),
    )
    """Optional description text displayed below the title.

    Typically a :class:`str` or a :obj:`~rich.console.RenderableType`
    """

    entries: list[HelpEntry] = field(factory=list)
    """List of help entries to display (in order) in the panel."""

    def copy(self, **kwargs):
        return evolve(self, **kwargs)

    def _remove_duplicates(self):
        seen, out = set(), []
        for item in self.entries:
            hashable = (item.names, item.shorts)
            if hashable not in seen:
                seen.add(hashable)
                out.append(item)
        self.entries = out

    def _sort(self):
        """Sort entries in-place."""
        if not self.entries:
            return

        if self.format == "command":
            sorted_sort_helper = SortHelper.sort(
                [
                    SortHelper(
                        entry.sort_key,
                        (
                            entry.names[0].startswith("-") if entry.names else False,
                            entry.names[0] if entry.names else "",
                        ),
                        entry,
                    )
                    for entry in self.entries
                ]
            )
            self.entries = [x.value for x in sorted_sort_helper]
        else:
            raise NotImplementedError


def _is_short(s):
    return not s.startswith("--") and s.startswith("-")


def _categorize_keyword_arguments(argument_collection: "ArgumentCollection") -> tuple[list, list]:
    """Categorize keyword arguments by requirement status for usage string formatting.

    Parameters
    ----------
    argument_collection : ArgumentCollection
        Collection of arguments to categorize.

    Returns
    -------
    tuple[list, list]
        (required_keyword, optional_keyword) where:
        - required_keyword: Required keyword-only parameters
        - optional_keyword: Optional keyword-only parameters and VAR_KEYWORD
    """
    required, optional = [], []

    for argument in argument_collection:
        if not argument.show:
            continue

        if argument.field_info.kind in (argument.field_info.VAR_KEYWORD,):
            optional.append(argument)
        elif argument.field_info.is_keyword_only:
            if argument.required:
                required.append(argument)
            else:
                optional.append(argument)

    return required, optional


def _categorize_positional_arguments(argument_collection: "ArgumentCollection") -> tuple[list, list]:
    """Categorize positional arguments by requirement status for usage string formatting.

    Parameters
    ----------
    argument_collection : ArgumentCollection
        Collection of arguments to categorize.

    Returns
    -------
    tuple[list, list]
        (required_positional, optional_positional) where:
        - required_positional: Required positional and VAR_POSITIONAL parameters
        - optional_positional: Optional positional and VAR_POSITIONAL parameters
    """
    required, optional = [], []

    for argument in argument_collection:
        if not argument.show:
            continue

        if argument.field_info.kind == argument.field_info.VAR_POSITIONAL:
            if argument.required:
                required.append(argument)
            else:
                optional.append(argument)
        elif argument.field_info.is_positional:
            if argument.required:
                required.append(argument)
            else:
                optional.append(argument)

    return required, optional


def format_usage(
    app: "App",
    command_chain: Iterable[str],
):
    from rich.text import Text

    from cyclopts.annotations import get_hint_name

    usage = []

    # If we're at the root level (no command chain), the app has a default_command,
    # and no explicit name was set, derive a better name from sys.argv[0]
    if not command_chain and app.default_command and not app._name:
        # Use the same logic as in App.name property for apps without default_command
        name = Path(sys.argv[0]).name
        if name == "__main__.py":
            name = _get_root_module_name()
        app_name = name
    else:
        app_name = app.name[0]

    usage.append(app_name)
    usage.extend(command_chain)

    for command in command_chain:
        app = app[command]

    if any(app[x].show for x in app._registered_commands):
        usage.append("COMMAND")

    if app.default_command:
        argument_collection = app.assemble_argument_collection(parse_docstring=False)

        required_keyword_params, optional_keyword_params = _categorize_keyword_arguments(argument_collection)
        required_positional_args, optional_positional_args = _categorize_positional_arguments(argument_collection)

        for argument in required_keyword_params:
            param_name = argument.name
            type_name = get_hint_name(argument.hint).upper()
            usage.append(f"{param_name} {type_name}")

        if optional_keyword_params:
            usage.append("[OPTIONS]")

        for argument in required_positional_args:
            if argument.field_info.kind == argument.field_info.VAR_POSITIONAL:
                arg_name = argument.name.lstrip("-").upper()
                usage.append(f"{arg_name}...")
            else:
                arg_name = argument.name.lstrip("-").upper()
                usage.append(arg_name)

        if optional_positional_args:
            has_var_positional = any(
                arg.field_info.kind == arg.field_info.VAR_POSITIONAL for arg in optional_positional_args
            )
            if has_var_positional:
                usage.append("[ARGS...]")
            else:
                usage.append("[ARGS]")

    return Text(" ".join(usage) + "\n", style="bold")


def _smart_join(strings: Sequence[str]) -> str:
    """Joins strings with a space, unless the previous string ended in a newline."""
    if not strings:
        return ""

    result = [strings[0]]
    for s in strings[1:]:
        if result[-1].endswith("\n"):
            result.append(s)
        else:
            result.append(" " + s)

    return "".join(result)


def format_doc(app: "App", format: str) -> InlineText | SilentRich:
    raw_doc_string = app.help

    if not raw_doc_string:
        return SILENT

    parsed = docstring_parse(raw_doc_string, format)

    components: list[str] = []
    if parsed.short_description:
        components.append(parsed.short_description + "\n")

    if parsed.long_description:
        if parsed.short_description:
            components.append("\n")
        components.append(parsed.long_description + "\n")
    return InlineText.from_format(_smart_join(components), format=format, force_empty_end=True)


def create_parameter_help_panel(
    group: "Group",
    argument_collection: "ArgumentCollection",
    format: str,
) -> HelpPanel:
    from rich.text import Text

    kwargs = {
        "format": "parameter",
        "title": group.name,
        "description": InlineText.from_format(group.help, format=format, force_empty_end=True)
        if group.help
        else Text(),
    }

    help_panel = HelpPanel(**kwargs)

    def help_append(text, style):
        if help_components:
            text = " " + text
        if style:
            help_components.append((text, style))
        else:
            help_components.append(text)

    entries_positional, entries_kw = [], []
    for argument in argument_collection.filter_by(show=True):
        assert argument.parameter.name_transform

        help_components = []
        options = list(argument.names)

        # Deduplicate options based on their transformed names for display.
        # E.g., both "userName" and "user_name" transform to "user-name"
        # This prevents duplicate help entries while keeping all name variants
        # in field_info.names for CLI/JSON/env var matching.
        seen_transformed = set()
        unique_options = []
        for option in options:
            transformed = argument.parameter.name_transform(option)
            if transformed not in seen_transformed:
                seen_transformed.add(transformed)
                unique_options.append(option)
        options = unique_options

        # Add an all-uppercase name if it's an argument
        if argument.index is not None:
            arg_name = options[0].lstrip("-").upper()
            if arg_name != options[0]:
                options = [arg_name, *options]

        # Split options into positive/negative and long/short categories.
        negatives = set(argument.negatives)
        positive_names = [o for o in options if o not in negatives and not _is_short(o)]
        positive_shorts = [o for o in options if o not in negatives and _is_short(o)]
        negative_names = [o for o in options if o in negatives and not _is_short(o)]
        negative_shorts = [o for o in options if o in negatives and _is_short(o)]

        help_description = InlineText.from_format(argument.parameter.help, format=format)

        # Prepare choices if needed
        choices = argument.get_choices()

        # Prepare env_var if needed
        env_var = None
        if argument.parameter.show_env_var and argument.parameter.env_var:
            env_var = tuple(argument.parameter.env_var)

        # Prepare default if needed
        default = None
        if argument.show_default:
            default_val = argument.field_info.default
            if is_class_and_subclass(argument.hint, Enum):
                default = argument.parameter.name_transform(default_val.name)
            elif isinstance(default_val, (list, tuple, set, frozenset)):
                # Handle collections - format each element, especially enums
                formatted_items = []
                for item in default_val:
                    if isinstance(item, Enum):
                        # For enums, use the transformed name without quotes
                        formatted_items.append(argument.parameter.name_transform(item.name))
                    elif isinstance(item, str):
                        # Keep strings quoted
                        formatted_items.append(f"'{item}'")
                    else:
                        formatted_items.append(str(item))
                # Use appropriate collection notation
                if isinstance(default_val, tuple):
                    if len(formatted_items) == 1:
                        default = "(" + formatted_items[0] + ",)"
                    else:
                        default = "(" + ", ".join(formatted_items) + ")"
                elif isinstance(default_val, list):
                    default = "[" + ", ".join(formatted_items) + "]"
                else:  # set or frozenset
                    default = "{" + ", ".join(formatted_items) + "}"
            elif default_val == "":
                # Empty string - show explicitly as empty
                default = '""'
            else:
                default = str(default_val)
            if callable(argument.show_default):
                default = argument.show_default(default_val)

        # populate row
        entry = HelpEntry(
            positive_names=tuple(positive_names),
            positive_shorts=tuple(positive_shorts),
            negative_names=tuple(negative_names),
            negative_shorts=tuple(negative_shorts),
            description=help_description,
            required=argument.required,
            type=resolve_annotated(argument.field_info.annotation),
            choices=choices,
            env_var=env_var,
            default=default,
        )

        if argument.field_info.is_positional:
            entries_positional.append(entry)
        else:
            entries_kw.append(entry)

    help_panel.entries.extend(entries_positional)
    help_panel.entries.extend(entries_kw)

    return help_panel


def format_command_entries(apps_with_names: Iterable, format: str) -> list[HelpEntry]:
    """Format command entries for help display.

    Parameters
    ----------
    apps_with_names : Iterable[RegisteredCommand]
        Iterable of RegisteredCommand tuples.
    format : str
        Help text format.

    Returns
    -------
    list[HelpEntry]
        List of formatted help entries.
    """
    entries = []
    for registered_command in apps_with_names:
        names = registered_command.names
        app = registered_command.app
        if not app.show:
            continue
        # Commands don't have negative variants, so all names are "positive"
        short_names, long_names = [], []
        for name in names:
            short_names.append(name) if _is_short(name) else long_names.append(name)

        entry = HelpEntry(
            positive_names=tuple(long_names),
            positive_shorts=tuple(short_names),
            description=InlineText.from_format(docstring_parse(app.help, format).short_description, format=format),
            sort_key=resolve_callables(app.sort_key, app),
        )
        if entry not in entries:
            entries.append(entry)
    return entries
