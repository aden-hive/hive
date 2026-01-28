"""Cyclopts panel utilities for Rich-based terminal output."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rich.panel import Panel


def CycloptsPanel(message: Any, title: str = "Error", style: str = "red") -> "Panel":  # noqa: N802
    """Create a :class:`~rich.panel.Panel` with a consistent style.

    The resulting panel can be displayed using a :class:`~rich.console.Console`.

    .. code-block:: text

        ╭─ Title ──────────────────────────────────╮
        │ Message content here.                    │
        ╰──────────────────────────────────────────╯

    Parameters
    ----------
    message: Any
        The body of the panel will be filled with the stringified version of the message.
    title: str
        Title of the panel that appears in the top-left corner.
    style: str
        Rich `style <https://rich.readthedocs.io/en/stable/style.html>`_ for the panel border.

    Returns
    -------
    ~rich.panel.Panel
        Formatted panel object.
    """
    from rich import box
    from rich.panel import Panel
    from rich.text import Text

    panel = Panel(
        Text(str(message), "default"),
        title=title,
        style=style,
        box=box.ROUNDED,
        expand=True,
        title_align="left",
    )
    return panel
