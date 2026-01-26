"""Preprocessing utilities for reStructuredText content.

This module provides workarounds for limitations in the rich_rst library when rendering
Sphinx directives. While rich_rst handles standard reStructuredText well, it doesn't
support Sphinx-specific directives (versionadded, deprecated, note, warning, etc.).

Since Cyclopts docstrings may contain these directives, we preprocess RST content to
convert Sphinx directives into plain text annotations before passing to rich_rst. This
ensures users see meaningful information in CLI help rather than raw directive syntax.

This is a pragmatic workaround; ideally this functionality would be in rich_rst itself.
"""

import re
from collections.abc import Callable


def _skip_indented_block(lines: list[str], start_index: int, base_indent: int) -> int:
    """Skip over lines indented more than base_indent.

    Parameters
    ----------
    lines : list[str]
        All lines in the text.
    start_index : int
        Index to start from.
    base_indent : int
        Base indentation level; lines must be indented more than this.

    Returns
    -------
    int
        Index of the first non-matching line (or len(lines) if reached end).
    """
    i = start_index
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if not stripped or indent > base_indent:
            i += 1
        else:
            break

    return i


def _is_list_item(line: str) -> bool:
    """Check if a line is a list item.

    Parameters
    ----------
    line : str
        The stripped line to check.

    Returns
    -------
    bool
        True if the line starts with a list marker.
    """
    if not line:
        return False
    if line[0] in ("-", "*", "+"):
        return len(line) == 1 or line[1] in (" ", "\t")
    match = re.match(r"^\d+[\.\)](\s|$)", line)
    return match is not None


def _gather_indented_block(lines: list[str], start_index: int, base_indent: int) -> tuple[list[str], int]:
    """Gather lines indented more than base_indent, preserving structure.

    This function preserves paragraph breaks (blank lines), list structure,
    and code block indentation while gathering indented content. List items
    are kept on separate lines. Lines that are indented beyond the minimum
    content indentation (like code blocks) preserve their relative indentation.

    Parameters
    ----------
    lines : list[str]
        All lines in the text.
    start_index : int
        Index to start from.
    base_indent : int
        Base indentation level; lines must be indented more than this.

    Returns
    -------
    content_lines : list[str]
        Content lines preserving paragraph structure. Each element represents
        either a paragraph (multiple lines joined with spaces), a single
        list item line, or indented code lines.
    end_index : int
        Index of the first non-matching line (or len(lines) if reached end).
    """
    # First pass: collect all content and determine minimum indentation
    collected_lines = []
    i = start_index
    min_indent = float("inf")

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if indent > base_indent or not stripped:
            if stripped:
                min_indent = min(min_indent, indent)
            collected_lines.append((line, indent, stripped))
            i += 1
        else:
            break

    if min_indent == float("inf"):
        min_indent = base_indent + 1

    # Second pass: format content preserving relative indentation
    paragraphs = []
    current_paragraph = []
    last_was_empty = False

    for _, indent, stripped in collected_lines:
        if not stripped:
            if current_paragraph:
                paragraphs.append(" ".join(current_paragraph))
                current_paragraph = []
            last_was_empty = True
        else:
            is_list = _is_list_item(stripped)
            is_code_block = indent > min_indent

            if is_list:
                if current_paragraph:
                    paragraphs.append(" ".join(current_paragraph))
                    current_paragraph = []
                paragraphs.append(stripped)
                last_was_empty = False
            elif is_code_block:
                # Preserve code block indentation
                if current_paragraph:
                    paragraphs.append(" ".join(current_paragraph))
                    current_paragraph = []
                # Preserve relative indentation (subtract min_indent to normalize)
                relative_indent = indent - min_indent
                paragraphs.append(" " * relative_indent + stripped)
                last_was_empty = False
            else:
                if last_was_empty and current_paragraph:
                    paragraphs.append(" ".join(current_paragraph))
                    current_paragraph = []
                current_paragraph.append(stripped)
                last_was_empty = False

    if current_paragraph:
        paragraphs.append(" ".join(current_paragraph))

    return paragraphs, i


def _handle_version_directive(
    directive_name: str, directive_arg: str, lines: list[str], start_index: int, current_indent: int
) -> tuple[str, int]:
    """Handle versionadded and versionchanged directives.

    Parameters
    ----------
    directive_name : str
        Name of the directive (e.g., "versionadded").
    directive_arg : str
        Version number argument.
    lines : list[str]
        All lines in the text.
    start_index : int
        Current line index.
    current_indent : int
        Current indentation level.

    Returns
    -------
    tag : str
        Formatted tag text.
    next_index : int
        Next line index to process.
    """
    prefix = "Added" if directive_name == "versionadded" else "Changed"
    tag = f"[{prefix} in v{directive_arg}]"
    return tag, start_index + 1


def _handle_deprecated_directive(
    directive_name: str, directive_arg: str, lines: list[str], start_index: int, current_indent: int
) -> tuple[str, int]:
    """Handle deprecated directive with optional content.

    Parameters
    ----------
    directive_name : str
        Name of the directive ("deprecated").
    directive_arg : str
        Version number argument.
    lines : list[str]
        All lines in the text.
    start_index : int
        Current line index.
    current_indent : int
        Current indentation level.

    Returns
    -------
    tag : str
        Formatted tag text with optional content.
    next_index : int
        Next line index to process.
    """
    paragraphs, next_i = _gather_indented_block(lines, start_index + 1, current_indent)
    content = "\n\n".join(paragraphs).strip()
    tag = f"[⚠ Deprecated in v{directive_arg}]"
    return f"{tag} {content}" if content else tag, next_i


def _handle_admonition_directive(
    directive_name: str, directive_arg: str, lines: list[str], start_index: int, current_indent: int
) -> tuple[str, int]:
    """Handle note, warning, and seealso directives.

    Parameters
    ----------
    directive_name : str
        Name of the directive (e.g., "note", "warning", "seealso").
    directive_arg : str
        Inline content on the directive line.
    lines : list[str]
        All lines in the text.
    start_index : int
        Current line index.
    current_indent : int
        Current indentation level.

    Returns
    -------
    tag : str
        Formatted tag text with content.
    next_index : int
        Next line index to process.
    """
    paragraphs = [directive_arg] if directive_arg else []
    more_paragraphs, next_i = _gather_indented_block(lines, start_index + 1, current_indent)
    paragraphs.extend(more_paragraphs)

    blocks = []
    current_list = []
    current_code_block = []

    for para in paragraphs:
        is_list = _is_list_item(para)
        is_code = para.startswith(" ") and para.strip()  # Code block lines start with space

        if is_list:
            # Flush any current blocks
            if current_code_block:
                blocks.append("\n".join(current_code_block))
                current_code_block = []
            current_list.append(para)
        elif is_code:
            # Flush current list if any
            if current_list:
                blocks.append("\n".join(current_list))
                current_list = []
            current_code_block.append(para)
        else:
            # Regular paragraph
            if current_list:
                blocks.append("\n".join(current_list))
                current_list = []
            if current_code_block:
                blocks.append("\n".join(current_code_block))
                current_code_block = []
            blocks.append(para)

    # Flush any remaining blocks
    if current_list:
        blocks.append("\n".join(current_list))
    if current_code_block:
        blocks.append("\n".join(current_code_block))

    content = "\n\n".join(blocks).strip()

    prefix_map = {
        "note": "Note:",
        "warning": "⚠ Warning:",
        "seealso": "See also:",
    }
    prefix = prefix_map[directive_name]
    formatted = f"\n\n{prefix} {content}\n\n" if content else f"\n\n{prefix}\n\n"
    return formatted, next_i


DirectiveHandler = Callable[[str, str, list[str], int, int], tuple[str, int]]

DIRECTIVE_HANDLERS: dict[str, DirectiveHandler] = {
    "versionadded": _handle_version_directive,
    "versionchanged": _handle_version_directive,
    "deprecated": _handle_deprecated_directive,
    "note": _handle_admonition_directive,
    "warning": _handle_admonition_directive,
    "seealso": _handle_admonition_directive,
}


def process_sphinx_directives(text: str | None) -> str:
    """Process Sphinx directives in reStructuredText content for CLI help display.

    Converts Sphinx directives to readable format:
    - .. versionadded:: X -> [Added in vX]
    - .. versionchanged:: X -> [Changed in vX]
    - .. deprecated:: X -> [⚠ Deprecated in vX]
    - .. note:: content -> Note: content
    - .. warning:: content -> ⚠ Warning: content
    - .. seealso:: content -> See also: content

    Unknown directives are silently removed but logged as debug messages.

    Parameters
    ----------
    text : str | None
        The reStructuredText content to process.

    Returns
    -------
    str
        Processed text with directives converted to inline annotations.
        Returns empty string if input is None or empty.
    """
    if not text:
        return ""

    lines = text.split("\n")
    result_parts = []
    version_tags = []
    first_inline_directive_idx = None
    i = 0

    # Admonition directives that should appear inline at their position
    admonition_directives = {"note", "warning", "seealso"}

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        current_indent = len(line) - len(stripped)

        if stripped.startswith("..") and "::" in stripped:
            match = re.match(r"\.\.\s+(\w+)::\s*(.*)", stripped)
            if match:
                directive_name = match.group(1)
                directive_arg = match.group(2).strip()

                handler = DIRECTIVE_HANDLERS.get(directive_name)
                if handler:
                    tag, next_i = handler(directive_name, directive_arg, lines, i, current_indent)
                    if directive_name in admonition_directives:
                        # Track position of first inline directive
                        if first_inline_directive_idx is None:
                            first_inline_directive_idx = len(result_parts)
                        # Add inline directive (strip() removes the newlines added by handler)
                        result_parts.append(tag.strip())
                    else:
                        # Collect version/deprecated directives
                        version_tags.append(tag)
                    i = next_i
                else:
                    i = _skip_indented_block(lines, i + 1, current_indent)
            else:
                i = _skip_indented_block(lines, i + 1, current_indent)
        else:
            result_parts.append(line)
            i += 1

    # Append version tags
    if version_tags:
        # If there are inline directives and no text after them, insert tags before first inline directive
        if first_inline_directive_idx is not None:
            # Check if there's any non-empty text after the first inline directive
            has_text_after = any(
                result_parts[i].strip() for i in range(first_inline_directive_idx + 1, len(result_parts))
            )
            if not has_text_after:
                # Insert before first inline directive
                _insert_version_tags_at_index(result_parts, version_tags, first_inline_directive_idx)
            else:
                # Insert at the end
                _insert_version_tags(result_parts, version_tags)
        else:
            # No inline directives, insert at the end
            _insert_version_tags(result_parts, version_tags)

    result = "\n".join(result_parts).strip()
    return result


def _insert_version_tags(result_parts: list[str], version_tags: list[str]) -> None:
    """Insert version tags at the end of the last non-empty line."""
    tags_text = " ".join(version_tags)
    if result_parts:
        # Find last non-empty line
        for idx in range(len(result_parts) - 1, -1, -1):
            if result_parts[idx].strip():
                result_parts[idx] = f"{result_parts[idx]} {tags_text}"
                return
        # All lines are empty, append tags as new line
        result_parts.append(tags_text)
    else:
        result_parts.append(tags_text)


def _insert_version_tags_at_index(result_parts: list[str], version_tags: list[str], before_index: int) -> None:
    """Insert version tags before the specified index, appending to the last non-empty line before that index."""
    tags_text = " ".join(version_tags)
    # Find last non-empty line before the index
    for idx in range(before_index - 1, -1, -1):
        if result_parts[idx].strip():
            result_parts[idx] = f"{result_parts[idx]} {tags_text}"
            return
    # All lines before index are empty, insert at the index
    result_parts.insert(before_index, tags_text)
