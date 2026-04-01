"""Streaming XML tag filter for thinking tags.

Strips configured XML tags (e.g. ``<situation>``, ``<monologue>``) from
a chunked text stream while preserving the full text for conversation
storage.  The filter is stateful — it handles chunks that split mid-tag.

Only touches text content.  Tool calls flow through a completely separate
code path and are never affected by this filter.
"""

from __future__ import annotations

from collections.abc import Sequence


class ThinkingTagFilter:
    """Strips XML thinking tags from a streaming text output.

    Buffers content inside configured tags and yields only the visible
    content outside those tags.  Handles chunks that split across tag
    boundaries (e.g. a chunk ending with ``"<mono"``).

    Args:
        tag_names: Tag names to strip (e.g. ``["situation", "monologue"]``).
    """

    def __init__(self, tag_names: Sequence[str]) -> None:
        self._tag_names: set[str] = set(tag_names)
        # Pre-compute all opening and closing tag strings for matching.
        self._open_tags: dict[str, str] = {name: f"<{name}>" for name in tag_names}
        self._close_tags: dict[str, str] = {name: f"</{name}>" for name in tag_names}
        # All possible tag prefixes for partial-match detection.
        self._all_tag_strings: list[str] = sorted(
            list(self._open_tags.values()) + list(self._close_tags.values()),
            key=len,
            reverse=True,
        )

        self._inside_tag: str | None = None  # Which tag we're inside, or None.
        self._pending: str = ""  # Chars that might be a partial tag.
        self._visible_text: str = ""  # Accumulated visible snapshot.

    def feed(self, chunk: str) -> str:
        """Feed a text chunk and return the visible portion.

        Characters inside thinking tags are suppressed.  Characters that
        *might* be the start of a tag are buffered until the next chunk
        resolves the ambiguity.

        Returns:
            The portion of text that should be shown to the user.
        """
        buf = self._pending + chunk
        self._pending = ""
        visible = self._process(buf)
        self._visible_text += visible
        return visible

    @property
    def visible_snapshot(self) -> str:
        """Accumulated visible text so far (for the snapshot field)."""
        return self._visible_text

    def flush(self) -> str:
        """Flush any pending partial tag as visible text.

        Called at end-of-stream.  If characters were buffered because they
        looked like the start of a tag but the stream ended before the tag
        completed, they are emitted as visible text (graceful degradation).
        """
        result = ""
        if self._pending:
            if self._inside_tag is None:
                result = self._pending
            # If inside a tag, discard pending (unclosed tag content).
            self._pending = ""
        self._visible_text += result
        return result

    # ------------------------------------------------------------------
    # Internal processing
    # ------------------------------------------------------------------

    def _process(self, buf: str) -> str:
        """Process a buffer, returning visible text and updating state."""
        visible_parts: list[str] = []
        i = 0
        n = len(buf)

        while i < n:
            if self._inside_tag is not None:
                # Inside a tag — look for the closing tag.
                close = self._close_tags[self._inside_tag]
                close_pos = buf.find(close, i)
                if close_pos == -1:
                    # Closing tag might be split across chunks.
                    # Check if the tail of buf is a prefix of the close tag.
                    tail_len = min(len(close) - 1, n - i)
                    for tl in range(tail_len, 0, -1):
                        if close.startswith(buf[n - tl:]):
                            self._pending = buf[n - tl:]
                            i = n
                            break
                    else:
                        # No partial match — discard everything (inside tag).
                        i = n
                    break
                else:
                    # Found closing tag — skip past it and exit tag.
                    i = close_pos + len(close)
                    self._inside_tag = None
            else:
                # Outside any tag — look for '<'.
                lt_pos = buf.find("<", i)
                if lt_pos == -1:
                    # No '<' — everything is visible.
                    visible_parts.append(buf[i:])
                    i = n
                else:
                    # Emit text before the '<'.
                    if lt_pos > i:
                        visible_parts.append(buf[i:lt_pos])
                    # Try to match an opening tag at this position.
                    remainder = buf[lt_pos:]
                    matched = False
                    for name, open_tag in self._open_tags.items():
                        if remainder.startswith(open_tag):
                            # Full opening tag found — enter tag.
                            self._inside_tag = name
                            i = lt_pos + len(open_tag)
                            matched = True
                            break
                    if not matched:
                        # Check if remainder could be a partial tag prefix.
                        if self._is_partial_tag_prefix(remainder):
                            # Buffer and wait for next chunk.
                            self._pending = remainder
                            i = n
                        else:
                            # Not a known tag — '<' is visible text.
                            visible_parts.append("<")
                            i = lt_pos + 1

        return "".join(visible_parts)

    def _is_partial_tag_prefix(self, text: str) -> bool:
        """Check if text could be the start of a known tag string."""
        for tag_str in self._all_tag_strings:
            if tag_str.startswith(text) and len(text) < len(tag_str):
                return True
        return False
