"""Silent Rich object that renders nothing."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions, RenderResult


class SilentRich:
    """Dummy object that causes nothing to be printed."""

    def __rich_console__(self, console: "Console", options: "ConsoleOptions") -> "RenderResult":
        # This generator yields nothing, so ``rich`` will print nothing for this object.
        if False:
            yield


SILENT = SilentRich()
