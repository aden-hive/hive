"""reStructuredText documentation formatter."""

import io
from typing import TYPE_CHECKING, Any, Optional

from cyclopts._markup import extract_text
from cyclopts.docs.rst import make_rst_section_header

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions

    from cyclopts.help import HelpEntry, HelpPanel


class RstFormatter:
    """reStructuredText documentation formatter.

    Parameters
    ----------
    heading_level : int
        Starting heading level for panels (default: 2).
    include_hidden : bool
        Include hidden commands/parameters in documentation (default: False).
    """

    def __init__(
        self,
        heading_level: int = 2,
        include_hidden: bool = False,
    ):
        self.heading_level = heading_level
        self.include_hidden = include_hidden
        self._output = io.StringIO()

    def reset(self) -> None:
        """Reset the internal output buffer."""
        self._output = io.StringIO()

    def get_output(self) -> str:
        """Get the accumulated RST output.

        Returns
        -------
        str
            The RST documentation string.
        """
        return self._output.getvalue()

    def __call__(
        self,
        console: Optional["Console"],
        options: Optional["ConsoleOptions"],
        panel: "HelpPanel",
    ) -> None:
        """Format and render a help panel as RST.

        Parameters
        ----------
        console : Optional[Console]
            Console for rendering (used for extracting plain text).
        options : Optional[ConsoleOptions]
            Console rendering options (unused for RST).
        panel : HelpPanel
            Help panel to render.
        """
        if not panel.entries:
            return

        # Write panel title as heading
        if panel.title:
            title_text = extract_text(panel.title, console)
            header = "\n".join(make_rst_section_header(title_text, self.heading_level))
            self._output.write(f"{header}\n\n")

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
        """Format command entries as RST.

        Parameters
        ----------
        entries : list[HelpEntry]
            Command entries to format.
        console : Optional[Console]
            Console for text extraction.
        """
        for entry in entries:
            if names := entry.all_options:
                # Use first name as primary, show aliases in parentheses
                primary_name, aliases = names[0], names[1:]
                if aliases:
                    name_display = f"{primary_name} ({', '.join(aliases)})"
                else:
                    name_display = primary_name

                # Use definition list format
                self._output.write(f"``{name_display}``\n")

                # Check if the description has RST markup to preserve
                preserve_rst_markup = (
                    hasattr(entry.description, "primary_renderable")
                    and hasattr(entry.description.primary_renderable, "__class__")
                    and "RestructuredText" in entry.description.primary_renderable.__class__.__name__
                )
                desc = extract_text(entry.description, console, preserve_markup=preserve_rst_markup)
                if desc:
                    # Join multi-line descriptions into a single paragraph for proper RST formatting
                    # This prevents each line from being interpreted as a separate blockquote
                    desc_text = " ".join(line.strip() for line in desc.split("\n") if line.strip())
                    self._output.write(f"    {desc_text}\n\n")

    def _format_parameter_panel(self, entries: list["HelpEntry"], console: Optional["Console"]) -> None:
        """Format parameter entries as RST.

        Parameters
        ----------
        entries : list[HelpEntry]
            Parameter entries to format.
        console : Optional[Console]
            Console for text extraction.
        """
        for entry in entries:
            if names := entry.all_options:
                # Determine if we should display as positional based on requirement and default
                is_positional = entry.required and entry.default is None and not any(n.startswith("-") for n in names)

                if is_positional:
                    # For positional arguments, show in uppercase
                    positional_names = [n for n in names if not n.startswith("-")]
                    name_str = positional_names[0].upper() if positional_names else names[0].upper()
                else:
                    # For options, format with all forms
                    name_str = ", ".join(names)

                # Use definition list format
                self._output.write(f"``{name_str}``\n")

                # Build description with metadata
                desc_parts = []

                # Add main description
                # Check if the description has RST markup to preserve
                preserve_rst_markup = (
                    hasattr(entry.description, "primary_renderable")
                    and hasattr(entry.description.primary_renderable, "__class__")
                    and "RestructuredText" in entry.description.primary_renderable.__class__.__name__
                )
                desc = extract_text(entry.description, console, preserve_markup=preserve_rst_markup)
                if desc:
                    desc_parts.append(desc)

                # Add metadata
                metadata = []

                if is_positional and entry.required:
                    metadata.append("**Required**")
                elif entry.required and not is_positional:
                    metadata.append("**Required**")

                if entry.choices:
                    choices_str = ", ".join(f"``{c}``" for c in entry.choices)
                    metadata.append(f"Choices: {choices_str}")

                if entry.default is not None:
                    default_str = extract_text(entry.default, console, preserve_markup=False)
                    metadata.append(f"Default: ``{default_str}``")

                if entry.env_var:
                    env_str = ", ".join(f"``{e}``" for e in entry.env_var)
                    metadata.append(f"Environment variable: {env_str}")

                # Combine description and metadata - handle multi-line descriptions
                if desc_parts:
                    # Join multi-line descriptions into a single paragraph for proper RST formatting
                    # This prevents each line from being interpreted as a separate blockquote
                    desc_text = " ".join(line.strip() for line in desc_parts[0].split("\n") if line.strip())
                    self._output.write(f"    {desc_text}")

                    if metadata:
                        self._output.write(f" [{', '.join(metadata)}]")
                    self._output.write("\n\n")
                elif metadata:
                    self._output.write(f"    {', '.join(metadata)}\n\n")

    def render_usage(
        self,
        console: Optional["Console"],
        options: Optional["ConsoleOptions"],
        usage: Any,
    ) -> None:
        """Render the usage line as RST.

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
                # Use literal block for usage
                self._output.write("::\n\n")
                # Add "Usage:" prefix if not already present (for custom usage strings)
                if not usage_text.strip().startswith("Usage:"):
                    self._output.write(f"    Usage: {usage_text}\n")
                else:
                    self._output.write(f"    {usage_text}\n")
                self._output.write("\n")

    def render_description(
        self,
        console: Optional["Console"],
        options: Optional["ConsoleOptions"],
        description: Any,
    ) -> None:
        """Render the description as RST.

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
