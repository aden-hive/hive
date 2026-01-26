"""Markup and format conversion utilities.

Pure utility layer for text processing across help and docs systems.
"""

import io
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from rich.console import Console


def extract_text(obj: Any, console: Optional["Console"] = None, preserve_markup: bool = False) -> str:
    """Extract text from Rich renderables or any object.

    Parameters
    ----------
    obj : Any
        Object to convert to text.
    console : Console | None
        Console for rendering Rich objects.
    preserve_markup : bool
        If True, preserve original markdown/RST markup when available.
        When False, always render to plain text.

    Returns
    -------
    str
        Text representation (plain or with markup preserved).
    """
    if obj is None:
        return ""

    if hasattr(obj, "primary_renderable"):
        primary = getattr(obj, "primary_renderable", None)
        if primary is not None:
            if preserve_markup and hasattr(primary, "markup"):
                return primary.markup.rstrip()
            return extract_text(primary, console, preserve_markup=preserve_markup)

    if hasattr(obj, "plain"):
        return obj.plain.rstrip()

    if preserve_markup and hasattr(obj, "markup"):
        return obj.markup.rstrip()

    if hasattr(obj, "__rich_console__"):
        from rich.console import Console

        plain_console = Console(
            file=io.StringIO(),
            width=console.width if console else 120,
            force_terminal=False,
            no_color=True,
            highlight=False,
            markup=False,
            emoji=False,
        )
        with plain_console.capture() as capture:
            plain_console.print(obj, end="")
        return capture.get().rstrip()

    return str(obj).rstrip()


def escape_rst(text: str | None) -> str:
    """Escape special reStructuredText characters in text.

    Parameters
    ----------
    text : str | None
        Text to escape. Can be None.

    Returns
    -------
    str
        Escaped text safe for RST.
    """
    if not text:
        return ""
    return text.replace("\\", "\\\\")


def escape_markdown(text: str | None) -> str | None:
    """Escape special markdown characters in text.

    If the text appears to already contain markdown formatting (bold, italic,
    code, links, or headings), it is returned unchanged. Otherwise, pipe
    characters are escaped for table compatibility.

    Parameters
    ----------
    text : str | None
        Text to escape. Can be None.

    Returns
    -------
    str | None
        Escaped text safe for markdown, or None if input was None.
    """
    if not text:
        return text

    if any(pattern in text for pattern in ["**", "``", "`", "](", "#"]):
        return text

    text = text.replace("|", "\\|")
    return text


def escape_html(text: str | None) -> str:
    """Escape special HTML characters in text.

    Parameters
    ----------
    text : str | None
        Text to escape. Can be None.

    Returns
    -------
    str
        Escaped text safe for HTML.
    """
    if not text:
        return ""

    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    text = text.replace("'", "&#x27;")
    return text
