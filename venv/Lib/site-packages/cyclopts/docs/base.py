"""Base utilities for documentation generation."""

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cyclopts.core import App
    from cyclopts.help import HelpPanel

from cyclopts.command_spec import CommandSpec
from cyclopts.help import format_doc, format_usage


def should_show_usage(app: "App") -> bool:
    """Determine if usage should be shown for an app.

    Root apps always show usage (even without default_command, showing "app COMMAND").
    Subcommands only show usage if they have a default_command.
    This skips usage for command groups that can't be invoked directly.

    The determination is made by checking the app_stack depth:
    - Stack length of 1 means root app (just the initial frame)
    - Stack length > 1 means we're in a subcommand context (frames were pushed)

    Parameters
    ----------
    app : App
        The App instance to check.

    Returns
    -------
    bool
        True if usage should be shown.
    """
    # Check if we're in a subcommand context by examining the stack depth
    is_root = len(app.app_stack.stack) == 1

    if is_root:
        # Root app: always show usage
        return True
    else:
        # Subcommand: only show if it has a default_command
        return app.default_command is not None


def should_show_commands_list(app: "App") -> bool:
    """Determine if commands list should be shown for an app.

    Only show commands list for apps with a default_command.
    Command groups (apps without default_command) skip the list
    since their commands will be documented recursively anyway.

    Parameters
    ----------
    app : App
        The App instance to check.

    Returns
    -------
    bool
        True if commands list should be shown.
    """
    return app.default_command is not None


def _is_builtin_flag(app: "App", name: str) -> bool:
    """Check if a flag name is a built-in help or version flag.

    Parameters
    ----------
    app : App
        The App instance to check against.
    name : str
        The flag name to check.

    Returns
    -------
    bool
        True if this is a built-in help or version flag.
    """
    help_flags = set(app.app_stack.resolve("help_flags", fallback=()))
    version_flags = set(app.app_stack.resolve("version_flags", fallback=()))
    builtin_flags = help_flags | version_flags
    return name in builtin_flags


def is_all_builtin_flags(app: "App", names: Sequence[str]) -> bool:
    """Check if all names in the sequence are builtin help or version flags.

    Parameters
    ----------
    app : App
        The App instance to check against.
    names : Sequence[str]
        Sequence of flag names to check.

    Returns
    -------
    bool
        True if all names are builtin flags.
    """
    if not names:
        return False
    return all(_is_builtin_flag(app, name) for name in names)


def normalize_command_filters(
    commands_filter: list[str] | None = None,
    exclude_commands: list[str] | None = None,
) -> tuple[set[str] | None, set[str] | None]:
    """Normalize command filter lists by converting underscores to dashes.

    Parameters
    ----------
    commands_filter : list[str] | None
        List of commands to include.
    exclude_commands : list[str] | None
        List of commands to exclude.

    Returns
    -------
    tuple[set[str] | None, set[str] | None]
        Normalized include and exclude sets for O(1) lookup.
    """
    normalized_include = None
    if commands_filter is not None:
        normalized_include = {cmd.replace("_", "-") for cmd in commands_filter}

    normalized_exclude = None
    if exclude_commands:
        normalized_exclude = {cmd.replace("_", "-") for cmd in exclude_commands}

    return normalized_include, normalized_exclude


def should_include_command(
    name: str,
    parent_path: list[str],
    normalized_commands_filter: set[str] | None,
    normalized_exclude_commands: set[str] | None,
    subapp: "App",
) -> bool:
    """Determine if a command should be included based on filters.

    Parameters
    ----------
    name : str
        The command name.
    parent_path : list[str]
        Path to parent commands.
    normalized_commands_filter : set[str] | None
        Set of commands to include (already normalized).
    normalized_exclude_commands : set[str] | None
        Set of commands to exclude (already normalized).
    subapp : App
        The subcommand App instance.

    Returns
    -------
    bool
        True if the command should be included, False otherwise.
    """
    full_path = ".".join(parent_path + [name]) if parent_path else name

    if normalized_exclude_commands:
        if name in normalized_exclude_commands or full_path in normalized_exclude_commands:
            return False
        for i in range(len(parent_path)):
            parent_segment = ".".join(parent_path[: i + 1])
            if parent_segment in normalized_exclude_commands:
                return False

    if normalized_commands_filter is not None:
        if name in normalized_commands_filter or full_path in normalized_commands_filter:
            return True

        for i in range(len(parent_path)):
            parent_segment = ".".join(parent_path[: i + 1])
            if parent_segment in normalized_commands_filter:
                return True

        if hasattr(subapp, "_commands") and subapp._commands:
            for filter_cmd in normalized_commands_filter:
                if filter_cmd.startswith(full_path + "."):
                    return True

        return False

    return True


def adjust_filters_for_subcommand(
    name: str,
    normalized_commands_filter: set[str] | None,
    normalized_exclude_commands: set[str] | None,
) -> tuple[list[str] | None, list[str] | None]:
    """Adjust filter lists for subcommand context.

    Parameters
    ----------
    name : str
        The current command name.
    normalized_commands_filter : set[str] | None
        Set of commands to include (already normalized).
    normalized_exclude_commands : set[str] | None
        Set of commands to exclude (already normalized).

    Returns
    -------
    tuple[list[str] | None, list[str] | None]
        Adjusted commands_filter and exclude_commands lists (denormalized).
    """
    sub_commands_filter = None
    if normalized_commands_filter is not None:
        sub_commands_filter = []
        for filter_cmd in normalized_commands_filter:
            if filter_cmd.startswith(name + "."):
                sub_filter = filter_cmd[len(name) + 1 :]
                sub_commands_filter.append(sub_filter.replace("-", "_"))
            elif filter_cmd == name:
                sub_commands_filter = None
                break

        if sub_commands_filter is not None and not sub_commands_filter:
            sub_commands_filter = []

    sub_exclude_commands = None
    if normalized_exclude_commands:
        sub_exclude_commands = []
        for exclude_cmd in normalized_exclude_commands:
            if exclude_cmd.startswith(name + "."):
                sub_exclude = exclude_cmd[len(name) + 1 :]
                sub_exclude_commands.append(sub_exclude.replace("-", "_"))
            else:
                sub_exclude_commands.append(exclude_cmd.replace("-", "_"))

    return sub_commands_filter, sub_exclude_commands


def get_app_info(app: "App", command_chain: list[str] | None = None) -> tuple[str, str, str]:
    """Get app name, full command path, and title.

    Parameters
    ----------
    app : App
        The cyclopts App instance.
    command_chain : Optional[List[str]]
        Chain of parent commands leading to this app.

    Returns
    -------
    Tuple[str, str, str]
        (app_name, full_command, title)
    """
    if not command_chain:
        app_name = app.name[0]
        full_command = app_name
        title = app_name
    else:
        app_name = command_chain[0]
        full_command = " ".join(command_chain)
        title = full_command

    return app_name, full_command, title


def build_command_chain(command_chain: list[str] | None, command_name: str, app_name: str) -> list[str]:
    """Build command chain for a subcommand.

    Parameters
    ----------
    command_chain : Optional[List[str]]
        Current command chain.
    command_name : str
        Name of the subcommand.
    app_name : str
        Name of the root app.

    Returns
    -------
    List[str]
        Updated command chain.
    """
    if command_chain:
        return command_chain + [command_name]
    else:
        return [app_name, command_name]


def generate_anchor(command_path: str) -> str:
    """Generate a URL-friendly anchor from a command path.

    Converts spaces to hyphens and lowercases the string to match
    how markdown/HTML processors generate anchors from headings.
    Strips leading dashes to match markdown processor behavior.

    Parameters
    ----------
    command_path : str
        Full command path (e.g., "myapp files cp").

    Returns
    -------
    str
        Anchor string (e.g., "myapp-files-cp").

    Examples
    --------
    >>> generate_anchor("myapp files cp")
    'myapp-files-cp'
    >>> generate_anchor("myapp --install-completion")
    'myapp-install-completion'
    """
    anchor = command_path.lower().replace(" ", "-")
    # Collapse consecutive dashes to single dash (markdown processors do this)
    anchor = re.sub(r"-+", "-", anchor)
    return anchor


def should_skip_command(command_name: str, subapp: "App", parent_app: "App", include_hidden: bool) -> bool:
    """Check if a command should be skipped.

    Parameters
    ----------
    command_name : str
        Name of the command.
    subapp : App
        The subcommand App instance.
    parent_app : App
        The parent App instance.
    include_hidden : bool
        Whether to include hidden commands.

    Returns
    -------
    bool
        True if command should be skipped.
    """
    if _is_builtin_flag(parent_app, command_name):
        return True

    if not isinstance(subapp, type(parent_app)):
        return True

    if not include_hidden and not subapp.show:
        return True

    return False


def filter_help_entries(app: "App", panel: "HelpPanel", include_hidden: bool) -> list[Any]:
    """Filter help panel entries based on visibility settings.

    Parameters
    ----------
    app : App
        The App instance to check against.
    panel : HelpPanel
        The help panel to filter.
    include_hidden : bool
        Whether to include hidden entries.

    Returns
    -------
    List[Any]
        Filtered panel entries.
    """
    if include_hidden:
        return panel.entries

    return [e for e in panel.entries if not (e.names and is_all_builtin_flags(app, e.names))]


def extract_description(app: "App", help_format: str) -> Any | None:
    """Extract app description.

    Parameters
    ----------
    app : App
        The App instance.
    help_format : str
        Help format type.

    Returns
    -------
    Optional[Any]
        The extracted description object, or None.
    """
    description = format_doc(app, help_format)
    return description


def extract_usage(app: "App") -> Any | None:
    """Extract usage string.

    Parameters
    ----------
    app : App
        The App instance.

    Returns
    -------
    Optional[Any]
        The extracted usage object, or None.
    """
    if app.usage is not None:
        return app.usage if app.usage else None

    usage = format_usage(app, [])
    return usage


def format_usage_line(usage_text: str, command_chain: list[str], prefix: str = "") -> str:
    """Format usage line with proper command path.

    Parameters
    ----------
    usage_text : str
        Raw usage text.
    command_chain : List[str]
        Command chain for the app.
    prefix : str
        Optional prefix for the usage line (e.g., "$").

    Returns
    -------
    str
        Formatted usage line.
    """
    if not usage_text:
        return ""

    if "Usage:" in usage_text:
        usage_text = usage_text.replace("Usage:", "").strip()

    full_command = " ".join(command_chain) if command_chain else ""

    parts = usage_text.split(None, 1)
    if len(parts) > 1 and command_chain:
        usage_line = f"{prefix} {full_command} {parts[1]}" if prefix else f"{full_command} {parts[1]}"
    elif command_chain:
        usage_line = f"{prefix} {full_command}" if prefix else full_command
    else:
        usage_line = f"{prefix} {usage_text}" if prefix else usage_text

    return usage_line.strip()


def iterate_commands(app: "App", include_hidden: bool = False):
    """Iterate through app commands, yielding valid resolved subapps.

    Automatically resolves CommandSpec instances to App instances.
    Each unique subapp is yielded only once (first occurrence wins).

    Parameters
    ----------
    app : App
        The App instance.
    include_hidden : bool
        Whether to include hidden commands.

    Yields
    ------
    Tuple[str, App]
        (command_name, resolved_subapp) for each valid command.
    """
    if not app._commands:
        return

    seen: set[int] = set()

    for name, app_or_spec in app._commands.items():
        if _is_builtin_flag(app, name):
            continue

        subapp = app_or_spec.resolve(app) if isinstance(app_or_spec, CommandSpec) else app_or_spec

        if not isinstance(subapp, type(app)):
            continue

        if not include_hidden and not subapp.show:
            continue

        # Skip if we've already yielded this app (alias)
        app_id = id(subapp)
        if app_id in seen:
            continue
        seen.add(app_id)

        yield name, subapp
