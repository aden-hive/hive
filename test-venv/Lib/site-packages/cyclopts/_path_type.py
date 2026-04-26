""":class:`StdioPath` - A Path subclass that treats ``-`` as stdin/stdout.

Requires Python 3.12+ for proper Path subclassing support.
"""

import io
import sys
from pathlib import Path
from typing import IO, TYPE_CHECKING

from cyclopts.parameter import Parameter

if TYPE_CHECKING:
    from collections.abc import Buffer


class _NonClosingIOWrapper:
    """Wrapper around an IO stream that doesn't close on context exit.

    This is used to wrap stdin/stdout so they can be used as context managers
    without being closed when the context exits.
    """

    def __init__(self, stream: IO, detach_on_exit: bool = False):
        self._stream = stream
        self._detach_on_exit = detach_on_exit

    def __enter__(self):
        return self._stream

    def __exit__(self, *args):
        # Flush any buffered data (important for TextIOWrapper)
        self._stream.flush()
        if self._detach_on_exit:
            self._stream.detach()  # Detach TextIOWrapper without closing underlying buffer

    def __getattr__(self, name):
        return getattr(self._stream, name)


@Parameter(allow_leading_hyphen=True)
class StdioPath(Path):
    """A :class:`~pathlib.Path` subclass that treats ``-`` as stdin/stdout."""

    STDIO_STRING: str = "-"
    """The string that represents stdin/stdout. Override in subclasses for custom behavior."""

    @property
    def is_stdio(self) -> bool:
        """Return True if this represents stdin/stdout.

        Override this property in subclasses for custom matching logic
        (e.g., matching multiple strings or using pattern matching).
        """
        return str(self) == self.STDIO_STRING

    def __repr__(self):
        return f"{type(self).__name__}({str(self)!r})"

    def exists(self, *, follow_symlinks: bool = True) -> bool:
        """Return True if path exists. Always True for stdio."""
        return True if self.is_stdio else super().exists(follow_symlinks=follow_symlinks)

    def open(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ):
        """Open the file or return stdin/stdout.

        For stdio paths, returns a wrapper around the appropriate stream
        (stdin for reading, stdout for writing) that doesn't close on context exit.
        For regular paths, behaves like the standard Path.open().
        """
        if self.is_stdio:
            is_binary = "b" in mode
            is_write = "w" in mode or "a" in mode
            # Always get the buffer stream
            buffer_stream = sys.stdout.buffer if is_write else sys.stdin.buffer
            if is_binary:
                stream = _NonClosingIOWrapper(buffer_stream)
            else:
                # For text mode, wrap the binary stream with TextIOWrapper
                text_stream = io.TextIOWrapper(
                    buffer_stream,
                    encoding=encoding or "utf-8",
                    errors=errors or "strict",
                    newline=newline,
                )
                stream = _NonClosingIOWrapper(text_stream, detach_on_exit=True)
            return stream
        return super().open(mode, buffering, encoding, errors, newline)

    def read_text(self, encoding: str | None = None, errors: str | None = None, newline: str | None = None) -> str:
        """Read entire contents as text."""
        if self.is_stdio:
            wrapper = io.TextIOWrapper(
                sys.stdin.buffer,
                encoding=encoding or "utf-8",
                errors=errors or "strict",
                newline=newline,
            )
            try:
                return wrapper.read()
            finally:
                wrapper.detach()  # Detach without closing stdin.buffer
        # newline parameter added in Python 3.13
        if sys.version_info >= (3, 13):
            return super().read_text(encoding=encoding, errors=errors, newline=newline)
        else:
            return super().read_text(encoding=encoding, errors=errors)

    def read_bytes(self) -> bytes:
        """Read entire contents as bytes."""
        if self.is_stdio:
            return sys.stdin.buffer.read()
        return super().read_bytes()

    def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        """Write text data."""
        if self.is_stdio:
            wrapper = io.TextIOWrapper(
                sys.stdout.buffer,
                encoding=encoding or "utf-8",
                errors=errors or "strict",
                newline=newline,
            )
            try:
                wrapper.write(data)
                wrapper.flush()
                # TextIOWrapper doesn't return bytes written, so calculate from encoded data
                # Apply same newline translation that TextIOWrapper does
                if newline is None or newline == "":
                    encoded_data = data
                else:
                    encoded_data = data.replace("\n", newline)
                return len(encoded_data.encode(encoding or "utf-8", errors or "strict"))
            finally:
                wrapper.detach()  # Detach without closing stdout.buffer
        return super().write_text(data, encoding=encoding, errors=errors, newline=newline)

    def write_bytes(self, data: "Buffer") -> int:
        """Write binary data."""
        if self.is_stdio:
            return sys.stdout.buffer.write(data)
        return super().write_bytes(data)
