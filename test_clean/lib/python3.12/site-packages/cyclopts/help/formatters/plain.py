"""Plain text help formatter for improved accessibility."""

import io
import textwrap
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions

    from cyclopts.help import HelpEntry, HelpPanel


def _to_plain_text(obj: Any, console: "Console") -> str:
    """Extract plain text from Rich renderables.

    Parameters
    ----------
    obj : Any
        Object to convert to plain text.
    console : ~rich.console.Console
        Console for rendering Rich objects.

    Returns
    -------
    str
        Plain text representation.
    """
    if obj is None:
        return ""

    # Rich Text objects have a .plain property for plain text
    if hasattr(obj, "plain"):
        return obj.plain.rstrip()

    # For any Rich renderable, render without styles
    if hasattr(obj, "__rich_console__"):
        # Create a plain console that preserves layout but removes styling
        from rich.console import Console

        plain_console = Console(
            file=io.StringIO(),
            width=console.width,
            height=console.height,
            tab_size=console.tab_size,
            legacy_windows=console.legacy_windows,
            safe_box=console.safe_box,
            # Disable all styling
            force_terminal=False,
            no_color=True,
            highlight=False,
            markup=False,
            emoji=False,
        )
        with plain_console.capture() as capture:
            plain_console.print(obj, end="")
        return capture.get().rstrip()

    # Fallback for non-Rich objects
    return str(obj).rstrip()


class PlainFormatter:
    """Plain text formatter for improved accessibility.

    Parameters
    ----------
    indent_width : int
        Number of spaces to indent entries (default: 2).
    max_width : Optional[int]
        Maximum line width for wrapping text.
    """

    def __init__(
        self,
        indent_width: int = 2,
        max_width: int | None = None,
    ):
        self.indent_width = indent_width
        self.max_width = max_width
        self.indent = " " * indent_width

    def _print_plain(self, console: "Console", text: str) -> None:
        """Print text without any highlighting or markup."""
        console.print(text, highlight=False, markup=False)

    def __call__(
        self,
        console: "Console",
        options: "ConsoleOptions",
        panel: "HelpPanel",
    ) -> None:
        """Format and render a single help panel as plain text.

        Parameters
        ----------
        console : ~rich.console.Console
            Console to render to.
        options : ~rich.console.ConsoleOptions
            Console rendering options.
        panel : HelpPanel
            Help panel to render.
        """
        if not panel.entries:
            return

        # Print panel title with appropriate formatting
        if panel.title:
            self._print_plain(console, f"{panel.title}:")

        # Print each entry in the panel
        for entry in panel.entries:
            desc = _to_plain_text(entry.description, console)

            # Format the entry line
            if entry.all_options:
                if panel.format == "parameter":
                    self._format_parameter_entry(entry.all_options, desc, console, entry)
                else:
                    # Command formatter needs separate longs/shorts for its specific layout
                    self._format_command_entry(entry.positive_names, entry.positive_shorts, desc, console)

        # Add trailing newline for visual separation between panels
        console.print()

    def render_usage(
        self,
        console: "Console",
        options: "ConsoleOptions",
        usage: Any,
    ) -> None:
        """Render the usage line.

        Parameters
        ----------
        console : ~rich.console.Console
            Console to render to.
        options : ~rich.console.ConsoleOptions
            Console rendering options.
        usage : Any
            The usage line (Text or str).
        """
        if usage:
            usage_text = _to_plain_text(usage, console)
            if usage_text:
                # Add "Usage:" prefix if not already present (for custom usage strings)
                if not usage_text.strip().startswith("Usage:"):
                    self._print_plain(console, f"Usage: {usage_text}")
                else:
                    self._print_plain(console, usage_text)
                console.print()

    def render_description(
        self,
        console: "Console",
        options: "ConsoleOptions",
        description: Any,
    ) -> None:
        """Render the description.

        Parameters
        ----------
        console : ~rich.console.Console
            Console to render to.
        options : ~rich.console.ConsoleOptions
            Console rendering options.
        description : Any
            The description (can be various Rich renderables).
        """
        if description:
            desc_text = _to_plain_text(description, console)
            if desc_text:
                self._print_plain(console, desc_text)
                console.print()

    def _format_parameter_entry(
        self,
        options: tuple[str, ...],
        desc: str,
        console: "Console",
        entry: "HelpEntry",
    ) -> None:
        """Format and print a parameter entry.

        Parameters
        ----------
        options : tuple[str, ...]
            All parameter options in display order.
        desc : str
            Parameter description.
        console : ~rich.console.Console
            Console to print to.
        entry : HelpEntry
            The full help entry with metadata fields.
        """
        if not options:
            return

        # Build the description with metadata
        desc_parts = []
        if desc:
            desc_parts.append(desc)

        # Add metadata fields from entry
        if entry.choices:
            choices_str = ", ".join(entry.choices)
            desc_parts.append(f"[choices: {choices_str}]")

        if entry.env_var:
            env_vars_str = ", ".join(entry.env_var)
            desc_parts.append(f"[env var: {env_vars_str}]")

        if entry.default is not None:
            desc_parts.append(f"[default: {entry.default}]")

        if entry.required:
            desc_parts.append("[required]")

        full_desc = " ".join(desc_parts)

        # Format: "option1, option2, ...: description"
        options_str = ", ".join(options)
        if full_desc:
            text = f"{options_str}: {full_desc}"
        else:
            text = options_str
        self._print_plain(console, textwrap.indent(text, self.indent))

    def _format_command_entry(
        self,
        names: tuple[str, ...],
        shorts: tuple[str, ...],
        desc: str,
        console: "Console",
    ) -> None:
        """Format and print a command entry.

        Parameters
        ----------
        names : tuple[str, ...]
            Command long names.
        shorts : tuple[str, ...]
            Short forms of the command.
        desc : str
            Command description.
        console : ~rich.console.Console
            Console to print to.
        """
        # For commands, we typically want to show long names on separate lines
        # and shorts together
        if names:
            for i, name in enumerate(names):
                if i == 0:
                    # First name gets the shorts and description
                    parts = [name]
                    if shorts:
                        parts.append(", " + " ".join(shorts))
                    entry_name = "".join(parts)
                    if desc:
                        text = f"{entry_name}: {desc}"
                    else:
                        text = entry_name
                    self._print_plain(console, textwrap.indent(text, self.indent))
                else:
                    # Additional names on separate lines
                    self._print_plain(console, textwrap.indent(name, self.indent))
        elif shorts:
            # Only short names
            shorts_str = " ".join(shorts)
            if desc:
                text = f"{shorts_str}: {desc}"
            else:
                text = shorts_str
            self._print_plain(console, textwrap.indent(text, self.indent))
