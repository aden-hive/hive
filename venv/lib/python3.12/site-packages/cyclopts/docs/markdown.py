"""Documentation generation functions for cyclopts apps."""

from typing import TYPE_CHECKING

from cyclopts._markup import extract_text
from cyclopts.core import DEFAULT_FORMAT
from cyclopts.docs.base import (
    adjust_filters_for_subcommand,
    build_command_chain,
    extract_description,
    extract_usage,
    format_usage_line,
    generate_anchor,
    get_app_info,
    is_all_builtin_flags,
    iterate_commands,
    normalize_command_filters,
    should_include_command,
    should_show_commands_list,
    should_show_usage,
)

if TYPE_CHECKING:
    from cyclopts.core import App


def _collect_commands_for_toc(
    app: "App",
    include_hidden: bool = False,
    prefix: str = "",
    commands_filter: list[str] | None = None,
    exclude_commands: list[str] | None = None,
    parent_path: list[str] | None = None,
    skip_filtered_command: bool = False,
) -> list[tuple[str, "App"]]:
    """Recursively collect all commands for table of contents.

    Returns a list of (display_name, app) tuples.
    """
    commands = []

    if parent_path is None:
        parent_path = []

    normalized_commands_filter, normalized_exclude_commands = normalize_command_filters(
        commands_filter, exclude_commands
    )

    for name, subapp in iterate_commands(app, include_hidden):
        if not should_include_command(
            name, parent_path, normalized_commands_filter, normalized_exclude_commands, subapp
        ):
            continue

        # Skip the command itself if it's the single filtered command with subcommands
        # (we'll include its children directly instead)
        skip_this_command = skip_filtered_command and subapp._commands

        if not skip_this_command:
            display_name = f"{prefix}{name}" if prefix else name
            commands.append((display_name, subapp))

        # Collect nested commands
        nested_path = parent_path + [name]
        # Always include parent in prefix for nested commands (for correct paths)
        nested_prefix = f"{prefix}{name} "
        nested = _collect_commands_for_toc(
            subapp,
            include_hidden=include_hidden,
            prefix=nested_prefix,
            commands_filter=commands_filter,
            exclude_commands=exclude_commands,
            parent_path=nested_path,
            skip_filtered_command=False,  # Only skip at the top level
        )
        commands.extend(nested)

    return commands


def _generate_toc_entries(lines: list[str], commands: list[tuple[str, "App"]]) -> None:
    """Generate TOC entries with proper indentation.

    Parameters
    ----------
    lines : list[str]
        List to append TOC entries to.
    commands : list[tuple[str, "App"]]
        List of (display_name, app) tuples.
    """
    anchor_counts: dict[str, int] = {}

    for display_name, _app in commands:
        depth = display_name.count(" ") - 1
        indent = "    " * depth

        cmd_name = display_name.split()[-1]
        anchor = generate_anchor(display_name)

        if anchor in anchor_counts:
            anchor_counts[anchor] += 1
            anchor = f"{anchor}_{anchor_counts[anchor]}"
        else:
            anchor_counts[anchor] = 0

        lines.append(f"{indent}- [`{cmd_name}`](#{anchor})")


def _build_command_map(app: "App", include_hidden: bool = True) -> dict[str, "App"]:
    """Build mapping of command names to App objects.

    Parameters
    ----------
    app : App
        The app to extract commands from.
    include_hidden : bool
        Whether to include hidden commands.

    Returns
    -------
    dict[str, App]
        Mapping of command names to App instances.
    """
    command_map = {}
    if app._commands:
        for name, subapp in iterate_commands(app, include_hidden):
            command_map[name] = subapp
    return command_map


def _append_if_present(lines: list[str], content: str, add_blank: bool = True) -> None:
    """Append content to lines if present, optionally adding blank line.

    Parameters
    ----------
    lines : list[str]
        List to append to.
    content : str
        Content to append (only if non-empty).
    add_blank : bool
        Whether to add a blank line after content.
    """
    if content:
        lines.append(content)
    if add_blank:
        lines.append("")


def _render_description_section(app: "App", help_format: str, lines: list[str]) -> None:
    """Extract and render app description.

    Parameters
    ----------
    app : App
        The app to extract description from.
    help_format : str
        Help format (e.g., "markdown", "rich").
    lines : list[str]
        List to append description to.
    """
    description = extract_description(app, help_format)
    if description:
        # Preserve markup when help_format matches output format (markdown)
        preserve = help_format in ("markdown", "md")
        desc_text = extract_text(description, None, preserve_markup=preserve)
        if desc_text:
            lines.append(desc_text.strip())
            lines.append("")


def _render_usage_section(app: "App", command_chain: list[str], lines: list[str]) -> None:
    """Render usage console block.

    Parameters
    ----------
    app : App
        The app to extract usage from.
    command_chain : list[str]
        Command chain for usage line.
    lines : list[str]
        List to append usage to.
    """
    if should_show_usage(app):
        usage = extract_usage(app)
        if usage:
            lines.append("```console")
            if isinstance(usage, str):
                usage_text = usage
            else:
                usage_text = extract_text(usage, None, preserve_markup=False)
            usage_line = format_usage_line(usage_text, command_chain)
            lines.append(usage_line)
            lines.append("```")
            lines.append("")


def _render_toc(
    app: "App",
    app_name: str,
    include_hidden: bool,
    commands_filter: list[str] | None,
    exclude_commands: list[str] | None,
    skip_filtered_command: bool,
    lines: list[str],
) -> None:
    """Generate and render table of contents.

    Parameters
    ----------
    app : App
        The app to generate TOC for.
    app_name : str
        Application name for TOC prefixes.
    include_hidden : bool
        Whether to include hidden commands.
    commands_filter : list[str] | None
        Commands to include.
    exclude_commands : list[str] | None
        Commands to exclude.
    skip_filtered_command : bool
        Whether to skip the single filtered command in TOC.
    lines : list[str]
        List to append TOC to.
    """
    # Collect all commands recursively for TOC
    toc_commands = _collect_commands_for_toc(
        app,
        include_hidden=include_hidden,
        prefix=f"{app_name} " if app_name else "",
        commands_filter=commands_filter,
        exclude_commands=exclude_commands,
        skip_filtered_command=skip_filtered_command,
    )
    if toc_commands:
        lines.append("## Table of Contents")
        lines.append("")
        _generate_toc_entries(lines, toc_commands)
        lines.append("")


def _render_parameter_panel(panel, formatter, lines: list[str]) -> None:
    """Render a parameter panel as-is.

    Parameters
    ----------
    panel : HelpPanel
        The parameter panel to render.
    formatter : MarkdownFormatter
        Formatter to use for rendering.
    lines : list[str]
        List to append rendered content to.
    """
    # Render panel content first to check if there's anything
    formatter.reset()
    panel_copy = panel.copy(title="")
    formatter(None, None, panel_copy)
    output = formatter.get_output().strip()

    # Only render if there's actual content
    if output:
        if panel.title:
            lines.append(f"**{panel.title}**:\n")
        lines.append(output)
        lines.append("")


def _filter_command_entries(
    entries: list,
    command_map: dict[str, "App"],
    parent_path: list[str],
    normalized_filter: set[str] | None,
    normalized_exclude: set[str] | None,
) -> list:
    """Filter command entries based on inclusion/exclusion rules.

    Parameters
    ----------
    entries : list
        Command entries to filter.
    command_map : dict[str, App]
        Mapping of command names to App objects.
    parent_path : list[str]
        Parent command path.
    normalized_filter : set[str] | None
        Normalized filter set.
    normalized_exclude : set[str] | None
        Normalized exclude set.

    Returns
    -------
    list
        Filtered command entries.
    """
    filtered_entries = []
    for entry in entries:
        if entry.names:
            cmd_name = entry.names[0]
            subapp = command_map.get(cmd_name)
            if subapp is None:
                # If command not in map and no filters, include it
                if normalized_filter is None and normalized_exclude is None:
                    filtered_entries.append(entry)
            else:
                # Check if command should be included
                if should_include_command(cmd_name, parent_path, normalized_filter, normalized_exclude, subapp):
                    filtered_entries.append(entry)
    return filtered_entries


def generate_markdown_docs(
    app: "App",
    recursive: bool = True,
    include_hidden: bool = False,
    heading_level: int = 1,
    max_heading_level: int = 6,
    command_chain: list[str] | None = None,
    generate_toc: bool = True,
    flatten_commands: bool = False,
    commands_filter: list[str] | None = None,
    exclude_commands: list[str] | None = None,
    no_root_title: bool = False,
    code_block_title: bool = False,
    skip_preamble: bool = False,
) -> str:
    """Generate markdown documentation for a CLI application.

    Parameters
    ----------
    app : App
        The cyclopts App instance to document.
    recursive : bool
        If True, generate documentation for all subcommands recursively.
        Default is True.
    include_hidden : bool
        If True, include hidden commands/parameters in documentation.
        Default is False.
    heading_level : int
        Starting heading level for the main application title.
        Default is 1 (single #).
    max_heading_level : int
        Maximum heading level to use. Headings deeper than this will be capped
        at this level. Standard Markdown supports levels 1-6.
        Default is 6.
    command_chain : list[str]
        Internal parameter to track command hierarchy.
        Default is None.
    generate_toc : bool
        If True, generate a table of contents for multi-command apps.
        Default is True.
    flatten_commands : bool
        If True, generate all commands at the same heading level instead of nested.
        Default is False.
    commands_filter : list[str] | None
        If specified, only include commands in this list.
        Supports nested command paths like "db.migrate".
        Default is None (include all commands).
    exclude_commands : list[str] | None
        If specified, exclude commands in this list.
        Supports nested command paths like "db.migrate".
        Default is None (no exclusions).
    no_root_title : bool
        If True, skip the root application title. Used for plugin contexts.
        Default is False.
    skip_preamble : bool
        If True, skip the description and usage sections for the target command
        when filtering to a single command via ``commands_filter``.
        Useful when the user provides their own section introduction.
        Default is False.

    Returns
    -------
    str
        The generated markdown documentation.
    """
    from cyclopts.help.formatters.markdown import MarkdownFormatter

    # Build the main documentation
    lines = []

    if command_chain is None:
        command_chain = []
        is_root = True
    else:
        is_root = False

    # Determine if we should skip the current level's content
    # When filtering to a single command, skip the root app content
    skip_current_level = is_root and commands_filter is not None and len(commands_filter) == 1

    # Determine the app name and full command path
    app_name, full_command, base_title = get_app_info(app, command_chain)
    # Always use full command path for nested commands to avoid anchor collisions
    # (e.g., "files cp" and "other cp" would both generate #cp without this)
    if command_chain:
        # Show full command path (same for both hierarchical and flattened modes)
        title = f"`{full_command}`" if code_block_title else full_command
    else:
        # Root app: use base title
        title = base_title

    # Add title for all levels (unless skipping root title or skipping current level entirely)
    if not skip_current_level and not (no_root_title and is_root):
        effective_level = min(heading_level, max_heading_level)
        lines.append(f"{'#' * effective_level} {title}")
        lines.append("")

    # Get help format (needed for both current level and recursive docs)
    help_format = app.app_stack.resolve("help_format", fallback=DEFAULT_FORMAT)

    # Add usage section first (skip if skipping current level or skip_preamble is True)
    if not skip_current_level and not skip_preamble:
        _render_usage_section(app, command_chain, lines)

    # Add application description (skip if skipping current level or skip_preamble is True)
    if not skip_current_level and not skip_preamble:
        _render_description_section(app, help_format, lines)

    # Generate table of contents if this is the root level and has commands
    if generate_toc and not command_chain and app._commands:
        _render_toc(app, app_name, include_hidden, commands_filter, exclude_commands, skip_current_level, lines)

    # Get help panels for the current app (skip if skipping current level)
    # Use app_stack context - if caller set up parent context, it will be stacked
    if not skip_current_level:
        with app.app_stack([app]):
            help_panels_with_groups = app._assemble_help_panels([], help_format)

        # Set up command filtering (used for command panels only)
        normalized_commands_filter, normalized_exclude_commands = normalize_command_filters(
            commands_filter, exclude_commands
        )
        parent_path = []

        # Build a mapping of command names to App objects for filtering
        command_map = _build_command_map(app, include_hidden=True)

        # Create formatter
        formatter = MarkdownFormatter(
            heading_level=heading_level + 1,
            include_hidden=include_hidden,
            table_style="list",
        )

        # Iterate through panels in the order provided by _assemble_help_panels (already sorted)
        for group, panel in help_panels_with_groups:
            # Skip hidden groups
            if not include_hidden and group and not group.show:
                continue

            if panel.format == "command":
                # Always filter out built-in flags (--help, --version) from command panels
                # These are standard CLI flags, not commands, and shouldn't appear here
                command_entries = [e for e in panel.entries if not (e.names and is_all_builtin_flags(app, e.names))]

                if not command_entries:
                    continue  # Skip empty panel

                # Apply command filtering
                filtered_entries = _filter_command_entries(
                    command_entries, command_map, parent_path, normalized_commands_filter, normalized_exclude_commands
                )

                # Only render if there are filtered entries
                if filtered_entries:
                    if panel.title:
                        lines.append(f"**{panel.title}**:\n")

                    # Render command entries with hyperlinks to their sections
                    for entry in filtered_entries:
                        if entry.names:
                            cmd_name = entry.names[0]
                            # Generate anchor for the full command path
                            # Use full_command (not app_name) to include the complete path for nested apps
                            full_cmd_path = f"{full_command} {cmd_name}"
                            anchor = generate_anchor(full_cmd_path)
                            desc_text = (
                                extract_text(entry.description, None, preserve_markup=True) if entry.description else ""
                            )
                            if desc_text:
                                lines.append(f"* [`{cmd_name}`](#{anchor}): {desc_text}")
                            else:
                                lines.append(f"* [`{cmd_name}`](#{anchor})")
                    lines.append("")
            elif panel.format == "parameter":
                # Handle parameter panels - split into arguments and options if needed
                _render_parameter_panel(panel, formatter, lines)
    else:
        # When skipping current level, still need to set up filter variables for recursive docs
        normalized_commands_filter, normalized_exclude_commands = normalize_command_filters(
            commands_filter, exclude_commands
        )
        parent_path = []

    # Handle recursive documentation for subcommands
    if app._commands:
        # Iterate through registered commands using iterate_commands helper
        # This automatically resolves CommandSpec instances
        for name, subapp in iterate_commands(app, include_hidden):
            if not should_include_command(
                name, parent_path, normalized_commands_filter, normalized_exclude_commands, subapp
            ):
                continue

            # Build the command chain for this subcommand
            sub_command_chain = build_command_chain(command_chain, name, app_name)

            # Determine heading level for subcommand
            if flatten_commands:
                sub_heading_level = heading_level
            elif no_root_title and not command_chain:
                # When root title is skipped, subcommands "take over" the root heading level
                sub_heading_level = heading_level
            else:
                sub_heading_level = heading_level + 1

            # Check if we should skip this command's title heading
            # Skip title when: root was skipped (single command filter) AND this is the direct target
            # OR this is an intermediate command on the path to a nested target
            # This allows the markdown author's section title to serve as the heading
            is_single_filter = commands_filter is not None and len(commands_filter) == 1
            is_exact_target = is_single_filter and commands_filter is not None and name == commands_filter[0]
            is_intermediate_path = (
                is_single_filter and commands_filter is not None and commands_filter[0].startswith(name + ".")
            )

            skip_this_command_title = skip_current_level and is_exact_target
            # Also skip intermediate commands entirely when skip_preamble is set
            skip_intermediate = skip_preamble and skip_current_level and is_intermediate_path
            # Skip preamble for the exact target when skip_preamble is set (even in recursive calls)
            skip_target_preamble = skip_preamble and is_exact_target

            # Generate subcommand title (skip if this is the single filtered command at root level,
            # or if this is an intermediate command and skip_preamble is set)
            if not skip_this_command_title and not skip_intermediate:
                # Always use full command path to avoid anchor collisions
                display_name = " ".join(sub_command_chain)
                display_fmt = f"`{display_name}`" if code_block_title else display_name
                effective_sub_level = min(sub_heading_level, max_heading_level)
                lines.append(f"{'#' * effective_sub_level} {display_fmt}")
                lines.append("")

            # Get subapp help - show description, usage, and panels for included commands
            # Skip preamble (description + usage) if:
            # - skip_preamble is True and this is the exact target (even in recursive calls)
            # - or this is an intermediate command on the path to a nested target
            skip_this_preamble = skip_target_preamble or skip_intermediate

            # Include parent app in the stack so default_parameter is properly inherited
            with subapp.app_stack([app, subapp]):
                sub_help_format = subapp.app_stack.resolve("help_format", fallback=help_format)
                # Preserve markup when sub_help_format matches output format (markdown)
                preserve_sub = sub_help_format in ("markdown", "md")

                if not skip_this_preamble:
                    # Generate usage first for subcommand
                    _render_usage_section(subapp, sub_command_chain, lines)
                    _render_description_section(subapp, sub_help_format, lines)

                # Only show subcommand panels if we're in recursive mode
                # (Otherwise we just show the basic info about this command)
                if recursive:
                    # Get help panels for subcommand (already sorted)
                    sub_panels = subapp._assemble_help_panels([], sub_help_format)

                    # Set up command filtering for this subcommand
                    sub_commands_filter_for_panel, sub_exclude_commands_for_panel = adjust_filters_for_subcommand(
                        name, normalized_commands_filter, normalized_exclude_commands
                    )
                    normalized_sub_filter_panel, normalized_sub_exclude_panel = normalize_command_filters(
                        sub_commands_filter_for_panel, sub_exclude_commands_for_panel
                    )

                    # Build a map of command names to App objects for filtering
                    sub_command_map = _build_command_map(subapp, include_hidden=True)

                    # Build parent path for nested commands
                    # Use empty path since filter was already adjusted to strip current level's prefix
                    nested_parent_path_for_panel = []

                    # Create formatter
                    if flatten_commands:
                        panel_heading_level = heading_level + 1
                    else:
                        panel_heading_level = heading_level + 2
                    sub_formatter = MarkdownFormatter(
                        heading_level=panel_heading_level, include_hidden=include_hidden, table_style="list"
                    )

                    # Check if we'll be recursively documenting commands
                    will_recurse = recursive and subapp._commands

                    # Iterate through panels in order
                    for group, panel in sub_panels:
                        # Skip hidden groups
                        if not include_hidden and group and not group.show:
                            continue

                        if panel.format == "command" and should_show_commands_list(subapp):
                            # Always filter out built-in flags (--help, --version) from command panels
                            command_entries_list = [
                                e for e in panel.entries if not (e.names and is_all_builtin_flags(subapp, e.names))
                            ]

                            if not command_entries_list:
                                continue  # Skip empty panel

                            # Apply command filtering for command panels
                            if will_recurse:
                                # Show simple command list
                                command_entries = []
                                for entry in command_entries_list:
                                    if entry.names:
                                        cmd_name = entry.names[0]
                                        sub_cmd_app = sub_command_map.get(cmd_name)
                                        if sub_cmd_app and not should_include_command(
                                            cmd_name,
                                            nested_parent_path_for_panel,
                                            normalized_sub_filter_panel,
                                            normalized_sub_exclude_panel,
                                            sub_cmd_app,
                                        ):
                                            continue

                                        desc_text = (
                                            extract_text(entry.description, None, preserve_markup=preserve_sub)
                                            if entry.description
                                            else ""
                                        )
                                        # Generate anchor for the full command path
                                        full_cmd_path = " ".join(sub_command_chain + [cmd_name])
                                        anchor = generate_anchor(full_cmd_path)
                                        if desc_text:
                                            command_entries.append(f"* [`{cmd_name}`](#{anchor}): {desc_text}")
                                        else:
                                            command_entries.append(f"* [`{cmd_name}`](#{anchor})")

                                if command_entries:
                                    if panel.title:
                                        lines.append(f"**{panel.title}**:\n")
                                    lines.extend(command_entries)
                                    lines.append("")
                            else:
                                # Show full command panel
                                filtered_entries = []
                                for entry in command_entries_list:
                                    if entry.names:
                                        cmd_name = entry.names[0]
                                        sub_cmd_app = sub_command_map.get(cmd_name)
                                        if sub_cmd_app and not should_include_command(
                                            cmd_name,
                                            nested_parent_path_for_panel,
                                            normalized_sub_filter_panel,
                                            normalized_sub_exclude_panel,
                                            sub_cmd_app,
                                        ):
                                            continue
                                        filtered_entries.append(entry)

                                if filtered_entries:
                                    if panel.title:
                                        lines.append(f"**{panel.title}**:\n")

                                    sub_formatter.reset()
                                    filtered_panel = panel.__class__(
                                        title="",
                                        entries=filtered_entries,
                                        format=panel.format,
                                        description=panel.description,
                                    )
                                    sub_formatter(None, None, filtered_panel)
                                    output = sub_formatter.get_output().strip()
                                    if output:
                                        lines.append(output)
                                    lines.append("")
                        elif panel.format == "parameter":
                            # Handle parameter panels - split into arguments and options if needed
                            _render_parameter_panel(panel, sub_formatter, lines)

                # Process nested commands INSIDE the with block so context is preserved
                if recursive and subapp._commands:
                    sub_commands_filter, sub_exclude_commands = adjust_filters_for_subcommand(
                        name, normalized_commands_filter, normalized_exclude_commands
                    )

                    normalized_sub_filter, normalized_sub_exclude = normalize_command_filters(
                        sub_commands_filter, sub_exclude_commands
                    )

                    # Build parent path for nested commands
                    # Use empty path since filter was already adjusted to strip current level's prefix
                    nested_parent_path = []

                    for nested_name, nested_app in iterate_commands(subapp, include_hidden):
                        if not should_include_command(
                            nested_name, nested_parent_path, normalized_sub_filter, normalized_sub_exclude, nested_app
                        ):
                            continue

                        # Build nested command chain (always use full path for correct usage)
                        nested_command_chain = build_command_chain(sub_command_chain, nested_name, app_name)
                        # Determine heading level for nested commands
                        if flatten_commands:
                            nested_heading_level = heading_level
                        elif skip_this_command_title:
                            # When parent command's title was skipped, promote nested commands to parent's level
                            nested_heading_level = sub_heading_level
                        else:
                            nested_heading_level = sub_heading_level + 1
                        # Determine commands_filter for the recursive call
                        # Adjust filter to strip current command's prefix for the nested level
                        if normalized_sub_filter:
                            nested_commands_filter, _ = adjust_filters_for_subcommand(
                                nested_name, normalized_sub_filter, normalized_sub_exclude
                            )
                        else:
                            nested_commands_filter = None

                        # Check if this nested command is the target for skip_preamble purposes
                        # This handles nested paths like "parent.child" where "child" is the target
                        nested_is_target = (
                            skip_preamble
                            and sub_commands_filter is not None
                            and len(sub_commands_filter) == 1
                            and nested_name == sub_commands_filter[0]
                        )
                        # Also check if this is an intermediate on a deeper path
                        nested_is_intermediate = (
                            skip_preamble
                            and sub_commands_filter is not None
                            and len(sub_commands_filter) == 1
                            and sub_commands_filter[0].startswith(nested_name + ".")
                        )

                        # Set up context for nested_app, then recurse
                        # The recursive call's app_stack([app]) will stack on top of this
                        with nested_app.app_stack([subapp, nested_app]):
                            nested_docs = generate_markdown_docs(
                                nested_app,
                                recursive=recursive,
                                include_hidden=include_hidden,
                                heading_level=nested_heading_level,
                                max_heading_level=max_heading_level,
                                command_chain=nested_command_chain,
                                generate_toc=False,  # Don't generate TOC for nested commands
                                flatten_commands=flatten_commands,
                                commands_filter=nested_commands_filter,
                                exclude_commands=sub_exclude_commands,
                                no_root_title=nested_is_intermediate,  # Skip title for intermediate paths
                                code_block_title=code_block_title,
                                skip_preamble=nested_is_target or nested_is_intermediate,
                            )
                        # Just append the generated docs - no title replacement
                        lines.append(nested_docs)
                        lines.append("")

    # Join all lines into final document
    doc = "\n".join(lines).rstrip() + "\n"

    # Normalize multiple consecutive blank lines to a single blank line
    # This ensures consistent spacing regardless of how content was assembled
    import re

    doc = re.sub(r"\n{3,}", "\n\n", doc)

    return doc
