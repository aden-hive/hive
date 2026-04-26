# This module defines functions to parse Sphinx docstrings into structured data.

# Credits to Patrick Lannigan ([@plannigan](https://github.com/plannigan))
# who originally added the parser in the [pytkdocs project](https://github.com/mkdocstrings/pytkdocs).
# See https://github.com/mkdocstrings/pytkdocs/pull/71.

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from inspect import cleandoc
from typing import TYPE_CHECKING, Any, TypedDict

from griffe._internal.docstrings.models import (
    DocstringAttribute,
    DocstringParameter,
    DocstringRaise,
    DocstringReturn,
    DocstringSection,
    DocstringSectionAttributes,
    DocstringSectionParameters,
    DocstringSectionRaises,
    DocstringSectionReturns,
    DocstringSectionText,
)
from griffe._internal.docstrings.utils import docstring_warning, parse_docstring_annotation

if TYPE_CHECKING:
    from collections.abc import Callable

    from griffe._internal.expressions import Expr
    from griffe._internal.models import Docstring


# TODO: Examples: from the documentation, we're not sure there is a standard format for examples
_PARAM_NAMES = frozenset(("param", "parameter", "arg", "argument", "key", "keyword"))
_PARAM_TYPE_NAMES = frozenset(("type",))
_ATTRIBUTE_NAMES = frozenset(("var", "ivar", "cvar"))
_ATTRIBUTE_TYPE_NAMES = frozenset(("vartype",))
_RETURN_NAMES = frozenset(("returns", "return"))
_RETURN_TYPE_NAMES = frozenset(("rtype",))
_EXCEPTION_NAMES = frozenset(("raises", "raise", "except", "exception"))


@dataclass(frozen=True)
class _FieldType:
    """Maps directive names to parser functions."""

    names: frozenset[str]
    reader: Callable[[Docstring, int, _ParsedValues], int]

    def matches(self, line: str) -> bool:
        """Check if a line matches the field type.

        Parameters:
            line: Line to check against

        Returns:
            True if the line matches the field type, False otherwise.
        """
        return any(line.startswith(f":{name}") for name in self.names)


@dataclass
class _ParsedDirective:
    """Directive information that has been parsed from a docstring."""

    line: str
    next_index: int
    directive_parts: list[str]
    value: str
    invalid: bool = False


@dataclass
class _ParsedValues:
    """Values parsed from the docstring to be used to produce sections."""

    description: list[str] = field(default_factory=list)
    parameters: dict[str, DocstringParameter] = field(default_factory=dict)
    param_types: dict[str, str | Expr] = field(default_factory=dict)
    attributes: dict[str, DocstringAttribute] = field(default_factory=dict)
    attribute_types: dict[str, str] = field(default_factory=dict)
    exceptions: list[DocstringRaise] = field(default_factory=list)
    return_value: DocstringReturn | None = None
    return_type: str | None = None


class SphinxOptions(TypedDict, total=False):
    """Options for parsing Sphinx-style docstrings."""

    warn_unknown_params: bool
    """Whether to warn about unknown parameters."""
    warnings: bool
    """Whether to issue warnings for parsing issues."""


def parse_sphinx(
    docstring: Docstring,
    *,
    warn_unknown_params: bool = True,
    warnings: bool = True,
) -> list[DocstringSection]:
    """Parse a Sphinx-style docstring.

    Parameters:
        docstring: The docstring to parse.
        warn_unknown_params: Warn about documented parameters not appearing in the signature.
        warnings: Whether to log warnings at all.

    Returns:
        A list of docstring sections.
    """
    parsed_values = _ParsedValues()

    options = {
        "warn_unknown_params": warn_unknown_params,
        "warnings": warnings,
    }

    lines = docstring.lines
    curr_line_index = 0

    while curr_line_index < len(lines):
        line = lines[curr_line_index]
        for field_type in _field_types:
            if field_type.matches(line):
                # https://github.com/python/mypy/issues/5485
                curr_line_index = field_type.reader(docstring, curr_line_index, parsed_values, **options)
                break
        else:
            parsed_values.description.append(line)

        curr_line_index += 1

    return _parsed_values_to_sections(parsed_values)


def _read_parameter(
    docstring: Docstring,
    offset: int,
    parsed_values: _ParsedValues,
    *,
    warn_unknown_params: bool = True,
    warnings: bool = True,
    **options: Any,  # noqa: ARG001
) -> int:
    parsed_directive = _parse_directive(docstring, offset, warnings=warnings)
    if parsed_directive.invalid:
        return parsed_directive.next_index

    directive_type = None
    if len(parsed_directive.directive_parts) == 2:  # noqa: PLR2004
        # no type info
        name = parsed_directive.directive_parts[1]
    elif len(parsed_directive.directive_parts) == 3:  # noqa: PLR2004
        directive_type = parse_docstring_annotation(
            parsed_directive.directive_parts[1],
            docstring,
        )
        name = parsed_directive.directive_parts[2]
    elif len(parsed_directive.directive_parts) > 3:  # noqa: PLR2004
        # Ignoring type info, only a type with a single word is valid
        # https://www.sphinx-doc.org/en/master/usage/domains/python.html#info-field-lists
        name = parsed_directive.directive_parts[-1]
        if warnings:
            docstring_warning(docstring, 0, f"Failed to parse field directive from '{parsed_directive.line}'")
    else:
        if warnings:
            docstring_warning(docstring, 0, f"Failed to parse field directive from '{parsed_directive.line}'")
        return parsed_directive.next_index

    if name in parsed_values.parameters:
        if warnings:
            docstring_warning(docstring, 0, f"Duplicate parameter entry for '{name}'")
        return parsed_directive.next_index

    if warnings and warn_unknown_params:
        with suppress(AttributeError):  # For Parameters sections in objects without parameters.
            params = docstring.parent.parameters  # ty:ignore[unresolved-attribute]
            if name not in params:
                message = f"Parameter '{name}' does not appear in the function signature"
                for starred_name in (f"*{name}", f"**{name}"):
                    if starred_name in params:
                        message += f". Did you mean '{starred_name}'?"
                        break
                docstring_warning(docstring, 0, message)

    annotation = _determine_param_annotation(docstring, name, directive_type, parsed_values, warnings=warnings)
    default = _determine_param_default(docstring, name)

    parsed_values.parameters[name] = DocstringParameter(
        name=name,
        annotation=annotation,
        description=parsed_directive.value,
        value=default,
    )

    return parsed_directive.next_index


def _determine_param_default(docstring: Docstring, name: str) -> str | None:
    try:
        return docstring.parent.parameters[name.lstrip()].default  # ty:ignore[unresolved-attribute]
    except (AttributeError, KeyError):
        return None


def _determine_param_annotation(
    docstring: Docstring,
    name: str,
    directive_type: str | Expr | None,
    parsed_values: _ParsedValues,
    *,
    warnings: bool = True,
) -> Any:
    # Annotation precedence:
    # - in-line directive type
    # - "type" directive type
    # - signature annotation
    # - none
    annotation: str | Expr | None = None

    parsed_param_type = parsed_values.param_types.get(name)
    if parsed_param_type is not None:
        annotation = parsed_param_type

    if directive_type is not None:
        annotation = directive_type

    if warnings and directive_type is not None and parsed_param_type is not None:
        docstring_warning(docstring, 0, f"Duplicate parameter information for '{name}'")

    if annotation is None:
        try:
            annotation = docstring.parent.parameters[name.lstrip()].annotation  # ty:ignore[unresolved-attribute]
        except (AttributeError, KeyError):
            if warnings:
                docstring_warning(docstring, 0, f"No matching parameter for '{name}'")

    return annotation


def _read_parameter_type(
    docstring: Docstring,
    offset: int,
    parsed_values: _ParsedValues,
    *,
    warnings: bool = True,
    **options: Any,  # noqa: ARG001
) -> int:
    parsed_directive = _parse_directive(docstring, offset, warnings=warnings)
    if parsed_directive.invalid:
        return parsed_directive.next_index
    param_type_str = _consolidate_descriptive_type(parsed_directive.value.strip())
    param_type = parse_docstring_annotation(param_type_str, docstring)

    if len(parsed_directive.directive_parts) == 2:  # noqa: PLR2004
        param_name = parsed_directive.directive_parts[1]
    else:
        if warnings:
            docstring_warning(docstring, 0, f"Failed to get parameter name from '{parsed_directive.line}'")
        return parsed_directive.next_index

    parsed_values.param_types[param_name] = param_type
    param = parsed_values.parameters.get(param_name)
    if param is not None:
        if param.annotation is None:
            param.annotation = param_type
        else:
            docstring_warning(docstring, 0, f"Duplicate parameter information for '{param_name}'")
    return parsed_directive.next_index


def _read_attribute(
    docstring: Docstring,
    offset: int,
    parsed_values: _ParsedValues,
    *,
    warnings: bool = True,
    **options: Any,  # noqa: ARG001
) -> int:
    parsed_directive = _parse_directive(docstring, offset, warnings=warnings)
    if parsed_directive.invalid:
        return parsed_directive.next_index

    if len(parsed_directive.directive_parts) == 2:  # noqa: PLR2004
        name = parsed_directive.directive_parts[1]
    else:
        if warnings:
            docstring_warning(docstring, 0, f"Failed to parse field directive from '{parsed_directive.line}'")
        return parsed_directive.next_index

    annotation: str | Expr | None = None

    # Annotation precedence:
    # - "vartype" directive type
    # - annotation in the parent
    # - none

    parsed_attribute_type = parsed_values.attribute_types.get(name)
    if parsed_attribute_type is not None:
        annotation = parsed_attribute_type
    else:
        # try to use the annotation from the parent
        with suppress(AttributeError, KeyError, TypeError):
            # Use subscript syntax to fetch annotation from inherited members too.
            annotation = docstring.parent[name].annotation  # ty:ignore[not-subscriptable]
    if name in parsed_values.attributes:
        if warnings:
            docstring_warning(docstring, 0, f"Duplicate attribute entry for '{name}'")
    else:
        parsed_values.attributes[name] = DocstringAttribute(
            name=name,
            annotation=annotation,
            description=parsed_directive.value,
        )

    return parsed_directive.next_index


def _read_attribute_type(
    docstring: Docstring,
    offset: int,
    parsed_values: _ParsedValues,
    *,
    warnings: bool = True,
    **options: Any,  # noqa: ARG001
) -> int:
    parsed_directive = _parse_directive(docstring, offset, warnings=warnings)
    if parsed_directive.invalid:
        return parsed_directive.next_index
    attribute_type = _consolidate_descriptive_type(parsed_directive.value.strip())

    if len(parsed_directive.directive_parts) == 2:  # noqa: PLR2004
        attribute_name = parsed_directive.directive_parts[1]
    else:
        if warnings:
            docstring_warning(docstring, 0, f"Failed to get attribute name from '{parsed_directive.line}'")
        return parsed_directive.next_index

    parsed_values.attribute_types[attribute_name] = attribute_type
    attribute = parsed_values.attributes.get(attribute_name)
    if attribute is not None:
        if attribute.annotation is None:
            attribute.annotation = attribute_type
        elif warnings:
            docstring_warning(docstring, 0, f"Duplicate attribute information for '{attribute_name}'")
    return parsed_directive.next_index


def _read_exception(
    docstring: Docstring,
    offset: int,
    parsed_values: _ParsedValues,
    *,
    warnings: bool = True,
    **options: Any,  # noqa: ARG001
) -> int:
    parsed_directive = _parse_directive(docstring, offset, warnings=warnings)
    if parsed_directive.invalid:
        return parsed_directive.next_index

    if len(parsed_directive.directive_parts) == 2:  # noqa: PLR2004
        ex_type = parsed_directive.directive_parts[1]
        parsed_values.exceptions.append(DocstringRaise(annotation=ex_type, description=parsed_directive.value))
    elif warnings:
        docstring_warning(docstring, 0, f"Failed to parse exception directive from '{parsed_directive.line}'")

    return parsed_directive.next_index


def _read_return(
    docstring: Docstring,
    offset: int,
    parsed_values: _ParsedValues,
    *,
    warn_missing_types: bool = True,
    warnings: bool = True,
    **options: Any,  # noqa: ARG001
) -> int:
    parsed_directive = _parse_directive(docstring, offset, warnings=warnings)
    if parsed_directive.invalid:
        return parsed_directive.next_index

    # Annotation precedence:
    # - "rtype" directive type
    # - signature annotation
    # - None
    annotation: str | Expr | None
    if parsed_values.return_type is not None:
        annotation = parsed_values.return_type
    else:
        try:
            annotation = docstring.parent.annotation  # ty:ignore[unresolved-attribute]
        except AttributeError:
            if warnings and warn_missing_types:
                docstring_warning(docstring, 0, f"No return type or annotation at '{parsed_directive.line}'")
            annotation = None

    # TODO: maybe support names
    parsed_values.return_value = DocstringReturn(name="", annotation=annotation, description=parsed_directive.value)

    return parsed_directive.next_index


def _read_return_type(
    docstring: Docstring,
    offset: int,
    parsed_values: _ParsedValues,
    *,
    warnings: bool = True,
    **options: Any,  # noqa: ARG001
) -> int:
    parsed_directive = _parse_directive(docstring, offset, warnings=warnings)
    if parsed_directive.invalid:
        return parsed_directive.next_index

    return_type = _consolidate_descriptive_type(parsed_directive.value.strip())
    parsed_values.return_type = return_type
    return_value = parsed_values.return_value
    if return_value is not None:
        return_value.annotation = return_type

    return parsed_directive.next_index


def _parsed_values_to_sections(parsed_values: _ParsedValues) -> list[DocstringSection]:
    text = "\n".join(_strip_blank_lines(parsed_values.description))
    result: list[DocstringSection] = [DocstringSectionText(text)]
    if parsed_values.parameters:
        param_values = list(parsed_values.parameters.values())
        result.append(DocstringSectionParameters(param_values))
    if parsed_values.attributes:
        attribute_values = list(parsed_values.attributes.values())
        result.append(DocstringSectionAttributes(attribute_values))
    if parsed_values.return_value is not None:
        result.append(DocstringSectionReturns([parsed_values.return_value]))
    if parsed_values.exceptions:
        result.append(DocstringSectionRaises(parsed_values.exceptions))
    return result


def _parse_directive(docstring: Docstring, offset: int, *, warnings: bool = True) -> _ParsedDirective:
    line, next_index = _consolidate_continuation_lines(docstring.lines, offset)
    try:
        _, directive, value = line.split(":", 2)
    except ValueError:
        if warnings:
            docstring_warning(docstring, 0, f"Failed to get ':directive: value' pair from '{line}'")
        return _ParsedDirective(line, next_index, [], "", invalid=True)

    value = value.strip()
    return _ParsedDirective(line, next_index, directive.split(" "), value)


def _consolidate_continuation_lines(lines: list[str], offset: int) -> tuple[str, int]:
    curr_line_index = offset
    block = [lines[curr_line_index].lstrip()]

    # start processing after first item
    curr_line_index += 1
    while curr_line_index < len(lines) and not lines[curr_line_index].startswith(":"):
        block.append(lines[curr_line_index])
        curr_line_index += 1

    return cleandoc("\n".join(block)).rstrip("\n"), curr_line_index - 1


def _consolidate_descriptive_type(descriptive_type: str) -> str:
    return descriptive_type.replace(" or ", " | ")


def _strip_blank_lines(lines: list[str]) -> list[str]:
    if not lines:
        return lines

    # remove blank lines from the start and end
    content_found = False
    initial_content = 0
    final_content = 0
    for index, line in enumerate(lines):
        if not line or line.isspace():
            if not content_found:
                initial_content += 1
        else:
            content_found = True
            final_content = index
    return lines[initial_content : final_content + 1]


_field_types = [
    _FieldType(_PARAM_TYPE_NAMES, _read_parameter_type),
    _FieldType(_PARAM_NAMES, _read_parameter),
    _FieldType(_ATTRIBUTE_TYPE_NAMES, _read_attribute_type),
    _FieldType(_ATTRIBUTE_NAMES, _read_attribute),
    _FieldType(_EXCEPTION_NAMES, _read_exception),
    _FieldType(_RETURN_NAMES, _read_return),
    _FieldType(_RETURN_TYPE_NAMES, _read_return_type),
]
