# This module defines functions to parse docstrings by guessing their style.

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, TypedDict

from griffe._internal.enumerations import Parser

if TYPE_CHECKING:
    from griffe._internal.docstrings.google import GoogleOptions
    from griffe._internal.docstrings.models import DocstringSection
    from griffe._internal.docstrings.numpy import NumpyOptions
    from griffe._internal.docstrings.parsers import DocstringStyle
    from griffe._internal.docstrings.sphinx import SphinxOptions
    from griffe._internal.models import Docstring


# This is not our preferred order, but the safest order for proper detection
# using heuristics. Indeed, Google style sections sometimes appear in otherwise
# plain markup docstrings, which could lead to false positives. Same for Numpy
# sections, whose syntax is regular rST markup, and which can therefore appear
# in plain markup docstrings too, even more often than Google sections.
_default_style_order = [Parser.sphinx, Parser.google, Parser.numpy]


DocstringDetectionMethod = Literal["heuristics", "max_sections"]
"""The supported methods to infer docstring styles."""


_patterns = {
    Parser.google: (
        r"\n[ \t]*{0}:([ \t]+.+)?\n[ \t]+.+",
        [
            "args",
            "arguments",
            "params",
            "parameters",
            "keyword args",
            "keyword arguments",
            "other args",
            "other arguments",
            "other params",
            "other parameters",
            "raises",
            "exceptions",
            "returns",
            "yields",
            "receives",
            "examples",
            "attributes",
            "functions",
            "methods",
            "classes",
            "modules",
            "warns",
            "warnings",
        ],
    ),
    Parser.numpy: (
        r"\n[ \t]*{0}\n[ \t]*---+\n",
        [
            "deprecated",
            "parameters",
            "other parameters",
            "returns",
            "yields",
            "receives",
            "raises",
            "warns",
            # "examples",
            "attributes",
            "functions",
            "methods",
            "classes",
            "modules",
        ],
    ),
    Parser.sphinx: (
        r"\n[ \t]*:{0}([ \t]+\w+)*:([ \t]+.+)?\n",
        [
            "param",
            "parameter",
            "arg",
            "argument",
            "key",
            "keyword",
            "type",
            "var",
            "ivar",
            "cvar",
            "vartype",
            "returns",
            "return",
            "rtype",
            "raises",
            "raise",
            "except",
            "exception",
        ],
    ),
}


class PerStyleOptions(TypedDict, total=False):
    """Per-style options for docstring parsing."""

    google: GoogleOptions
    """Options for Google-style docstrings."""
    numpy: NumpyOptions
    """Options for Numpy-style docstrings."""
    sphinx: SphinxOptions
    """Options for Sphinx-style docstrings."""


def infer_docstring_style(
    docstring: Docstring,
    *,
    method: DocstringDetectionMethod = "heuristics",
    style_order: list[Parser] | list[DocstringStyle] | None = None,
    default: Parser | DocstringStyle | None = None,
    per_style_options: PerStyleOptions | None = None,
) -> tuple[Parser | None, list[DocstringSection] | None]:
    """Infer the parser to use for the docstring.

    The 'heuristics' method uses regular expressions. The 'max_sections' method
    parses the docstring with all parsers specified in `style_order` and returns
    the one who parsed the most sections.

    If heuristics fail, the `default` parser is returned. If multiple parsers
    parsed the same number of sections, `style_order` is used to decide which
    one to return. The `default` parser is never used with the 'max_sections' method.

    Additional options are parsed to the detected parser, if any.

    Parameters:
        docstring: The docstring to parse.
        method: The method to use to infer the parser.
        style_order: The order of the styles to try when inferring the parser.
        default: The default parser to use if the inference fails.
        per_style_options: Additional parsing options per style.

    Returns:
        The inferred parser, and optionally parsed sections (when method is 'max_sections').
    """
    from griffe._internal.docstrings.parsers import parsers  # noqa: PLC0415

    per_style_options = per_style_options or {}  # ty:ignore[invalid-assignment]

    style_order = [Parser(style) if isinstance(style, str) else style for style in style_order or _default_style_order]

    if method == "heuristics":
        for style in style_order:
            pattern, replacements = _patterns[style]
            patterns = [
                re.compile(pattern.format(replacement), re.IGNORECASE | re.MULTILINE) for replacement in replacements
            ]
            if any(pattern.search(docstring.value) for pattern in patterns):
                return style, None
        return default if default is None or isinstance(default, Parser) else Parser(default), None

    if method == "max_sections":
        style_sections = {}
        for style in style_order:
            style_sections[style] = parsers[style](docstring, **per_style_options.get(style, {}))  # ty:ignore[unresolved-attribute]
        style_lengths = {style: len(section) for style, section in style_sections.items()}
        max_sections = max(style_lengths.values())
        for style in style_order:
            if style_lengths[style] == max_sections:
                return style, style_sections[style]

    raise ValueError(f"Invalid method '{method}'.")


class AutoOptions(TypedDict, total=False):
    """Options for Auto-style docstrings."""

    method: DocstringDetectionMethod
    """The method to use to infer the parser."""
    style_order: list[Parser] | list[DocstringStyle] | None
    """The order of styles to try when inferring the parser."""
    default: Parser | DocstringStyle | None
    """The default parser to use if the inference fails."""
    per_style_options: PerStyleOptions | None
    """Additional parsing options per style."""


def parse_auto(
    docstring: Docstring,
    *,
    method: DocstringDetectionMethod = "heuristics",
    style_order: list[Parser] | list[DocstringStyle] | None = None,
    default: Parser | DocstringStyle | None = None,
    per_style_options: PerStyleOptions | None = None,
) -> list[DocstringSection]:
    """Parse a docstring by automatically detecting the style it uses.

    See [`infer_docstring_style`][griffe.infer_docstring_style] for more information
    on the available parameters.

    Parameters:
        docstring: The docstring to parse.
        method: The method to use to infer the parser.
        style_order: The order of the styles to try when inferring the parser.
        default: The default parser to use if the inference fails.
        per_style_options: Additional parsing options per style.

    Returns:
        A list of docstring sections.
    """
    from griffe._internal.docstrings.parsers import parse  # noqa: PLC0415

    per_style_options = per_style_options or {}  # ty:ignore[invalid-assignment]

    style, sections = infer_docstring_style(
        docstring,
        method=method,
        style_order=style_order,
        default=default,
        per_style_options=per_style_options,
    )
    if sections is None:
        return parse(docstring, style, **per_style_options.get(style, {}))  # ty:ignore[no-matching-overload, unresolved-attribute]
    return sections
