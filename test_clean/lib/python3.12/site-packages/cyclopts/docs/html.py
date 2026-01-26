"""HTML documentation generation for cyclopts apps."""

from typing import TYPE_CHECKING

from cyclopts._markup import escape_html, extract_text
from cyclopts.docs.base import (
    build_command_chain,
    extract_description,
    extract_usage,
    filter_help_entries,
    format_usage_line,
    generate_anchor,
    iterate_commands,
)

if TYPE_CHECKING:
    from cyclopts.core import App


def _generate_html_toc(
    lines: list[str],
    app: "App",
    include_hidden: bool,
    app_name: str,
    prefix: str,
    depth: int = 0,
) -> None:
    """Recursively generate HTML table of contents."""
    if not app._commands:
        return

    for name, subapp in iterate_commands(app, include_hidden):
        display_name = f"{prefix}{name}" if prefix else name
        full_path = f"{app_name}-{display_name.replace(' ', '-')}".lower()

        indent = "  " * (depth + 1)
        lines.append(f'{indent}<li><a href="#{full_path}"><code>{name}</code></a>')

        if subapp._commands:
            lines.append(f"{indent}  <ul>")
            _generate_html_toc(lines, subapp, include_hidden, app_name, f"{display_name} ", depth + 1)
            lines.append(f"{indent}  </ul>")

        lines.append(f"{indent}</li>")


# CSS styles embedded as a string - clean, modern design
DEFAULT_CSS = """
:root {
    --bg-color: #ffffff;
    --text-color: #333333;
    --border-color: #e0e0e0;
    --code-bg: #f5f5f5;
    --link-color: #0066cc;
    --header-bg: #f8f9fa;
    --required-color: #d73027;
}

* {
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    line-height: 1.6;
    color: var(--text-color);
    background: var(--bg-color);
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px;
}

h1, h2, h3, h4, h5, h6 {
    margin-top: 24px;
    margin-bottom: 16px;
    font-weight: 600;
    line-height: 1.25;
}

h1 { font-size: 2em; border-bottom: 2px solid var(--border-color); padding-bottom: 0.3em; }
h2 { font-size: 1.5em; border-bottom: 1px solid var(--border-color); padding-bottom: 0.3em; }
h3 { font-size: 1.25em; }
h4 { font-size: 1em; }

code {
    background: var(--code-bg);
    padding: 2px 6px;
    border-radius: 3px;
    font-family: 'Courier New', Consolas, monospace;
    font-size: 0.9em;
}

pre {
    background: var(--code-bg);
    padding: 16px;
    border-radius: 6px;
    overflow-x: auto;
    font-family: 'Courier New', Consolas, monospace;
    font-size: 0.9em;
}

pre code {
    background: none;
    padding: 0;
}

.usage-block {
    margin: 16px 0;
}

.usage {
    background: #f8f9fa;
    border-left: 4px solid #0066cc;
}

.description, .app-description, .command-description {
    margin: 16px 0;
    color: var(--text-color);
}

.panel-description {
    margin: 12px 0;
    color: #666;
}

.help-panel {
    margin: 24px 0;
}

/* List styles for commands and parameters */
.commands-list, .parameters-list {
    list-style: none;
    padding-left: 0;
    margin: 16px 0;
}

.commands-list li, .parameters-list li {
    padding: 8px 0;
    border-bottom: 1px solid var(--border-color);
}

.commands-list li:last-child, .parameters-list li:last-child {
    border-bottom: none;
}

.commands-list code, .parameters-list code {
    font-weight: 600;
}

/* Metadata styling */
.parameter-metadata {
    display: inline-flex;
    gap: 8px;
    margin-left: 8px;
    flex-wrap: wrap;
    align-items: center;
}

.metadata-item {
    display: inline-block;
    padding: 2px 8px;
    font-size: 0.85em;
    border-radius: 4px;
    background: var(--code-bg);
    border: 1px solid var(--border-color);
}

.metadata-required {
    background: #fee;
    border-color: #fcc;
    color: #c00;
    font-weight: 600;
}

.metadata-default {
    background: #f0f8ff;
    border-color: #d0e8ff;
    color: #0066cc;
}

.metadata-env {
    background: #f0fff0;
    border-color: #d0ffd0;
    color: #080;
}

.metadata-choices {
    background: #fffaf0;
    border-color: #ffd0a0;
    color: #840;
}

.metadata-label {
    font-weight: 600;
    opacity: 0.8;
    text-transform: uppercase;
    font-size: 0.9em;
}

/* Table of Contents */
.table-of-contents {
    background: var(--header-bg);
    border-radius: 6px;
    padding: 16px;
    margin: 24px 0;
}

.table-of-contents h2 {
    margin-top: 0;
    border-bottom: none;
    padding-bottom: 0;
}

.table-of-contents ul {
    margin: 8px 0;
    padding-left: 24px;
}

.table-of-contents li {
    margin: 4px 0;
}

.table-of-contents a {
    color: var(--link-color);
    text-decoration: none;
}

.table-of-contents a:hover {
    text-decoration: underline;
}

/* General link styles */
a {
    color: var(--link-color);
    text-decoration: none;
}

a:hover {
    text-decoration: underline;
}

.commands-list a code {
    color: var(--link-color);
}

/* Back to top link */
.back-to-top {
    display: inline-block;
    margin-top: 8px;
    font-size: 0.9em;
    opacity: 0.7;
}

.back-to-top:hover {
    opacity: 1;
}

/* Responsive design */
@media (max-width: 768px) {
    body {
        padding: 10px;
    }

    .commands-list, .parameters-list {
        font-size: 0.9em;
    }
}

/* Dark mode support */
@media (prefers-color-scheme: dark) {
    :root {
        --bg-color: #1e1e1e;
        --text-color: #e0e0e0;
        --border-color: #444;
        --code-bg: #2d2d2d;
        --link-color: #66b3ff;
        --header-bg: #2d2d2d;
    }

    .usage {
        background: #2d2d2d;
        border-left-color: #66b3ff;
    }

    .table-of-contents {
        background: #2d2d2d;
    }

    .metadata-required {
        background: #4a2020;
        border-color: #6a3030;
        color: #ff9999;
    }

    .metadata-default {
        background: #20304a;
        border-color: #304060;
        color: #99ccff;
    }

    .metadata-env {
        background: #204a20;
        border-color: #306030;
        color: #99ff99;
    }

    .metadata-choices {
        background: #4a3020;
        border-color: #604030;
        color: #ffcc99;
    }
}

/* Command sections */
.command-section {
    margin-top: 32px;
    padding-top: 16px;
    border-top: 2px solid var(--border-color);
}

.command-section:first-child {
    border-top: none;
}
"""


def generate_html_docs(
    app: "App",
    recursive: bool = True,
    include_hidden: bool = False,
    heading_level: int = 1,
    max_heading_level: int = 6,
    standalone: bool = True,
    custom_css: str | None = None,
    command_chain: list[str] | None = None,
    generate_toc: bool = True,
    flatten_commands: bool = False,
) -> str:
    """Generate HTML documentation for a CLI application.

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
        Default is 1.
    max_heading_level : int
        Maximum heading level to use. Headings deeper than this will be capped
        at this level. HTML supports levels 1-6.
        Default is 6.
    standalone : bool
        If True, generate a complete HTML document with <html>, <head>, etc.
        If False, generate only the body content. Default is True.
    custom_css : str
        Custom CSS to use instead of the default styles.
    command_chain : list[str]
        Internal parameter to track command hierarchy.
        Default is None.
    generate_toc : bool
        If True, generate a table of contents for multi-command apps.
        Default is True.
    flatten_commands : bool
        If True, generate all commands at the same heading level instead of nested.
        Default is False.

    Returns
    -------
    str
        The generated HTML documentation.
    """
    from cyclopts.help.formatters.html import HtmlFormatter

    # Initialize command chain if not provided
    if command_chain is None:
        command_chain = []

    # Build the main documentation
    lines = []

    # Only add the outer div for standalone documents or root level
    if standalone or not command_chain:
        lines.append('<div class="cli-documentation">')

    # Determine the app name and full command path
    if not command_chain:
        # Root level - use app name or derive from sys.argv
        app_name = app.name[0]
        full_command = app_name
        title = app_name
        # Add title for all levels
        effective_level = min(heading_level, max_heading_level)
        lines.append(f'<h{effective_level} class="app-title">{title}</h{effective_level}>')
    else:
        # Nested command - build full path
        app_name = command_chain[0] if command_chain else app.name[0]
        full_command = " ".join(command_chain)
        # Create anchor-friendly ID using shared logic
        anchor_id = generate_anchor(full_command)
        effective_level = min(heading_level, max_heading_level)
        lines.append('<section class="command-section">')
        lines.append(
            f'<h{effective_level} id="{anchor_id}" class="command-title"><code>{escape_html(full_command)}</code></h{effective_level}>'
        )

    # Add application description
    help_format = app.app_stack.resolve("help_format", fallback="restructuredtext")
    description = extract_description(app, help_format)
    if description:
        desc_text = extract_text(description, None)
        if desc_text:
            lines.append(f'<div class="app-description">{escape_html(desc_text)}</div>')

    # Generate table of contents if this is the root level and has commands
    if generate_toc and not command_chain and app._commands:
        lines.append('<div class="table-of-contents">')
        lines.append("<h2>Table of Contents</h2>")
        lines.append("<ul>")
        _generate_html_toc(lines, app, include_hidden, app_name, "", 0)
        lines.append("</ul>")
        lines.append("</div>")

    # Add usage section if not suppressed
    usage = extract_usage(app)
    if usage:
        usage_level = min(heading_level + 1, max_heading_level)
        lines.append(f"<h{usage_level}>Usage</h{usage_level}>")
        lines.append('<div class="usage-block">')
        if isinstance(usage, str):
            usage_text = usage
        else:
            usage_text = extract_text(usage, None)
        usage_text = format_usage_line(usage_text, command_chain, prefix="$")
        lines.append(f'<pre class="usage">{escape_html(usage_text)}</pre>')
        lines.append("</div>")

    # Get help panels for the current app
    # Use app_stack context - if caller set up parent context, it will be stacked
    with app.app_stack([app]):
        help_panels_with_groups = app._assemble_help_panels([], help_format)

    # Render panels
    formatter = HtmlFormatter(
        heading_level=heading_level + 1,
        include_hidden=include_hidden,
        app_name=app_name,
        command_chain=command_chain,
    )
    formatter.reset()
    for group, panel in help_panels_with_groups:
        if not include_hidden and group and not group.show:
            continue
        # Filter out entries based on include_hidden
        if not include_hidden:
            panel.entries = filter_help_entries(app, panel, include_hidden)
        if panel.entries:  # Only render non-empty panels
            formatter(None, None, panel)

    panel_docs = formatter.get_output().strip()
    if panel_docs:
        lines.append(panel_docs)

    # Handle recursive documentation for subcommands
    if app._commands:
        # Iterate through registered commands
        for name, subapp in iterate_commands(app, include_hidden):
            # Build the command chain for this subcommand
            sub_command_chain = build_command_chain(command_chain, name, app_name)

            # Determine heading level for subcommand
            if flatten_commands:
                sub_heading_level = heading_level
            else:
                sub_heading_level = heading_level + 1

            # Generate subcommand documentation
            lines.append('<section class="command-section">')
            # Create anchor-friendly ID
            anchor_id = (
                f"{app_name}-{'-'.join(sub_command_chain[1:])}".lower()
                if len(sub_command_chain) > 1
                else f"{app_name}-{name}".lower()
            )
            effective_sub_level = min(sub_heading_level, max_heading_level)
            lines.append(
                f'<h{effective_sub_level} id="{anchor_id}" class="command-title"><code>{escape_html(" ".join(sub_command_chain))}</code></h{effective_sub_level}>'
            )

            # Get subapp help
            # Include parent app in the stack so default_parameter is properly inherited
            with subapp.app_stack([app, subapp]):
                sub_help_format = subapp.app_stack.resolve("help_format", fallback=help_format)
                sub_description = extract_description(subapp, sub_help_format)
                if sub_description:
                    sub_desc_text = extract_text(sub_description, None)
                    if sub_desc_text:
                        lines.append(f'<div class="command-description">{escape_html(sub_desc_text)}</div>')

                # Generate usage for subcommand
                sub_usage = extract_usage(subapp)
                if sub_usage:
                    if flatten_commands:
                        usage_heading_level = heading_level + 1
                    else:
                        usage_heading_level = heading_level + 2
                    usage_heading_level = min(usage_heading_level, max_heading_level)
                    lines.append(f"<h{usage_heading_level}>Usage</h{usage_heading_level}>")
                    lines.append('<div class="usage-block">')
                    if isinstance(sub_usage, str):
                        sub_usage_text = sub_usage
                    else:
                        sub_usage_text = extract_text(sub_usage, None)
                    sub_usage_text = format_usage_line(sub_usage_text, sub_command_chain, prefix="$")
                    lines.append(f'<pre class="usage">{escape_html(sub_usage_text)}</pre>')
                    lines.append("</div>")

                # Only show subcommand panels if we're in recursive mode
                if recursive:
                    # Get help panels for subcommand
                    sub_panels = subapp._assemble_help_panels([], sub_help_format)

                    # Render subcommand panels
                    if flatten_commands:
                        panel_heading_level = heading_level + 1
                    else:
                        panel_heading_level = heading_level + 2
                    panel_heading_level = min(panel_heading_level, max_heading_level)
                    sub_formatter = HtmlFormatter(
                        heading_level=panel_heading_level,
                        include_hidden=include_hidden,
                        app_name=app_name,
                        command_chain=sub_command_chain,
                    )
                    for sub_group, sub_panel in sub_panels:
                        if not include_hidden and sub_group and not sub_group.show:
                            continue
                        if not include_hidden:
                            sub_panel.entries = filter_help_entries(subapp, sub_panel, include_hidden)
                        if sub_panel.entries:
                            sub_formatter(None, None, sub_panel)

                    sub_panel_docs = sub_formatter.get_output().strip()
                    if sub_panel_docs:
                        lines.append(sub_panel_docs)

                # Recursively handle nested subcommands
                if recursive and subapp._commands:
                    for nested_name, nested_app in iterate_commands(subapp, include_hidden):
                        # Build nested command chain
                        nested_chain = build_command_chain(sub_command_chain, nested_name, app_name)
                        # Determine heading level for nested commands
                        if flatten_commands:
                            nested_heading_level = heading_level
                        else:
                            nested_heading_level = heading_level + 2
                        # Set up context for nested_app, then recurse
                        # The recursive call's app_stack([app]) will stack on top of this
                        with nested_app.app_stack([subapp, nested_app]):
                            nested_docs = generate_html_docs(
                                nested_app,
                                recursive=recursive,
                                include_hidden=include_hidden,
                                heading_level=nested_heading_level,
                                max_heading_level=max_heading_level,
                                standalone=False,  # Not standalone for nested
                                custom_css=None,
                                command_chain=nested_chain,  # Pass the command chain
                                generate_toc=False,  # No TOC for nested commands
                                flatten_commands=flatten_commands,
                            )
                        lines.append(nested_docs)

            # Add back to top link if we're in a nested section
            if command_chain:
                lines.append('<a href="#top" class="back-to-top">↑ Back to top</a>')
            lines.append("</section>")

    # Close section if nested command
    if command_chain:
        lines.append("</section>")

    # Only close cli-documentation div for standalone or root
    if standalone or not command_chain:
        lines.append("</div>")  # Close cli-documentation div

    # Join all lines into body content
    body_content = "\n".join(lines)

    # If standalone, wrap in complete HTML document
    if standalone:
        css = custom_css if custom_css else DEFAULT_CSS
        doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape_html(app_name)} - CLI Documentation</title>
    <style>
{css}
    </style>
</head>
<body id="top">
{body_content}
</body>
</html>"""
        return doc
    else:
        return body_content
