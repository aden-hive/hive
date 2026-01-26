"""Shared shell completion infrastructure.

Provides data extraction, type analysis, and text processing utilities.
"""

import os
import re
import warnings
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, get_args, get_origin

from cyclopts._convert import ITERABLE_TYPES
from cyclopts.annotations import is_union
from cyclopts.argument import ArgumentCollection
from cyclopts.exceptions import CycloptsError
from cyclopts.group_extractors import RegisteredCommand, groups_from_app
from cyclopts.utils import frozen, is_class_and_subclass

if TYPE_CHECKING:
    from cyclopts import App


class CompletionAction(Enum):
    """Shell-agnostic completion action types."""

    NONE = "none"
    FILES = "files"
    DIRECTORIES = "directories"


@frozen
class CompletionData:
    """Completion data for a command path."""

    arguments: "ArgumentCollection"
    commands: list[RegisteredCommand]
    help_format: str


def extract_completion_data(app: "App") -> dict[tuple[str, ...], CompletionData]:
    """Recursively extract completion data for app and all subcommands.

    Parameters
    ----------
    app : App
        The Cyclopts application to extract completion data from.

    Returns
    -------
    dict[tuple[str, ...], CompletionData]
        Mapping from command path tuples to their completion data.
    """
    completion_data: dict[tuple[str, ...], CompletionData] = {}

    def _extract(command_path: tuple[str, ...] = ()):
        """Recursively extract completion data for command and subcommands."""
        try:
            _, execution_path, _ = app.parse_commands(list(command_path))
            command_app = execution_path[-1]
        except (CycloptsError, ValueError, TypeError) as e:
            if os.environ.get("CYCLOPTS_COMPLETION_DEBUG"):
                raise
            warnings.warn(f"Failed to extract completion data for command path {command_path!r}: {e}", stacklevel=2)
            help_format = app.app_stack.resolve("help_format", fallback="markdown")
            completion_data[command_path] = CompletionData(
                arguments=ArgumentCollection(), commands=[], help_format=help_format
            )
            return

        arguments = ArgumentCollection()
        apps_for_params = app._get_resolution_context(execution_path)
        with app.app_stack(execution_path):
            for subapp in apps_for_params:
                if subapp.default_command:
                    app_arguments = subapp.assemble_argument_collection(parse_docstring=True)
                    arguments.extend(app_arguments)

        commands = []
        for group, registered_commands in groups_from_app(command_app):
            if group.show:
                for registered_command in registered_commands:
                    if registered_command.app.show and registered_command not in commands:
                        commands.append(registered_command)

        help_format = command_app.app_stack.resolve("help_format", fallback="markdown")

        completion_data[command_path] = CompletionData(arguments=arguments, commands=commands, help_format=help_format)

        for registered_command in commands:
            for cmd_name in registered_command.names:
                if not cmd_name.startswith("-"):
                    _extract(command_path + (cmd_name,))

    _extract()
    return completion_data


def get_completion_action(type_hint: Any) -> CompletionAction:
    """Get completion action from type hint.

    Parameters
    ----------
    type_hint : Any
        Type annotation.

    Returns
    -------
    CompletionAction
        Completion action for type.
    """
    if is_union(type_hint):
        for arg in get_args(type_hint):
            if arg is not type(None):
                action = get_completion_action(arg)
                if action != CompletionAction.NONE:
                    return action
        return CompletionAction.NONE

    origin = get_origin(type_hint)

    # For collection types, unwrap to get element type
    if is_class_and_subclass(origin, tuple(ITERABLE_TYPES)):
        args = get_args(type_hint)
        if args and len(args) >= 1:
            # list[Path], set[Path], tuple[Path, ...] -> check first arg
            return get_completion_action(args[0])

    target_type = origin or type_hint

    if target_type is Path or is_class_and_subclass(target_type, Path):
        return CompletionAction.FILES

    return CompletionAction.NONE


def clean_choice_text(text: str) -> str:
    """Clean choice text without shell-specific escaping.

    Parameters
    ----------
    text : str
        Raw choice text.

    Returns
    -------
    str
        Cleaned text (not shell-escaped).
    """
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def escape_for_shell_pattern(name: str, chars: str = "*?[]") -> str:
    """Escape glob/pattern characters for shell case patterns.

    Both bash and zsh case patterns treat glob characters as special even inside
    quotes. This function escapes them with backslashes for literal matching.

    Parameters
    ----------
    name : str
        String to escape.
    chars : str
        Characters to escape. Default covers basic glob chars.
        For zsh, also pass "()|" for extended patterns.

    Returns
    -------
    str
        Escaped string safe for shell case patterns.
    """
    # Escape backslashes first to avoid double-escaping
    result = name.replace("\\", "\\\\")
    for char in chars:
        result = result.replace(char, f"\\{char}")
    return result


def strip_markup(text: str, format: str = "markdown", max_length: int = 80) -> str:
    """Strip markup and render to plain text for shell completions.

    Converts formatted text (markdown/RST/rich) to plain text suitable for
    shell completion descriptions. Removes control characters, normalizes
    whitespace, and truncates if needed.

    Parameters
    ----------
    text : str
        Text with markup.
    format : str
        Markup format: "markdown", "rst", "rich", or "plaintext".
    max_length : int
        Maximum length before truncation.

    Returns
    -------
    str
        Plain text (not shell-escaped).
    """
    from cyclopts._markup import extract_text
    from cyclopts.help.inline_text import InlineText

    inline = InlineText.from_format(text, format=format)
    text = extract_text(inline)

    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > max_length:
        text = text[: max_length - 1] + "…"

    return text
