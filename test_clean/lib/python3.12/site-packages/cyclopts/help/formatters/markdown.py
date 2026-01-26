"""Markdown documentation formatter."""

import io
from typing import TYPE_CHECKING, Any, Optional

from cyclopts._markup import extract_text

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions

    from cyclopts.help import HelpEntry, HelpPanel


class MarkdownFormatter:
    """Markdown documentation formatter.

    Parameters
    ----------
    heading_level : int
        Starting heading level for panels (default: 2).
        E.g., 2 produces "## Commands", 3 produces "### Commands".
    table_style : str
        Style for parameter/command tables: "table" or "list" (default: "table").
    include_hidden : bool
        Include hidden commands/parameters in documentation (default: False).
    """

    def __init__(
        self,
        heading_level: int = 2,
        table_style: str = "table",
        include_hidden: bool = False,
    ):
        self.heading_level = heading_level
        self.table_style = table_style
        self.include_hidden = include_hidden
        self._output = io.StringIO()

    def reset(self) -> None:
        """Reset the internal output buffer."""
        self._output = io.StringIO()

    def get_output(self) -> str:
        """Get the accumulated markdown output.

        Returns
        -------
        str
            The markdown documentation string.
        """
        return self._output.getvalue()

    def __call__(
        self,
        console: Optional["Console"],
        options: Optional["ConsoleOptions"],
        panel: "HelpPanel",
    ) -> None:
        """Format and render a help panel as markdown.

        Parameters
        ----------
        console : Optional[Console]
            Console for rendering (used for extracting plain text).
        options : Optional[ConsoleOptions]
            Console rendering options (unused for markdown).
        panel : HelpPanel
            Help panel to render.
        """
        if not panel.entries:
            return

        # Write panel title as heading
        if panel.title:
            title_text = extract_text(panel.title, console)
            heading = "#" * self.heading_level
            self._output.write(f"{heading} {title_text}\n\n")

        # Write panel description if present
        if panel.description:
            desc_text = extract_text(panel.description, console)
            if desc_text:
                self._output.write(f"{desc_text}\n\n")

        # Format entries based on panel type
        if panel.format == "command":
            self._format_command_panel(panel.entries, console)
        elif panel.format == "parameter":
            self._format_parameter_panel(panel.entries, console)

        self._output.write("\n")

    def _format_command_panel(self, entries: list["HelpEntry"], console: Optional["Console"]) -> None:
        """Format command entries as markdown.

        Parameters
        ----------
        entries : list[HelpEntry]
            Command entries to format.
        console : Optional[Console]
            Console for text extraction.
        """
        # Always use list style for Typer-like output
        for entry in entries:
            if names := entry.all_options:
                # Use first name as primary, show aliases in parentheses
                primary_name, aliases = names[0], names[1:]
                if aliases:
                    name_display = f"{primary_name} ({', '.join(aliases)})"
                else:
                    name_display = primary_name
                desc = extract_text(entry.description, console, preserve_markup=True)

                if desc:
                    self._output.write(f"* `{name_display}`: {desc}")
                else:
                    self._output.write(f"* `{name_display}`:")

                self._output.write("\n")

    def _format_parameter_panel(self, entries: list["HelpEntry"], console: Optional["Console"]) -> None:
        """Format parameter entries as markdown in Typer style.

        Parameters
        ----------
        entries : list[HelpEntry]
            Parameter entries to format.
        console : Optional[Console]
            Console for text extraction.
        """
        # Always use list style for Typer-like output
        for entry in entries:
            if names := entry.all_options:
                # Separate positional names from option names
                positional_names = [n for n in names if not n.startswith("-")]
                short_opts = [n for n in names if n.startswith("-") and not n.startswith("--")]
                long_opts = [n for n in names if n.startswith("--")]

                # Determine if this is a positional argument (required, no default)
                is_positional = entry.required and entry.default is None

                if is_positional and positional_names:
                    # Show uppercase positional name first, then any option names
                    parts = [positional_names[0].upper()]
                    parts.extend(long_opts)
                    name_str = ", ".join(parts)
                else:
                    # For options, show long opts first, then short opts
                    if short_opts:
                        name_str = ", ".join(long_opts + short_opts)
                    elif positional_names:
                        # Has positional name but not required - show all
                        parts = [positional_names[0].upper()]
                        parts.extend(long_opts)
                        name_str = ", ".join(parts)
                    else:
                        name_str = ", ".join(long_opts)

                # Start the entry (no type display)
                self._output.write(f"* `{name_str}`: ")

                # Add description with proper indentation for nested content
                desc = extract_text(entry.description, console, preserve_markup=True)
                if desc:
                    import re

                    # Split into lines and indent continuation lines to nest under the bullet
                    lines = desc.split("\n")
                    self._output.write(lines[0])  # First line on same line as bullet

                    # Track what type of list context we're in for proper nesting
                    in_numbered_list = False

                    for line in lines[1:]:
                        if not line.strip():  # Blank line
                            self._output.write("\n")
                        else:
                            stripped = line.lstrip()
                            existing_indent = len(line) - len(stripped)

                            # Check if this line starts a numbered list
                            if re.match(r"^\d+\.", stripped):
                                in_numbered_list = True
                                # Numbered lists need 4 spaces base indentation minimum
                                indent = max(existing_indent + 4, 4)
                            # Check if this is a bullet under a numbered list
                            elif re.match(r"^\-", stripped) and in_numbered_list:
                                # Bullets nested under numbered items need extra indentation
                                # At least 10 spaces (4 base + 3 for "N. " + 3 more for nesting)
                                indent = max(existing_indent + 4, 10)
                            elif re.match(r"^\-", stripped):
                                # Top-level bullets just need base indentation
                                indent = max(existing_indent + 4, 4)
                            else:
                                # Regular content preserves relative indentation
                                indent = existing_indent + 4

                            self._output.write("\n" + " " * indent + stripped)

                # Add metadata in brackets
                # Handle required separately for bold formatting
                is_required = False
                if entry.required and not is_positional:
                    # Only show required for options, arguments show it differently
                    is_required = True
                elif is_positional and entry.required:
                    # For positional args, add [required] at the end
                    is_required = True

                metadata = []
                if entry.choices:
                    choices_str = ", ".join(entry.choices)
                    metadata.append(f"choices: {choices_str}")

                if entry.env_var:
                    env_str = ", ".join(entry.env_var)
                    metadata.append(f"env: {env_str}")

                if entry.default is not None:
                    default_str = extract_text(entry.default, console)
                    metadata.append(f"default: {default_str}")

                # Write required in bold and separate brackets first
                if is_required:
                    self._output.write("  **[required]**")

                # Write each metadata item in its own brackets with italics
                for item in metadata:
                    self._output.write(f"  *[{item}]*")

                self._output.write("\n")

    def render_usage(
        self,
        console: Optional["Console"],
        options: Optional["ConsoleOptions"],
        usage: Any,
    ) -> None:
        """Render the usage line as markdown.

        Parameters
        ----------
        console : Optional[Console]
            Console for text extraction.
        options : Optional[ConsoleOptions]
            Console rendering options (unused).
        usage : Any
            The usage line content.
        """
        if usage:
            usage_text = extract_text(usage, console)
            if usage_text:
                # Add "Usage:" prefix if not already present (for custom usage strings)
                if not usage_text.strip().startswith("Usage:"):
                    self._output.write(f"```\nUsage: {usage_text}\n```\n\n")
                else:
                    self._output.write(f"```\n{usage_text}\n```\n\n")

    def render_description(
        self,
        console: Optional["Console"],
        options: Optional["ConsoleOptions"],
        description: Any,
    ) -> None:
        """Render the description as markdown.

        Parameters
        ----------
        console : Optional[Console]
            Console for text extraction.
        options : Optional[ConsoleOptions]
            Console rendering options (unused).
        description : Any
            The description content.
        """
        if description:
            desc_text = extract_text(description, console)
            if desc_text:
                self._output.write(f"{desc_text}\n\n")
