# This module imports all the defined parsers
# and provides a generic function to parse docstrings.

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from griffe._internal.docstrings.auto import AutoOptions, parse_auto
from griffe._internal.docstrings.google import GoogleOptions, parse_google
from griffe._internal.docstrings.models import DocstringSection, DocstringSectionText
from griffe._internal.docstrings.numpy import NumpyOptions, parse_numpy
from griffe._internal.docstrings.sphinx import SphinxOptions, parse_sphinx
from griffe._internal.enumerations import Parser

if TYPE_CHECKING:
    from collections.abc import Callable

    from griffe._internal.models import Docstring


DocstringStyle = Literal["google", "numpy", "sphinx", "auto"]
"""The supported docstring styles (literal values of the Parser enumeration)."""
DocstringOptions = GoogleOptions | NumpyOptions | SphinxOptions | AutoOptions
"""The options for each docstring style."""


parsers: dict[Parser, Callable[[Docstring], list[DocstringSection]]] = {
    Parser.auto: parse_auto,
    Parser.google: parse_google,
    Parser.sphinx: parse_sphinx,
    Parser.numpy: parse_numpy,
}


def parse(
    docstring: Docstring,
    parser: DocstringStyle | Parser | None,
    **options: Any,
) -> list[DocstringSection]:
    """Parse the docstring.

    Parameters:
        docstring: The docstring to parse.
        parser: The docstring parser to use. If None, return a single text section.
        **options: The options accepted by the parser.

    Returns:
        A list of docstring sections.
    """
    if parser:
        if not isinstance(parser, Parser):
            parser = Parser(parser)
        return parsers[parser](docstring, **options)
    return [DocstringSectionText(docstring.value)] if docstring.value else []
