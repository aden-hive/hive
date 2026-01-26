"""Documentation generation for cyclopts CLI applications."""

from cyclopts.docs.html import generate_html_docs
from cyclopts.docs.markdown import generate_markdown_docs
from cyclopts.docs.rst import generate_rst_docs
from cyclopts.docs.types import (
    FORMAT_ALIASES,
    CanonicalDocFormat,
    DocFormat,
    normalize_format,
)

__all__ = [
    "generate_html_docs",
    "generate_markdown_docs",
    "generate_rst_docs",
    "DocFormat",
    "CanonicalDocFormat",
    "FORMAT_ALIASES",
    "normalize_format",
]
