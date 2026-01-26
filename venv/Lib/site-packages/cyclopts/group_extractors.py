from typing import TYPE_CHECKING, Any, NamedTuple

from cyclopts.command_spec import CommandSpec
from cyclopts.group import Group

if TYPE_CHECKING:
    from cyclopts.core import App


class RegisteredCommand(NamedTuple):
    """An App with the names it was registered under.

    Attributes
    ----------
    names : tuple[str, ...]
        All names (including aliases) this command is registered under.
    app : "App"
        The command's App instance.
    """

    names: tuple[str, ...]
    app: "App"


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


def groups_from_app(app: "App") -> list[tuple[Group, list[RegisteredCommand]]]:
    """Extract Group/App association from all commands of ``app``.

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
    # Limitation: Group objects defined in unresolved lazy modules won't be
    # available until those modules are imported. To avoid this, define Group
    # objects in non-lazy modules. See docs/source/lazy_loading.rst for details.
    app_names: dict[int, list[str]] = {}
    unique_apps: dict[int, App] = {}
    for name in app:
        cmd = app._get_item(name, recurse_meta=True)
        if isinstance(cmd, CommandSpec) and not cmd.is_resolved:
            continue
        subapp = app[name]
        app_id = id(subapp)
        app_names.setdefault(app_id, []).append(name)
        if app_id not in unique_apps:
            unique_apps[app_id] = subapp

    group_mapping: list[tuple[Group, list[RegisteredCommand]]] = [
        (group_commands, []),
    ]

    # Extract Group objects
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

    # Assign apps to groups with their registered names
    for app_id, subapp in unique_apps.items():
        names = tuple(app_names[app_id])
        registered_command = RegisteredCommand(names, subapp)
        if subapp.group:
            assert isinstance(subapp.group, tuple)
            for group in subapp.group:
                _create_or_append(group_mapping, group, registered_command)
        else:
            _create_or_append(group_mapping, app.group_commands or Group.create_default_commands(), registered_command)

    # Remove empty groups
    group_mapping = [x for x in group_mapping if x[1]]

    # Sort alphabetically by name
    group_mapping.sort(key=lambda x: x[0].name)

    return group_mapping


def inverse_groups_from_app(input_app: "App") -> list[tuple["App", list[Group]]]:
    out = []
    seen_apps = []
    for group, registered_commands in groups_from_app(input_app):
        for registered_command in registered_commands:
            app = registered_command.app
            try:
                index = seen_apps.index(app)
            except ValueError:
                index = len(out)
                out.append((app, []))
                seen_apps.append(app)
            out[index][1].append(group)
    return out
