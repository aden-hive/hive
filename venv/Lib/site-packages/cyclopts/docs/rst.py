"""RST documentation generation functions for cyclopts apps."""

from typing import TYPE_CHECKING

from cyclopts._markup import extract_text
from cyclopts.docs.base import (
    adjust_filters_for_subcommand,
    extract_description,
    extract_usage,
    generate_anchor,
    get_app_info,
    is_all_builtin_flags,
    iterate_commands,
    normalize_command_filters,
    should_include_command,
    should_show_usage,
)

if TYPE_CHECKING:
    from cyclopts.core import App


def make_rst_code_block_title(title: str) -> list[str]:
    """Create an RST code block containing the title.

    Parameters
    ----------
    title : str
        Title text to display in code block.

    Returns
    -------
    list[str]
        RST formatted code block lines.
    """
    return [
        ".. code-block:: text",
        "",
        f"   {title}",
    ]


def make_rst_section_header(title: str, level: int) -> list[str]:
    """Create an RST section header.

    Parameters
    ----------
    title : str
        Section title.
    level : int
        Heading level (1-6).

    Returns
    -------
    list[str]
        RST formatted section header lines.
    """
    markers = {
        1: "=",
        2: "-",
        3: "^",
        4: '"',
        5: "'",
        6: "~",
    }

    if level < 1:
        level = 1
    elif level > 6:
        level = 6

    marker = markers[level]
    underline = marker * len(title)

    if level == 1:
        return [underline, title, underline]
    else:
        return [title, underline]


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


def _generate_toc(lines: list[str]) -> None:
    """Generate table of contents using RST contents directive.

    The `.. contents::` directive automatically generates a TOC from
    section headings, which is the idiomatic approach for RST/Sphinx.
    """
    lines.append(".. contents:: Table of Contents")
    lines.append("   :local:")
    lines.append("   :depth: 6")
    lines.append("")


def generate_rst_docs(
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
    """Generate reStructuredText documentation for a CLI application.

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
        Default is 1 (uses '=' markers).
    max_heading_level : int
        Maximum heading level to use. Headings deeper than this will be capped
        at this level. RST uses different underline characters for each level.
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
    commands_filter : list[str], optional
        If specified, only include commands in this list.
        Supports nested command paths like "db.migrate".
        Default is None (include all commands).
    exclude_commands : list[str], optional
        If specified, exclude commands in this list.
        Supports nested command paths like "db.migrate".
        Default is None (no exclusions).
    no_root_title : bool
        If True, skip generating the root application title.
        Useful when embedding in existing documentation with its own title.
        Default is False.
    skip_preamble : bool
        If True, skip the description and usage sections for the target command
        when filtering to a single command via ``commands_filter``.
        Useful when the user provides their own section introduction.
        Default is False.

    Returns
    -------
    str
        The generated RST documentation.
    """
    from cyclopts.help.formatters.rst import RstFormatter

    lines = []

    if command_chain is None:
        command_chain = []

    app_name, full_command, base_title = get_app_info(app, command_chain)
    # Title logic: match markdown behavior for consistency
    # - Hierarchical mode: show just command name (last part of chain)
    # - Flattened mode: show full command path
    # - Root: use base title
    if command_chain and not flatten_commands:
        # Hierarchical: show just the command name (last part of chain)
        title = command_chain[-1]
    elif command_chain:
        # Flattened: show full command path
        title = full_command
    else:
        # Root app: use base title
        title = base_title

    # Always generate RST anchor/label with improved namespacing
    # RST uses a "cyclopts-" prefix for namespacing
    anchor_parts = ["cyclopts"]
    if command_chain:
        anchor_parts.extend(command_chain)
    else:
        anchor_parts.append(app_name)
    # Use shared anchor generation logic, then add RST-specific slash replacement
    anchor_name = generate_anchor(" ".join(anchor_parts)).replace("/", "-")
    lines.append(f".. _{anchor_name}:")
    lines.append("")

    # Determine effective heading level for this command
    if no_root_title and not command_chain:
        # Skip title entirely for root when no_root_title is True
        effective_heading_level = heading_level
    elif flatten_commands and command_chain:
        # When flattening, all commands use the same heading level
        effective_heading_level = heading_level
    else:
        # Normal hierarchical: increment level for nested commands
        effective_heading_level = heading_level + len(command_chain) - 1 if command_chain else heading_level

    # Cap at max_heading_level
    effective_heading_level = min(effective_heading_level, max_heading_level)

    if not (no_root_title and not command_chain):
        if code_block_title:
            header_lines = make_rst_code_block_title(title)
        else:
            header_lines = make_rst_section_header(title, effective_heading_level)
        lines.extend(header_lines)
        lines.append("")

    help_format = app.app_stack.resolve("help_format", fallback="restructuredtext")

    # Add usage section first if appropriate (skip if skip_preamble is True)
    if not skip_preamble and should_show_usage(app):
        # Generate usage line - only if we're documenting a specific command
        if not (no_root_title and not command_chain):
            # Extract usage from app
            usage = extract_usage(app)
            usage_text = None
            if usage:
                if isinstance(usage, str):
                    usage_text = usage
                else:
                    usage_text = extract_text(usage, None, preserve_markup=False)

                # Format usage with command chain if this is a subcommand
                if command_chain:
                    # Add command chain to usage
                    parts = usage_text.split(None, 1)
                    if len(parts) > 1:
                        usage_text = f"{' '.join(command_chain)} {parts[1]}"
                    else:
                        usage_text = " ".join(command_chain)

            if usage_text:
                # Use literal block with double colon
                lines.append("::")
                lines.append("")
                # Indent usage text with 4 spaces for literal block
                for line in usage_text.split("\n"):
                    lines.append(f"    {line}")
                lines.append("")

    # Add description (skip if skip_preamble is True)
    if not skip_preamble:
        description = extract_description(app, help_format)
        if description:
            # Extract plain text from description
            # Preserve markup when help_format matches output format (RST)
            preserve = help_format in ("restructuredtext", "rst")
            desc_text = extract_text(description, None, preserve_markup=preserve)
            if desc_text:
                lines.append(desc_text.strip())
                lines.append("")

    # Generate table of contents at root level only
    if generate_toc and not command_chain and app._commands:
        _generate_toc(lines)

    # Get help panels for the current app
    # Use app_stack context - if caller set up parent context, it will be stacked
    with app.app_stack([app]):
        help_panels_with_groups = app._assemble_help_panels([], help_format)

    # Set up command filtering
    normalized_commands_filter, normalized_exclude_commands = normalize_command_filters(
        commands_filter, exclude_commands
    )
    parent_path: list[str] = []

    # Build a mapping of command names to App objects for filtering
    command_map = _build_command_map(app, include_hidden=True)

    # Create formatter for help panels
    formatter = RstFormatter(heading_level=heading_level + 1, include_hidden=include_hidden)

    # Render panels as-is without categorization
    for group, panel in help_panels_with_groups:
        # Skip hidden panels unless include_hidden is True
        if not include_hidden and group and not group.show:
            continue

        # Skip if no_root_title and we're at root
        if no_root_title and not command_chain:
            continue

        # Render command panels as grouped command lists
        if panel.format == "command":
            # Filter out built-in flags (--help, --version) from command panels
            command_entries = [e for e in panel.entries if not (e.names and is_all_builtin_flags(app, e.names))]

            if not command_entries:
                continue  # Skip empty panel

            # Apply command filtering
            filtered_entries = _filter_command_entries(
                command_entries, command_map, parent_path, normalized_commands_filter, normalized_exclude_commands
            )

            if not filtered_entries:
                continue  # Skip if nothing after filtering

            # Render group title
            if panel.title:
                lines.append(f"**{panel.title}:**")
                lines.append("")

            # Render commands as RST definition list
            for entry in filtered_entries:
                primary_name = entry.names[0] if entry.names else ""
                desc = extract_text(entry.description, None)
                lines.append(f"``{primary_name}``")
                if desc:
                    lines.append(f"    {desc}")
                lines.append("")

        # Render parameter panels as-is
        elif panel.format == "parameter":
            # Render content first to check if there's anything
            formatter.reset()
            panel_copy = panel.copy(title="")
            formatter(None, None, panel_copy)
            output = formatter.get_output().strip()

            # Only render if there's actual content
            if output:
                if panel.title:
                    lines.append(f"**{panel.title}:**")
                    lines.append("")
                lines.append(output)
                lines.append("")

    if recursive and app._commands:
        normalized_commands_filter, normalized_exclude_commands = normalize_command_filters(
            commands_filter, exclude_commands
        )
        parent_path = []

        for name, subapp in iterate_commands(app, include_hidden):
            if not should_include_command(
                name, parent_path, normalized_commands_filter, normalized_exclude_commands, subapp
            ):
                continue

            lines.append("")

            subcommand_chain = command_chain + [name] if command_chain else [app_name, name]
            if flatten_commands:
                next_heading_level = heading_level
            elif no_root_title and not command_chain:
                next_heading_level = heading_level - 1
            else:
                next_heading_level = heading_level

            sub_commands_filter, sub_exclude_commands = adjust_filters_for_subcommand(
                name, normalized_commands_filter, normalized_exclude_commands
            )

            # Determine if this subcommand should skip its preamble
            # Skip preamble when: we're at root, skip_preamble is True, and this is the single target command
            # OR this is an intermediate command on the path to a nested target
            is_single_target = (
                not command_chain
                and skip_preamble
                and commands_filter is not None
                and len(commands_filter) == 1
                and name == commands_filter[0]
            )
            is_intermediate_path = (
                not command_chain
                and skip_preamble
                and commands_filter is not None
                and len(commands_filter) == 1
                and commands_filter[0].startswith(name + ".")
            )

            # Push subapp onto app_stack - context will stack with recursive call's app_stack([app])
            with subapp.app_stack([app, subapp]):
                subdocs = generate_rst_docs(
                    subapp,
                    recursive=recursive,
                    include_hidden=include_hidden,
                    heading_level=next_heading_level,
                    max_heading_level=max_heading_level,
                    command_chain=subcommand_chain,
                    generate_toc=False,  # Only generate TOC at root level
                    flatten_commands=flatten_commands,
                    commands_filter=sub_commands_filter,
                    exclude_commands=sub_exclude_commands,
                    no_root_title=is_intermediate_path,  # Skip title for intermediate path commands
                    code_block_title=code_block_title,
                    skip_preamble=is_single_target or is_intermediate_path,  # Skip preamble for target or intermediate
                )
            lines.append(subdocs)

    # Join and normalize multiple consecutive blank lines to a single blank line
    import re

    doc = "\n".join(lines)
    doc = re.sub(r"\n{3,}", "\n\n", doc)

    return doc
