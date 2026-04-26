"""Default Rich-based help formatter."""

from typing import TYPE_CHECKING, Any, Optional, Union

from attrs import define

from cyclopts.help.silent import SILENT

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions, RenderableType

    from cyclopts.help import HelpPanel
    from cyclopts.help.protocols import ColumnSpecBuilder
    from cyclopts.help.specs import ColumnSpec, PanelSpec, TableSpec


@define(kw_only=True)
class DefaultFormatter:
    """Default help formatter using Rich library with customizable specs.

    Parameters
    ----------
    panel_spec : Optional[PanelSpec]
        Panel specification for the outer box/panel styling.
    table_spec : Optional[TableSpec]
        Table specification for table styling (borders, padding, etc).
    column_specs : Optional[Union[tuple[ColumnSpec, ...], ColumnSpecBuilder]]
        Column specifications or builder function for table columns.

    Notes
    -----
    The relationship between these specs can be visualized as:

    ::

        ╭─ Commands ───────────────────────────────────────────────────────╮  ← panel_spec
        │ serve     Start the development server                           │     (border, title)
        │ --help    Display this message and exit.                         │
        ╰──────────────────────────────────────────────────────────────────╯
         ↑         ↑
         col[0]    col[1]
         (name)    (description)

        ╭─ Parameters ─────────────────────────────────────────────────────╮  ← panel_spec
        │ *  PORT --port        Server port number [required]              │
        │    VERBOSE --verbose  Enable verbose output [default: False]     │
        ╰──────────────────────────────────────────────────────────────────╯
         ↑  ↑                  ↑
         │  col[1]             col[2]
         │  (name/flags)       (description)
         │
         col[0]
         (required marker)

    Where:

    - ``panel_spec`` controls the outer panel appearance (border, title, etc.)
    - ``table_spec`` controls the inner table styling (no visible borders by default)
    - ``column_specs`` defines individual columns (width, style, alignment, etc.)
    """

    panel_spec: Optional["PanelSpec"] = None
    """Panel specification for the outer box/panel styling (border, title, padding, etc)."""

    table_spec: Optional["TableSpec"] = None
    """Table specification for table styling (borders, padding, column separation, etc)."""

    column_specs: Union[tuple["ColumnSpec", ...], "ColumnSpecBuilder"] | None = None
    """Column specifications or builder function for table columns (width, style, alignment, etc)."""

    @classmethod
    def with_newline_metadata(cls, **kwargs):
        """Create formatter with metadata on separate lines.

        Returns a DefaultFormatter configured to display parameter metadata
        (choices, env vars, defaults) on separate indented lines rather
        than inline with descriptions.

        Parameters
        ----------
        **kwargs
            Additional keyword arguments to pass to DefaultFormatter constructor.

        Returns
        -------
        DefaultFormatter
            Configured formatter instance with newline metadata display.

        Examples
        --------
        >>> from cyclopts import App
        >>> from cyclopts.help import DefaultFormatter
        >>> app = App(help_formatter=DefaultFormatter.with_newline_metadata())
        """

        def column_builder(console, options, entries):
            import math

            from cyclopts.help.specs import (
                AsteriskColumn,
                ColumnSpec,
                DescriptionRenderer,
                NameRenderer,
            )

            max_width = math.ceil(console.width * 0.35)
            name_column = ColumnSpec(
                renderer=NameRenderer(max_width=max_width),
                header="Option",
                style="cyan",
                max_width=max_width,
            )

            description_column = ColumnSpec(
                renderer=DescriptionRenderer(newline_metadata=True), header="Description", overflow="fold"
            )

            if any(x.required for x in entries):
                return (AsteriskColumn, name_column, description_column)
            return (name_column, description_column)

        return cls(column_specs=column_builder, **kwargs)

    def __call__(self, console: "Console", options: "ConsoleOptions", panel: "HelpPanel") -> None:
        """Format and render a single help panel using Rich.

        Parameters
        ----------
        console : ~rich.console.Console
            Console to render to.
        options : ~rich.console.ConsoleOptions
            Console rendering options.
        panel : HelpPanel
            Help panel to render.
        """
        rendered = self._render_panel(panel, console, options)
        console.print(rendered)

    def render_usage(self, console: "Console", options: "ConsoleOptions", usage: Any) -> None:
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
            from rich.text import Text

            # Add "Usage:" prefix if not already present (for custom usage strings)
            usage_str = str(usage)
            if not usage_str.strip().startswith("Usage:"):
                if isinstance(usage, Text):
                    usage_with_label = Text("Usage: ", style="bold") + usage
                else:
                    usage_with_label = Text(f"Usage: {usage}", style="bold")
            else:
                # Custom usage already has "Usage:", use as-is
                usage_with_label = usage if isinstance(usage, Text) else Text(str(usage), style="bold")
            console.print(usage_with_label)

    def render_description(self, console: "Console", options: "ConsoleOptions", description: Any) -> None:
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
            console.print(description)

    def _render_panel(self, help_panel: "HelpPanel", console: "Console", options: "ConsoleOptions") -> "RenderableType":
        """Render a single help panel."""
        if not help_panel.entries:
            return SILENT

        from rich.console import Group as RichGroup
        from rich.console import NewLine
        from rich.text import Text

        from cyclopts.help.specs import (
            PanelSpec,
            TableSpec,
            get_default_command_columns,
            get_default_parameter_columns,
        )

        panel_description = help_panel.description
        if isinstance(panel_description, Text):
            panel_description.end = ""

            if panel_description.plain:
                panel_description = RichGroup(panel_description, NewLine(2))

        # Get table spec (styling only)
        table_spec = self.table_spec or TableSpec()
        panel_spec = self.panel_spec or PanelSpec()

        # Determine/Resolve column specs
        columns = self.column_specs
        if columns is None:
            # Use default columns based on panel format
            if help_panel.format == "command":
                columns = get_default_command_columns
            else:
                columns = get_default_parameter_columns

        if callable(columns):
            # It's a column builder
            columns = columns(console, options, help_panel.entries)

        # Build table with columns and entries
        table = table_spec.build(columns, help_panel.entries)

        # Build the panel
        assert panel_description is not None  # Always true due to attrs converter
        if panel_spec.title is None:
            panel = panel_spec.build(RichGroup(panel_description, table), title=help_panel.title)
        else:
            panel = panel_spec.build(RichGroup(panel_description, table))

        return panel
