"""Text chunking strategies for document processing."""

from __future__ import annotations


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    separator: str = "\n\n",
) -> list[str]:
    """
    Split text into chunks with overlap using a recursive strategy.
    Args:
        text: Input text to chunk
        chunk_size: Maximum characters per chunk
        chunk_overlap: Number of overlapping characters between chunks
        separator: Primary separator to use for splitting
    Returns:
        List of text chunks
    """
    if not text or chunk_size <= 0:
        return []

    # If text is smaller than chunk_size, return as-is
    if len(text) <= chunk_size:
        return [text]

    separators = [separator, "\n", ". ", " ", ""]

    def _split_text(text: str, seps: list[str]) -> list[str]:
        """Recursively split text using available separators."""
        if not seps:
            # Base case: split by character
            return [
                text[i : i + chunk_size] for i in range(0, len(text), chunk_size - chunk_overlap)
            ]

        current_sep = seps[0]
        remaining_seps = seps[1:]

        # Split by current separator
        splits = text.split(current_sep) if current_sep else list(text)

        result = []
        current_chunk = ""

        for split in splits:
            # Add separator back (except for empty separator)
            split_with_sep = split + (current_sep if current_sep and split else "")

            # If adding this split would exceed chunk_size
            if len(current_chunk) + len(split_with_sep) > chunk_size:
                if current_chunk:
                    result.append(current_chunk.strip())
                    # Start new chunk with overlap
                    if chunk_overlap > 0 and len(current_chunk) > chunk_overlap:
                        current_chunk = current_chunk[-chunk_overlap:] + split_with_sep
                    else:
                        current_chunk = split_with_sep
                else:
                    # Single split is too large, try next separator
                    if len(split_with_sep) > chunk_size:
                        result.extend(_split_text(split_with_sep, remaining_seps))
                        current_chunk = ""
                    else:
                        current_chunk = split_with_sep
            else:
                current_chunk += split_with_sep

        # Add remaining chunk
        if current_chunk:
            result.append(current_chunk.strip())

        return result

    return _split_text(text, separators)
