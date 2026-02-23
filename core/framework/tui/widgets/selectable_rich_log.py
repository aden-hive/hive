"""
SelectableRichLog - RichLog with mouse-driven text selection and clipboard copy.

Drop-in replacement for RichLog. Click-and-drag to select text, which is
visually highlighted. Press Ctrl+C to copy selection to clipboard (handled
by app.py). Press Escape or single-click to clear selection.
"""

from __future__ import annotations

import subprocess
import sys

from rich.segment import Segment as RichSegment
from rich.style import Style
from textual.geometry import Offset
from textual.selection import Selection
from textual.strip import Strip
from textual.widgets import RichLog

# Highlight style for selected text
_HIGHLIGHT_STYLE = Style(bgcolor="blue", color="white")


class SelectableRichLog(RichLog):
    """RichLog with mouse-driven text selection."""

    DEFAULT_CSS = """
    SelectableRichLog {
        pointer: text;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sel_anchor: Offset | None = None
        self._sel_end: Offset | None = None
        self._selecting: bool = False

    # -- Internal helpers --

    def _apply_highlight(self, strip: Strip) -> Strip:
        """Apply highlight with correct precedence (highlight wins over base style)."""
        segments = []
        for text, style, control in strip._segments:
            if control:
                segments.append(RichSegment(text, style, control))
            else:
                new_style = (style + _HIGHLIGHT_STYLE) if style else _HIGHLIGHT_STYLE
                segments.append(RichSegment(text, new_style, control))
        return Strip(segments, strip.cell_length)

    # -- Selection helpers --

    @property
    def selection(self) -> Selection | None:
        """Build a Selection from current anchor/end, or None if no selection."""
        if self._sel_anchor is None or self._sel_end is None:
            return None
        if self._sel_anchor == self._sel_end:
            return None
        return Selection.from_offsets(self._sel_anchor, self._sel_end)

    def _mouse_to_content(self, event_x: int, event_y: int) -> Offset:
        """Convert viewport mouse coords to content (line, col) coords."""
        scroll_x, scroll_y = self.scroll_offset
        return Offset(scroll_x + event_x, scroll_y + event_y)

    def clear_selection(self) -> None:
        """Clear any active selection."""
        had_selection = self._sel_anchor is not None
        self._sel_anchor = None
        self._sel_end = None
        self._selecting = False
        if had_selection:
            self.refresh()

    # -- Mouse handlers (left button only) --

    def on_mouse_down(self, event) -> None:
        """Start selection on left mouse button."""
        if event.button != 1:
            return
        self._sel_anchor = self._mouse_to_content(event.x, event.y)
        self._sel_end = self._sel_anchor
        self._selecting = True
        self.capture_mouse()
        self.refresh()

    def on_mouse_move(self, event) -> None:
        """Extend selection while dragging."""
        if not self._selecting:
            return
        self._sel_end = self._mouse_to_content(event.x, event.y)
        self.refresh()

    def on_mouse_up(self, event) -> None:
        """End selection on mouse release."""
        if not self._selecting:
            return
        self._selecting = False
        self.release_mouse()

        # Single-click (no drag) clears selection
        if self._sel_anchor == self._sel_end:
            self.clear_selection()

    # -- Keyboard handlers --

    def on_key(self, event) -> None:
        """Clear selection on Escape."""
        if event.key == "escape":
            self.clear_selection()

    # -- Rendering with highlight --

    def render_line(self, y: int) -> Strip:
        """Override to apply selection highlight on top of the base strip."""
        strip = super().render_line(y)

        sel = self.selection
        if sel is None:
            return strip

        # Determine which content line this viewport row corresponds to
        _, scroll_y = self.scroll_offset
        content_y = scroll_y + y

        span = sel.get_span(content_y)
        if span is None:
            return strip

        start_x, end_x = span
        cell_len = strip.cell_length
        if cell_len == 0:
            return strip

        scroll_x, _ = self.scroll_offset

        # -1 means "to end of content line" — use viewport end
        if end_x == -1:
            end_x = cell_len
        else:
            # Convert content-space x to viewport-space x
            end_x = end_x - scroll_x

        # Convert content-space x to viewport-space x
        start_x = start_x - scroll_x

        # Clamp to viewport strip bounds
        start_x = max(0, start_x)
        end_x = min(end_x, cell_len)

        if start_x >= end_x:
            return strip

        # Divide strip into [before, selected, after] and highlight the middle
        parts = strip.divide([start_x, end_x])
        if len(parts) < 2:
            return strip

        highlighted_parts: list[Strip] = []
        for i, part in enumerate(parts):
            if i == 1:
                highlighted_parts.append(self._apply_highlight(part))
            else:
                highlighted_parts.append(part)

        return Strip.join(highlighted_parts)

    # -- Text extraction & clipboard --

    def get_selected_text(self) -> str | None:
        """Extract the plain text of the current selection, or None."""
        sel = self.selection
        if sel is None:
            return None

        # Build full text from all lines
        all_text = "\n".join(strip.text for strip in self.lines)
        try:
            extracted = sel.extract(all_text)
        except (IndexError, ValueError):
            # Selection coordinates can exceed line count when the virtual
            # canvas is larger than the actual content (e.g. after scroll).
            return None
        return extracted if extracted else None

    def copy_selection(self) -> str | None:
        """Copy selected text to system clipboard. Returns text or None."""
        text = self.get_selected_text()
        if not text:
            return None
        _copy_to_clipboard(text)
        return text


def _copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard using platform-native tools."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True, timeout=5)
        elif sys.platform == "win32":
            subprocess.run(
                ["clip.exe"],
                input=text.encode("utf-16le"),
                check=True,
                timeout=5,
            )
        elif sys.platform.startswith("linux"):
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode(),
                    check=True,
                    timeout=5,
                )
            except (subprocess.SubprocessError, FileNotFoundError):
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode(),
                    check=True,
                    timeout=5,
                )
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
