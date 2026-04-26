from typing import TYPE_CHECKING, Any

from cyclopts.command_spec import CommandSpec
from cyclopts.group import Group
from cyclopts.utils import frozen

if TYPE_CHECKING:
    from cyclopts.core import App


@frozen
class RegisteredCommand:
    """A command with the names it was registered under.

    Parameters
    ----------
    names : tuple[str, ...]
        All names (including aliases) this command is registered under.
    app : App | CommandSpec
        The command's App or unresolved CommandSpec instance.
    """

    names: tuple[str, ...]
    app: "App | CommandSpec"


def _create_or_append(
    group_mapping: list[tuple[Group, list[Any]]],
    group: str | Group,
    element: Any,
):
    # updates group_mapping inplace.
    if isinstance(group, str):
        group = Group(group)
    elif isinstance(group, Group):
        pass
    else:
        raise TypeError

    for mapping in group_mapping:
        if mapping[0].name == group.name:
            mapping[1].append(element)
            break
    else:
        group_mapping.append((group, [element]))


def groups_from_app(app: "App", resolve_lazy: bool = False) -> list[tuple[Group, list[RegisteredCommand]]]:
    """Extract Group/App association from all commands of ``app``.

    Parameters
    ----------
    app : App
        The application to extract groups from.
    resolve_lazy : bool
        If ``True``, resolve lazy commands (import their modules) to include them
        in the output. If ``False`` (default), skip unresolved lazy commands.
        Set to ``True`` when generating static artifacts that need all commands,
        such as shell completion scripts.

    Returns
    -------
    list
        List of items where each item is a tuple containing:

        * :class:`.Group` - The group

        * ``list[RegisteredCommand]`` - List of RegisteredCommand tuples containing
          the registered names and app instance for each command.
    """
    assert not isinstance(app.group_commands, str)
    group_commands = app.group_commands or Group.create_default_commands()

    # First pass: collect all registered names and unique apps
    # Use __iter__ and __getitem__ to properly handle meta parents
    #
    # Skip unresolved lazy commands to avoid importing modules unnecessarily.
    # Group assignment for unresolved commands uses the group= field from
    # CommandSpec (set at registration time). Groups defined only inside
    # lazy modules won't be available until those modules are imported.
    app_names: dict[int, list[str]] = {}
    unique_apps: dict[int, App] = {}
    lazy_names: dict[int, list[str]] = {}
    unique_lazy: dict[int, CommandSpec] = {}
    for name in app:
        cmd = app._get_item(name, recurse_meta=True)
        if isinstance(cmd, CommandSpec) and not cmd.is_resolved:
            if not resolve_lazy:
                # Skip hidden lazy commands early to avoid keeping
                # an otherwise-empty group alive.
                if not cmd.show:
                    continue
                cmd_id = id(cmd)
                lazy_names.setdefault(cmd_id, []).append(name)
                if cmd_id not in unique_lazy:
                    unique_lazy[cmd_id] = cmd
                continue
        subapp = app[name]
        app_id = id(subapp)
        app_names.setdefault(app_id, []).append(name)
        if app_id not in unique_apps:
            unique_apps[app_id] = subapp

    group_mapping: list[tuple[Group, list[RegisteredCommand]]] = [
        (group_commands, []),
    ]

    # Extract Group objects from resolved apps
    for subapp in unique_apps.values():
        assert isinstance(subapp.group, tuple)
        for group in subapp.group:
            if isinstance(group, Group):
                for mapping in group_mapping:
                    if mapping[0] is group:
                        break
                    elif mapping[0].name == group.name:
                        raise ValueError(f'Command Group "{group.name}" already exists.')
                else:
                    group_mapping.append((group, []))

    # Assign resolved apps to groups with their registered names
    for app_id, subapp in unique_apps.items():
        names = tuple(app_names[app_id])
        registered_command = RegisteredCommand(names, subapp)
        if subapp.group:
            assert isinstance(subapp.group, tuple)
            for group in subapp.group:
                _create_or_append(group_mapping, group, registered_command)
        else:
            _create_or_append(group_mapping, group_commands, registered_command)

    # Extract Group objects from unresolved lazy commands
    for cmd in unique_lazy.values():
        if cmd.group is not None:
            groups = cmd.group if isinstance(cmd.group, tuple) else (cmd.group,)
            for group in groups:
                if isinstance(group, Group):
                    for mapping in group_mapping:
                        if mapping[0] is group:
                            break
                        elif mapping[0].name == group.name:
                            raise ValueError(f'Command Group "{group.name}" already exists.')
                    else:
                        group_mapping.append((group, []))

    # Assign unresolved lazy commands to their group (or default)
    for cmd_id, cmd in unique_lazy.items():
        names = tuple(lazy_names[cmd_id])
        registered_command = RegisteredCommand(names, cmd)
        if cmd.group is not None:
            groups = cmd.group if isinstance(cmd.group, tuple) else (cmd.group,)
            for group in groups:
                _create_or_append(group_mapping, group, registered_command)
        else:
            _create_or_append(group_mapping, group_commands, registered_command)

    # Remove empty groups
    group_mapping = [x for x in group_mapping if x[1]]

    # Sort alphabetically by name
    group_mapping.sort(key=lambda x: x[0].name)

    return group_mapping


def inverse_groups_from_app(input_app: "App", resolve_lazy: bool = False) -> list[tuple["App", list[Group]]]:
    out = []
    seen_apps = []
    for group, registered_commands in groups_from_app(input_app, resolve_lazy=resolve_lazy):
        for registered_command in registered_commands:
            app = registered_command.app
            if isinstance(app, CommandSpec):
                continue
            try:
                index = seen_apps.index(app)
            except ValueError:
                index = len(out)
                out.append((app, []))
                seen_apps.append(app)
            out[index][1].append(group)
    return out
