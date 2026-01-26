"""InlineText class for rich text rendering with appended metadata."""

import sys
from typing import TYPE_CHECKING

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

if TYPE_CHECKING:
    from rich.console import RenderableType
    from rich.text import Text


class InlineText:
    def __init__(self, primary_renderable: "RenderableType", *, force_empty_end=False):
        self.primary_renderable = primary_renderable
        self.texts = []
        self.force_empty_end = force_empty_end

    @classmethod
    def from_format(
        cls,
        content: str | None,
        format: str,
        *,
        force_empty_end: bool = False,
        show_errors: bool = False,
    ) -> Self:
        if content is None:
            from rich.text import Text

            primary_renderable = Text(end="")
        elif format == "plaintext":
            from rich.text import Text

            primary_renderable = Text(content.rstrip())
        elif format in ("markdown", "md"):
            from rich.markdown import Markdown

            primary_renderable = Markdown(content)
        elif format in ("restructuredtext", "rst"):
            from rich_rst import RestructuredText

            from cyclopts.help.rst_preprocessor import process_sphinx_directives

            processed_content = process_sphinx_directives(content)
            primary_renderable = RestructuredText(processed_content, show_errors=show_errors)
        elif format == "rich":
            from rich.text import Text

            primary_renderable = Text.from_markup(content)
        else:
            raise ValueError(f'Unknown help_format "{format}"')

        return cls(primary_renderable, force_empty_end=force_empty_end)

    def append(self, text: "Text"):
        self.texts.append(text)

    def __rich_console__(self, console, options):
        from rich.segment import Segment
        from rich.text import Text

        if not self.primary_renderable and not self.texts:
            return

        # Group segments by line
        lines_of_segments, current_line = [], []
        for segment in console.render(self.primary_renderable, options):
            if segment.text == "\n":
                lines_of_segments.append(current_line + [segment])
                current_line = []
            else:
                current_line.append(segment)

        if current_line:
            lines_of_segments.append(current_line)

        # If no content, just yield the additional texts
        if not lines_of_segments:
            if self.texts:
                combined_text = Text.assemble(*self.texts)
                yield from console.render(combined_text, options)
            return

        # Yield all but the last line unchanged
        for line in lines_of_segments[:-1]:
            for segment in line:
                yield segment

        # For the last line, concatenate all of our additional texts;
        # We have to re-render to properly handle textwrapping.
        if lines_of_segments:
            last_line = lines_of_segments[-1]

            # Check for newline at end
            has_newline = last_line and last_line[-1].text == "\n"
            newline_segment = last_line.pop() if has_newline else None

            # rstrip the last segment
            if last_line:
                last_segment = last_line[-1]
                last_segment = Segment(
                    last_segment.text.rstrip(),
                    style=last_segment.style,
                    control=last_segment.control,
                )
                last_line[-1] = last_segment

            # Convert last line segments to text and combine with additional text
            last_line_text = Text("", end="")
            for segment in last_line:
                if segment.text:
                    last_line_text.append(segment.text, segment.style)

            separator = Text(" ")
            for text in self.texts:
                if last_line_text:
                    last_line_text += separator
                last_line_text += text

            # Re-render with proper wrapping
            wrapped_segments = list(console.render(last_line_text, options))

            if self.force_empty_end:
                last_segment = wrapped_segments[-1]
                if last_segment and not last_segment.text.endswith("\n"):
                    wrapped_segments.append(Segment("\n"))

            # Add back newline if it was present
            if newline_segment:
                wrapped_segments.append(newline_segment)

            yield from wrapped_segments
