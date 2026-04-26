"""HTML documentation formatter."""

import io
from typing import TYPE_CHECKING, Any, Optional

from cyclopts._markup import escape_html, extract_text

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions

    from cyclopts.help import HelpEntry, HelpPanel


class HtmlFormatter:
    """HTML documentation formatter.

    Parameters
    ----------
    heading_level : int
        Starting heading level for panels (default: 2).
        E.g., 2 produces "<h2>Commands</h2>", 3 produces "<h3>Commands</h3>".
    include_hidden : bool
        Include hidden commands/parameters in documentation (default: False).
    app_name : str
        The root application name for generating anchor IDs.
    command_chain : list[str]
        The current command chain for generating anchor IDs.
    """

    def __init__(
        self,
        heading_level: int = 2,
        include_hidden: bool = False,
        app_name: str | None = None,
        command_chain: list[str] | None = None,
    ):
        self.heading_level = heading_level
        self.include_hidden = include_hidden
        self.app_name = app_name
        self.command_chain = command_chain or []
        self._output = io.StringIO()

    def reset(self) -> None:
        """Reset the internal output buffer."""
        self._output = io.StringIO()

    def get_output(self) -> str:
        """Get the accumulated HTML output.

        Returns
        -------
        str
            The HTML documentation string.
        """
        return self._output.getvalue()

    def __call__(
        self,
        console: Optional["Console"],
        options: Optional["ConsoleOptions"],
        panel: "HelpPanel",
    ) -> None:
        """Format and render a help panel as HTML.

        Parameters
        ----------
        console : Optional[Console]
            Console for rendering (used for extracting plain text).
        options : Optional[ConsoleOptions]
            Console rendering options (unused for HTML).
        panel : HelpPanel
            Help panel to render.
        """
        if not panel.entries:
            return

        # Write panel as a section
        self._output.write('<section class="help-panel">\n')

        # Write panel title as heading
        if panel.title:
            title_text = escape_html(extract_text(panel.title, console))
            self._output.write(f'<h{self.heading_level} class="panel-title">{title_text}</h{self.heading_level}>\n')

        # Write panel description if present
        if panel.description:
            desc_text = escape_html(extract_text(panel.description, console))
            if desc_text:
                self._output.write(f'<div class="panel-description">{desc_text}</div>\n')

        # Format entries based on panel type
        if panel.format == "command":
            self._format_command_panel(panel.entries, console)
        elif panel.format == "parameter":
            self._format_parameter_panel(panel.entries, console)

        self._output.write("</section>\n")

    def _format_command_panel(self, entries: list["HelpEntry"], console: Optional["Console"]) -> None:
        """Format command entries as HTML.

        Parameters
        ----------
        entries : list[HelpEntry]
            Command entries to format.
        console : Optional[Console]
            Console for text extraction.
        """
        if not entries:
            return

        # Use list format instead of table
        self._output.write('<ul class="commands-list">\n')

        for entry in entries:
            names = entry.all_options
            if not names:
                name_html = ""
            elif self.app_name:
                # Generate anchor link
                primary_name, aliases = names[0], names[1:]
                if self.command_chain:
                    full_chain = self.command_chain + [primary_name]
                    anchor_id = f"{self.app_name}-{'-'.join(full_chain[1:])}".lower()
                else:
                    anchor_id = f"{self.app_name}-{primary_name}".lower()
                name_html = f'<a href="#{anchor_id}"><code>{escape_html(primary_name)}</code></a>'
                if aliases:
                    aliases_str = ", ".join(escape_html(n) for n in aliases)
                    name_html = f"{name_html} ({aliases_str})"
            else:
                # Non-linked format with aliases in parentheses
                primary_name, aliases = names[0], names[1:]
                name_html = f"<code>{escape_html(primary_name)}</code>"
                if aliases:
                    aliases_str = ", ".join(escape_html(n) for n in aliases)
                    name_html = f"{name_html} ({aliases_str})"

            desc_html = escape_html(extract_text(entry.description, console))

            self._output.write(f"<li><strong>{name_html}</strong>")
            if desc_html:
                self._output.write(f": {desc_html}")
            self._output.write("</li>\n")

        self._output.write("</ul>\n")

    def _format_parameter_panel(self, entries: list["HelpEntry"], console: Optional["Console"]) -> None:
        """Format parameter entries as HTML.

        Parameters
        ----------
        entries : list[HelpEntry]
            Parameter entries to format.
        console : Optional[Console]
            Console for text extraction.
        """
        if not entries:
            return

        # Use list format instead of table
        self._output.write('<ul class="parameters-list">\n')

        for entry in entries:
            # Format name with code tags
            if names := entry.all_options:
                name_html = ", ".join(f"<code>{escape_html(n)}</code>" for n in names)
            else:
                name_html = ""

            # Start list item (no type display)
            self._output.write(f"<li><strong>{name_html}</strong>")

            # Add description
            desc = extract_text(entry.description, console)
            if desc:
                self._output.write(f": {escape_html(desc)}")

            # Add metadata as styled badges
            metadata_items = []

            # Add required marker
            if entry.required:
                metadata_items.append('<span class="metadata-item metadata-required">Required</span>')

            # Add choices
            if entry.choices:
                choices_str = ", ".join(f"<code>{escape_html(str(c))}</code>" for c in entry.choices)
                metadata_items.append(
                    f'<span class="metadata-item metadata-choices"><span class="metadata-label">choices:</span> {choices_str}</span>'
                )

            # Add default
            if entry.default is not None:
                default_str = extract_text(entry.default, console)
                metadata_items.append(
                    f'<span class="metadata-item metadata-default"><span class="metadata-label">default:</span> <code>{escape_html(default_str)}</code></span>'
                )

            # Add environment variable
            if entry.env_var:
                env_html = ", ".join(f"<code>{escape_html(e)}</code>" for e in entry.env_var)
                metadata_items.append(
                    f'<span class="metadata-item metadata-env"><span class="metadata-label">env:</span> {env_html}</span>'
                )

            # Write metadata
            if metadata_items:
                self._output.write(f'<span class="parameter-metadata">{"".join(metadata_items)}</span>')

            self._output.write("</li>\n")

        self._output.write("</ul>\n")

    def render_usage(
        self,
        console: Optional["Console"],
        options: Optional["ConsoleOptions"],
        usage: Any,
    ) -> None:
        """Render the usage line as HTML.

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
            usage_text = escape_html(extract_text(usage, console))
            if usage_text:
                self._output.write('<div class="usage-block">\n')
                # Add "Usage:" prefix if not already present (for custom usage strings)
                if not usage_text.strip().startswith("Usage:"):
                    self._output.write(f'<pre class="usage">Usage: {usage_text}</pre>\n')
                else:
                    self._output.write(f'<pre class="usage">{usage_text}</pre>\n')
                self._output.write("</div>\n")

    def render_description(
        self,
        console: Optional["Console"],
        options: Optional["ConsoleOptions"],
        description: Any,
    ) -> None:
        """Render the description as HTML.

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
            desc_text = escape_html(extract_text(description, console))
            if desc_text:
                self._output.write(f'<div class="description">{desc_text}</div>\n')
