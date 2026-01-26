from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions, RenderableType

    from .help import HelpEntry, HelpPanel
    from .specs import ColumnSpec


@runtime_checkable
class Renderer(Protocol):
    """Protocol for column renderers that transform HelpEntry to display content."""

    def __call__(self, entry: "HelpEntry") -> "RenderableType": ...


@runtime_checkable
class ColumnSpecBuilder(Protocol):
    """Protocol for ColumnSpecBuilders."""

    def __call__(
        self, console: "Console", options: "ConsoleOptions", entries: list["HelpEntry"]
    ) -> tuple["ColumnSpec", ...]:
        """Build column specifications based on console settings and entries.

        Parameters
        ----------
        console : ~rich.console.Console
            The Rich console instance.
        options : ~rich.console.ConsoleOptions
            Console rendering options.
        entries : list[HelpEntry]
            List of help entries to be displayed.

        Returns
        -------
        tuple[ColumnSpec, ...]
            Tuple of column specifications for table rendering.
        """
        ...


@runtime_checkable
class HelpFormatter(Protocol):
    """Protocol for help **formatter** functions.

    It's the Formatter's job to transform a :class:`.HelpPanel` into rendered text on the display.

    Implementations may optionally provide the following methods for custom rendering of "usage" and "description". If these methods are not provided, default rendering will be used.

    .. code-block:: python

        def render_usage(self, console: Console, options: ConsoleOptions, usage: Any) -> None:
            \"\"\"Render the usage line.\"\"\"
            ...

        def render_description(self, console: Console, options: ConsoleOptions, description: Any) -> None:
            \"\"\"Render the description.\"\"\"
            ...
    """

    def __call__(
        self,
        console: "Console",
        options: "ConsoleOptions",
        panel: "HelpPanel",
    ) -> None:
        """Format and render a single help panel.

        Parameters
        ----------
        console : ~rich.console.Console
            Console to render to.
        options : ~rich.console.ConsoleOptions
            Console rendering options.
        panel : HelpPanel
            Help panel to render (commands, parameters, etc).
        """
        ...
