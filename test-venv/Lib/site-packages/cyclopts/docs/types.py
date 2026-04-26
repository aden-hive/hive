"""Type definitions and utilities for documentation generation."""

from typing import Literal

# All accepted format values (canonical and aliases)
DocFormat = Literal["markdown", "md", "html", "htm", "rst", "rest", "restructuredtext"]

# Canonical format values only
CanonicalDocFormat = Literal["markdown", "html", "rst"]

# Map all aliases to their canonical format
# Also used for suffix lookups by stripping the leading period
FORMAT_ALIASES: dict[str, CanonicalDocFormat] = {
    "md": "markdown",
    "markdown": "markdown",
    "html": "html",
    "htm": "html",
    "rst": "rst",
    "rest": "rst",
    "restructuredtext": "rst",
}


def normalize_format(format_value: str) -> CanonicalDocFormat:
    """Normalize format aliases to standard format names.

    Parameters
    ----------
    format_value : str
        The format string to normalize (case-insensitive).

    Returns
    -------
    CanonicalDocFormat
        The canonical format name.

    Raises
    ------
    ValueError
        If the format is not recognized.
    """
    format_lower = format_value.lower()
    canonical_format = FORMAT_ALIASES.get(format_lower)

    if canonical_format is None:
        raise ValueError(
            f'Unsupported format "{format_value}". Supported formats: {", ".join(sorted(FORMAT_ALIASES.keys()))}'
        )

    return canonical_format
