# This module defines functions to parse Google-style docstrings into structured data.

from __future__ import annotations

import re
from contextlib import suppress
from typing import TYPE_CHECKING, TypedDict

from griffe._internal.docstrings.models import (
    DocstringAttribute,
    DocstringClass,
    DocstringFunction,
    DocstringModule,
    DocstringParameter,
    DocstringRaise,
    DocstringReceive,
    DocstringReturn,
    DocstringSection,
    DocstringSectionAdmonition,
    DocstringSectionAttributes,
    DocstringSectionClasses,
    DocstringSectionExamples,
    DocstringSectionFunctions,
    DocstringSectionModules,
    DocstringSectionOtherParameters,
    DocstringSectionParameters,
    DocstringSectionRaises,
    DocstringSectionReceives,
    DocstringSectionReturns,
    DocstringSectionText,
    DocstringSectionTypeAliases,
    DocstringSectionTypeParameters,
    DocstringSectionWarns,
    DocstringSectionYields,
    DocstringTypeAlias,
    DocstringTypeParameter,
    DocstringWarn,
    DocstringYield,
)
from griffe._internal.docstrings.utils import docstring_warning, parse_docstring_annotation
from griffe._internal.enumerations import DocstringSectionKind, LogLevel

if TYPE_CHECKING:
    from re import Pattern
    from typing import Any, Literal

    from griffe._internal.expressions import Expr
    from griffe._internal.models import Docstring


_section_kind = {
    "args": DocstringSectionKind.parameters,
    "arguments": DocstringSectionKind.parameters,
    "params": DocstringSectionKind.parameters,
    "parameters": DocstringSectionKind.parameters,
    "keyword args": DocstringSectionKind.other_parameters,
    "keyword arguments": DocstringSectionKind.other_parameters,
    "other args": DocstringSectionKind.other_parameters,
    "other arguments": DocstringSectionKind.other_parameters,
    "other params": DocstringSectionKind.other_parameters,
    "other parameters": DocstringSectionKind.other_parameters,
    "type args": DocstringSectionKind.type_parameters,
    "type arguments": DocstringSectionKind.type_parameters,
    "type params": DocstringSectionKind.type_parameters,
    "type parameters": DocstringSectionKind.type_parameters,
    "raises": DocstringSectionKind.raises,
    "exceptions": DocstringSectionKind.raises,
    "returns": DocstringSectionKind.returns,
    "yields": DocstringSectionKind.yields,
    "receives": DocstringSectionKind.receives,
    "examples": DocstringSectionKind.examples,
    "attributes": DocstringSectionKind.attributes,
    "functions": DocstringSectionKind.functions,
    "methods": DocstringSectionKind.functions,
    "classes": DocstringSectionKind.classes,
    "type aliases": DocstringSectionKind.type_aliases,
    "modules": DocstringSectionKind.modules,
    "warns": DocstringSectionKind.warns,
    "warnings": DocstringSectionKind.warns,
}

_BlockItem = tuple[int, list[str]]
_BlockItems = list[_BlockItem]
_ItemsBlock = tuple[_BlockItems, int]

_RE_ADMONITION: Pattern = re.compile(r"^(?P<type>[\w][\s\w-]*):(\s+(?P<title>[^\s].*))?\s*$", re.IGNORECASE)
_RE_NAME_ANNOTATION_DESCRIPTION: Pattern = re.compile(r"^(?:(?P<name>\w+)?\s*(?:\((?P<type>.+)\))?:\s*)?(?P<desc>.*)$")
_RE_DOCTEST_BLANKLINE: Pattern = re.compile(r"^\s*<BLANKLINE>\s*$")
_RE_DOCTEST_FLAGS: Pattern = re.compile(r"(\s*#\s*doctest:.+)$")


def _read_block_items(docstring: Docstring, *, offset: int, warnings: bool = True, **options: Any) -> _ItemsBlock:  # noqa: ARG001
    lines = docstring.lines
    if offset >= len(lines):
        return [], offset

    new_offset = offset
    items: _BlockItems = []

    # Skip first empty lines.
    while _is_empty_line(lines[new_offset]):
        new_offset += 1

    # Get initial indent.
    indent = len(lines[new_offset]) - len(lines[new_offset].lstrip())

    if indent == 0:
        # First non-empty line was not indented, abort.
        return [], new_offset - 1

    # Start processing first item.
    current_item = (new_offset, [lines[new_offset][indent:]])
    new_offset += 1

    # Loop on next lines.
    while new_offset < len(lines):
        line = lines[new_offset]

        if _is_empty_line(line):
            # Empty line: preserve it in the current item.
            current_item[1].append("")

        elif line.startswith(indent * 2 * " "):
            # Continuation line.
            current_item[1].append(line[indent * 2 :])

        elif line.startswith((indent + 1) * " "):
            # Indent between initial and continuation: append but warn.
            cont_indent = len(line) - len(line.lstrip())
            current_item[1].append(line[cont_indent:])
            if warnings:
                docstring_warning(
                    docstring,
                    new_offset,
                    f"Confusing indentation for continuation line {new_offset + 1} in docstring, "
                    f"should be {indent} * 2 = {indent * 2} spaces, not {cont_indent}",
                )

        elif line.startswith(indent * " "):
            # Indent equal to initial one: new item.
            items.append(current_item)
            current_item = (new_offset, [line[indent:]])

        else:
            # Indent lower than initial one: end of section.
            break

        new_offset += 1

    if current_item:
        items.append(current_item)

    return items, new_offset - 1


def _read_block(docstring: Docstring, *, offset: int, **options: Any) -> tuple[str, int]:  # noqa: ARG001
    lines = docstring.lines
    if offset >= len(lines):
        return "", offset - 1

    new_offset = offset
    block: list[str] = []

    # skip first empty lines.
    while _is_empty_line(lines[new_offset]):
        new_offset += 1

    # Get initial indent.
    indent = len(lines[new_offset]) - len(lines[new_offset].lstrip())

    if indent == 0:
        # First non-empty line was not indented, abort.
        return "", offset - 1

    # Start processing first item.
    block.append(lines[new_offset].lstrip())
    new_offset += 1

    # Loop on next lines.
    while new_offset < len(lines) and (lines[new_offset].startswith(indent * " ") or _is_empty_line(lines[new_offset])):
        block.append(lines[new_offset][indent:])
        new_offset += 1

    return "\n".join(block).rstrip("\n"), new_offset - 1


def _read_parameters(
    docstring: Docstring,
    *,
    offset: int,
    warn_unknown_params: bool = True,
    warn_missing_types: bool = True,
    warnings: bool = True,
    **options: Any,
) -> tuple[list[DocstringParameter], int]:
    parameters = []
    annotation: str | Expr | None

    block, new_offset = _read_block_items(docstring, offset=offset, warnings=warnings, **options)

    # TODO: Use `get_name_annotation_description` here too?
    for line_number, param_lines in block:
        # Check the presence of a name and description, separated by a colon.
        try:
            name_with_type, description = param_lines[0].split(":", 1)
        except ValueError:
            if warnings:
                docstring_warning(
                    docstring,
                    line_number,
                    f"Failed to get 'name: description' pair from '{param_lines[0]}'",
                )
            continue

        description = "\n".join([description.lstrip(), *param_lines[1:]]).rstrip("\n")

        # Use the type given after the parameter name, if any.
        if "(" in name_with_type and name_with_type.endswith(")"):
            name, annotation = name_with_type.split("(", 1)
            name = name.strip()
            annotation = annotation.removesuffix(")").removesuffix(", optional").strip()
            # Try to compile the annotation to transform it into an expression.
            annotation = parse_docstring_annotation(annotation, docstring)
        else:
            name = name_with_type
            # Try to use the annotation from the signature.
            try:
                annotation = docstring.parent.parameters[name].annotation  # ty:ignore[unresolved-attribute]
            except (AttributeError, KeyError):
                annotation = None

        try:
            default = docstring.parent.parameters[name].default  # ty:ignore[unresolved-attribute]
        except (AttributeError, KeyError):
            default = None

        if warnings and warn_missing_types and annotation is None:
            docstring_warning(docstring, line_number, f"No type or annotation for parameter '{name}'")

        if warnings and warn_unknown_params:
            with suppress(AttributeError):  # For Parameters sections in objects without parameters.
                params = docstring.parent.parameters  # ty:ignore[unresolved-attribute]
                if name not in params:
                    message = f"Parameter '{name}' does not appear in the function signature"
                    for starred_name in (f"*{name}", f"**{name}"):
                        if starred_name in params:
                            message += f". Did you mean '{starred_name}'?"
                            break
                    docstring_warning(docstring, line_number, message)

        parameters.append(DocstringParameter(name=name, value=default, annotation=annotation, description=description))

    return parameters, new_offset


def _read_parameters_section(
    docstring: Docstring,
    *,
    offset: int,
    **options: Any,
) -> tuple[DocstringSectionParameters | None, int]:
    parameters, new_offset = _read_parameters(docstring, offset=offset, **options)
    return DocstringSectionParameters(parameters), new_offset


def _read_other_parameters_section(
    docstring: Docstring,
    *,
    offset: int,
    warn_unknown_params: bool = True,  # noqa: ARG001
    **options: Any,
) -> tuple[DocstringSectionOtherParameters | None, int]:
    parameters, new_offset = _read_parameters(docstring, offset=offset, warn_unknown_params=False, **options)
    return DocstringSectionOtherParameters(parameters), new_offset


def _read_type_parameters_section(
    docstring: Docstring,
    *,
    offset: int,
    warn_unknown_params: bool = True,
    **options: Any,
) -> tuple[DocstringSectionTypeParameters | None, int]:
    type_parameters = []
    bound: str | Expr | None

    block, new_offset = _read_block_items(docstring, offset=offset, **options)

    for line_number, type_param_lines in block:
        # check the presence of a name and description, separated by a colon
        try:
            name_with_bound, description = type_param_lines[0].split(":", 1)
        except ValueError:
            docstring_warning(
                docstring,
                line_number,
                f"Failed to get 'name: description' pair from '{type_param_lines[0]}'",
            )
            continue

        description = "\n".join([description.lstrip(), *type_param_lines[1:]]).rstrip("\n")

        # use the type given after the type parameter name, if any
        if " " in name_with_bound:
            name, bound = name_with_bound.split(" ", 1)
            if bound.startswith("(") and bound.endswith(")"):
                bound = bound[1:-1]
            # try to compile the annotation to transform it into an expression
            bound = parse_docstring_annotation(bound, docstring)
        else:
            name = name_with_bound
            # try to use the annotation from the signature
            try:
                bound = docstring.parent.type_parameters[name].annotation  # ty:ignore[unresolved-attribute]
            except (AttributeError, KeyError):
                bound = None

        try:
            default = docstring.parent.type_parameters[name].default  # ty:ignore[unresolved-attribute]
        except (AttributeError, KeyError):
            default = None

        if warn_unknown_params:
            with suppress(AttributeError):  # for type parameters sections in objects without type parameters
                type_params = docstring.parent.type_parameters  # ty:ignore[unresolved-attribute]
                if name not in type_params:
                    message = f"Type parameter '{name}' does not appear in the {docstring.parent.kind.value} signature"  # ty:ignore[unresolved-attribute]
                    for starred_name in (f"*{name}", f"**{name}"):
                        if starred_name in type_params:
                            message += f". Did you mean '{starred_name}'?"
                            break
                    docstring_warning(docstring, line_number, message)

        type_parameters.append(
            DocstringTypeParameter(
                name=name,
                value=default,
                annotation=bound,
                description=description,
            ),
        )

    return DocstringSectionTypeParameters(type_parameters), new_offset


def _read_attributes_section(
    docstring: Docstring,
    *,
    offset: int,
    warnings: bool = True,
    **options: Any,
) -> tuple[DocstringSectionAttributes | None, int]:
    attributes = []
    block, new_offset = _read_block_items(docstring, offset=offset, warnings=warnings, **options)

    annotation: str | Expr | None = None
    for line_number, attr_lines in block:
        try:
            name_with_type, description = attr_lines[0].split(":", 1)
        except ValueError:
            if warnings:
                docstring_warning(
                    docstring,
                    line_number,
                    f"Failed to get 'name: description' pair from '{attr_lines[0]}'",
                )
            continue

        description = "\n".join([description.lstrip(), *attr_lines[1:]]).rstrip("\n")

        if " " in name_with_type:
            name, annotation = name_with_type.split(" ", 1)
            annotation = annotation.strip("()")
            annotation = annotation.removesuffix(", optional")
            # Try to compile the annotation to transform it into an expression.
            annotation = parse_docstring_annotation(annotation, docstring)
        else:
            name = name_with_type
            with suppress(AttributeError, KeyError, TypeError):
                # Use subscript syntax to fetch annotation from inherited members too.
                annotation = docstring.parent[name].annotation  # ty:ignore[not-subscriptable]

        attributes.append(DocstringAttribute(name=name, annotation=annotation, description=description))

    return DocstringSectionAttributes(attributes), new_offset


def _read_functions_section(
    docstring: Docstring,
    *,
    offset: int,
    warnings: bool = True,
    **options: Any,
) -> tuple[DocstringSectionFunctions | None, int]:
    functions = []
    block, new_offset = _read_block_items(docstring, offset=offset, warnings=warnings, **options)

    signature: str | Expr | None = None
    for line_number, func_lines in block:
        try:
            name_with_signature, description = func_lines[0].split(":", 1)
        except ValueError:
            if warnings:
                docstring_warning(
                    docstring,
                    line_number,
                    f"Failed to get 'signature: description' pair from '{func_lines[0]}'",
                )
            continue

        description = "\n".join([description.lstrip(), *func_lines[1:]]).rstrip("\n")

        if "(" in name_with_signature:
            name = name_with_signature.split("(", 1)[0]
            signature = name_with_signature
        else:
            name = name_with_signature
            signature = None

        functions.append(DocstringFunction(name=name, annotation=signature, description=description))

    return DocstringSectionFunctions(functions), new_offset


def _read_classes_section(
    docstring: Docstring,
    *,
    offset: int,
    warnings: bool = True,
    **options: Any,
) -> tuple[DocstringSectionClasses | None, int]:
    classes = []
    block, new_offset = _read_block_items(docstring, offset=offset, warnings=warnings, **options)

    signature: str | Expr | None = None
    for line_number, class_lines in block:
        try:
            name_with_signature, description = class_lines[0].split(":", 1)
        except ValueError:
            if warnings:
                docstring_warning(
                    docstring,
                    line_number,
                    f"Failed to get 'signature: description' pair from '{class_lines[0]}'",
                )
            continue

        description = "\n".join([description.lstrip(), *class_lines[1:]]).rstrip("\n")

        if "(" in name_with_signature:
            name = name_with_signature.split("(", 1)[0]
            signature = name_with_signature
        else:
            name = name_with_signature
            signature = None

        classes.append(DocstringClass(name=name, annotation=signature, description=description))

    return DocstringSectionClasses(classes), new_offset


def _read_type_aliases_section(
    docstring: Docstring,
    *,
    offset: int,
    **options: Any,
) -> tuple[DocstringSectionTypeAliases | None, int]:
    type_aliases = []
    block, new_offset = _read_block_items(docstring, offset=offset, **options)

    for line_number, type_alias_lines in block:
        try:
            name, description = type_alias_lines[0].split(":", 1)
        except ValueError:
            docstring_warning(
                docstring,
                line_number,
                f"Failed to get 'name: description' pair from '{type_alias_lines[0]}'",
            )
            continue
        description = "\n".join([description.lstrip(), *type_alias_lines[1:]]).rstrip("\n")
        type_aliases.append(DocstringTypeAlias(name=name, description=description))

    return DocstringSectionTypeAliases(type_aliases), new_offset


def _read_modules_section(
    docstring: Docstring,
    *,
    offset: int,
    warnings: bool = True,
    **options: Any,
) -> tuple[DocstringSectionModules | None, int]:
    modules = []
    block, new_offset = _read_block_items(docstring, offset=offset, warnings=warnings, **options)

    for line_number, module_lines in block:
        try:
            name, description = module_lines[0].split(":", 1)
        except ValueError:
            if warnings:
                docstring_warning(
                    docstring,
                    line_number,
                    f"Failed to get 'name: description' pair from '{module_lines[0]}'",
                )
            continue

        description = "\n".join([description.lstrip(), *module_lines[1:]]).rstrip("\n")
        modules.append(DocstringModule(name=name, description=description))

    return DocstringSectionModules(modules), new_offset


def _read_raises_section(
    docstring: Docstring,
    *,
    offset: int,
    warnings: bool = True,
    **options: Any,
) -> tuple[DocstringSectionRaises | None, int]:
    exceptions = []
    block, new_offset = _read_block_items(docstring, offset=offset, warnings=warnings, **options)

    annotation: str | Expr
    for line_number, exception_lines in block:
        try:
            annotation, description = exception_lines[0].split(":", 1)
        except ValueError:
            if warnings:
                docstring_warning(
                    docstring,
                    line_number,
                    f"Failed to get 'exception: description' pair from '{exception_lines[0]}'",
                )
            continue

        description = "\n".join([description.lstrip(), *exception_lines[1:]]).rstrip("\n")
        # Try to compile the annotation to transform it into an expression.
        annotation = parse_docstring_annotation(annotation, docstring)
        exceptions.append(DocstringRaise(annotation=annotation, description=description))

    return DocstringSectionRaises(exceptions), new_offset


def _read_warns_section(
    docstring: Docstring,
    *,
    offset: int,
    warnings: bool = True,
    **options: Any,
) -> tuple[DocstringSectionWarns | None, int]:
    warns = []
    block, new_offset = _read_block_items(docstring, offset=offset, warnings=warnings, **options)

    for line_number, warning_lines in block:
        try:
            annotation, description = warning_lines[0].split(":", 1)
        except ValueError:
            if warnings:
                docstring_warning(
                    docstring,
                    line_number,
                    f"Failed to get 'warning: description' pair from '{warning_lines[0]}'",
                )
            continue

        description = "\n".join([description.lstrip(), *warning_lines[1:]]).rstrip("\n")
        warns.append(DocstringWarn(annotation=annotation, description=description))

    return DocstringSectionWarns(warns), new_offset


def _read_block_items_maybe(
    docstring: Docstring,
    *,
    offset: int,
    multiple: bool = True,
    **options: Any,
) -> _ItemsBlock:
    if multiple:
        return _read_block_items(docstring, offset=offset, **options)
    one_block, new_offset = _read_block(docstring, offset=offset, **options)
    return [(new_offset, one_block.splitlines())], new_offset


def _get_name_annotation_description(
    docstring: Docstring,
    line_number: int,
    lines: list[str],
    *,
    named: bool = True,
    warnings: bool = True,
) -> tuple[str | None, Any, str]:
    if named:
        match = _RE_NAME_ANNOTATION_DESCRIPTION.match(lines[0])
        if not match:
            if warnings:
                docstring_warning(
                    docstring,
                    line_number,
                    f"Failed to get name, annotation or description from '{lines[0]}'",
                )
            raise ValueError
        name, annotation, description = match.groups()
    else:
        name = None
        if ":" in lines[0]:
            annotation, description = lines[0].split(":", 1)
            annotation = annotation.lstrip("(").rstrip(")")
        else:
            annotation = None
            description = lines[0]
    description = "\n".join([description.lstrip(), *lines[1:]]).rstrip("\n")
    return name, annotation, description


def _annotation_from_parent(
    docstring: Docstring,
    *,
    gen_index: Literal[0, 1, 2],
    multiple: bool = False,
    index: int = 0,
) -> str | Expr | None:
    annotation = None
    with suppress(Exception):
        annotation = docstring.parent.annotation  # ty:ignore[unresolved-attribute]
        if annotation.is_generator:
            annotation = annotation.slice.elements[gen_index]
        elif annotation.is_iterator and gen_index == 0:
            annotation = annotation.slice
        if multiple and annotation.is_tuple:
            annotation = annotation.slice.elements[index]
    return annotation


def _read_returns_section(
    docstring: Docstring,
    *,
    offset: int,
    returns_multiple_items: bool = True,
    returns_named_value: bool = True,
    warn_missing_types: bool = True,
    warnings: bool = True,
    **options: Any,
) -> tuple[DocstringSectionReturns | None, int]:
    returns = []

    block, new_offset = _read_block_items_maybe(
        docstring,
        offset=offset,
        multiple=returns_multiple_items,
        **options,
    )

    for index, (line_number, return_lines) in enumerate(block):
        try:
            name, annotation, description = _get_name_annotation_description(
                docstring,
                line_number,
                return_lines,
                named=returns_named_value,
            )
        except ValueError:
            continue

        if annotation:
            # Try to compile the annotation to transform it into an expression.
            annotation = parse_docstring_annotation(annotation, docstring)
        else:
            # Try to retrieve the annotation from the docstring parent.
            annotation = _annotation_from_parent(docstring, gen_index=2, multiple=len(block) > 1, index=index)

            if warnings and warn_missing_types and annotation is None:
                returned_value = repr(name) if name else index + 1
                docstring_warning(docstring, line_number, f"No type or annotation for returned value {returned_value}")

        returns.append(DocstringReturn(name=name or "", annotation=annotation, description=description))

    return DocstringSectionReturns(returns), new_offset


def _read_yields_section(
    docstring: Docstring,
    *,
    offset: int,
    returns_multiple_items: bool = True,
    returns_named_value: bool = True,
    warn_missing_types: bool = True,
    warnings: bool = True,
    **options: Any,
) -> tuple[DocstringSectionYields | None, int]:
    yields = []

    block, new_offset = _read_block_items_maybe(
        docstring,
        offset=offset,
        multiple=returns_multiple_items,
        **options,
    )

    for index, (line_number, yield_lines) in enumerate(block):
        try:
            name, annotation, description = _get_name_annotation_description(
                docstring,
                line_number,
                yield_lines,
                named=returns_named_value,
            )
        except ValueError:
            continue

        if annotation:
            # Try to compile the annotation to transform it into an expression.
            annotation = parse_docstring_annotation(annotation, docstring)
        else:
            # Try to retrieve the annotation from the docstring parent.
            annotation = _annotation_from_parent(docstring, gen_index=0, multiple=len(block) > 1, index=index)

            if warnings and warn_missing_types and annotation is None:
                yielded_value = repr(name) if name else index + 1
                docstring_warning(docstring, line_number, f"No type or annotation for yielded value {yielded_value}")

        yields.append(DocstringYield(name=name or "", annotation=annotation, description=description))

    return DocstringSectionYields(yields), new_offset


def _read_receives_section(
    docstring: Docstring,
    *,
    offset: int,
    receives_multiple_items: bool = True,
    receives_named_value: bool = True,
    warn_missing_types: bool = True,
    warnings: bool = True,
    **options: Any,
) -> tuple[DocstringSectionReceives | None, int]:
    receives = []

    block, new_offset = _read_block_items_maybe(
        docstring,
        offset=offset,
        multiple=receives_multiple_items,
        **options,
    )

    for index, (line_number, receive_lines) in enumerate(block):
        try:
            name, annotation, description = _get_name_annotation_description(
                docstring,
                line_number,
                receive_lines,
                named=receives_named_value,
            )
        except ValueError:
            continue

        if annotation:
            # Try to compile the annotation to transform it into an expression.
            annotation = parse_docstring_annotation(annotation, docstring)
        else:
            # Try to retrieve the annotation from the docstring parent.
            annotation = _annotation_from_parent(docstring, gen_index=1, multiple=len(block) > 1, index=index)

        if warnings and warn_missing_types and annotation is None:
            received_value = repr(name) if name else index + 1
            docstring_warning(docstring, line_number, f"No type or annotation for received value {received_value}")

        receives.append(DocstringReceive(name=name or "", annotation=annotation, description=description))

    return DocstringSectionReceives(receives), new_offset


def _read_examples_section(
    docstring: Docstring,
    *,
    offset: int,
    trim_doctest_flags: bool = True,
    **options: Any,
) -> tuple[DocstringSectionExamples | None, int]:
    text, new_offset = _read_block(docstring, offset=offset, **options)

    sub_sections: list[tuple[Literal[DocstringSectionKind.text, DocstringSectionKind.examples], str]] = []
    in_code_example = False
    in_code_block = False
    current_text: list[str] = []
    current_example: list[str] = []

    for line in text.split("\n"):
        if _is_empty_line(line):
            if in_code_example:
                if current_example:
                    sub_sections.append((DocstringSectionKind.examples, "\n".join(current_example)))
                    current_example = []
                in_code_example = False
            else:
                current_text.append(line)

        elif in_code_example:
            if trim_doctest_flags:
                line = _RE_DOCTEST_FLAGS.sub("", line)  # noqa: PLW2901
                line = _RE_DOCTEST_BLANKLINE.sub("", line)  # noqa: PLW2901
            current_example.append(line)

        elif line.startswith("```"):
            in_code_block = not in_code_block
            current_text.append(line)

        elif in_code_block:
            current_text.append(line)

        elif line.startswith(">>>"):
            if current_text:
                sub_sections.append((DocstringSectionKind.text, "\n".join(current_text).rstrip("\n")))
                current_text = []
            in_code_example = True

            if trim_doctest_flags:
                line = _RE_DOCTEST_FLAGS.sub("", line)  # noqa: PLW2901
            current_example.append(line)

        else:
            current_text.append(line)

    if current_text:
        sub_sections.append((DocstringSectionKind.text, "\n".join(current_text).rstrip("\n")))
    elif current_example:
        sub_sections.append((DocstringSectionKind.examples, "\n".join(current_example)))

    return DocstringSectionExamples(sub_sections), new_offset


def _is_empty_line(line: str) -> bool:
    return not line.strip()


_section_reader = {
    DocstringSectionKind.parameters: _read_parameters_section,
    DocstringSectionKind.other_parameters: _read_other_parameters_section,
    DocstringSectionKind.type_parameters: _read_type_parameters_section,
    DocstringSectionKind.raises: _read_raises_section,
    DocstringSectionKind.warns: _read_warns_section,
    DocstringSectionKind.examples: _read_examples_section,
    DocstringSectionKind.attributes: _read_attributes_section,
    DocstringSectionKind.functions: _read_functions_section,
    DocstringSectionKind.classes: _read_classes_section,
    DocstringSectionKind.type_aliases: _read_type_aliases_section,
    DocstringSectionKind.modules: _read_modules_section,
    DocstringSectionKind.returns: _read_returns_section,
    DocstringSectionKind.yields: _read_yields_section,
    DocstringSectionKind.receives: _read_receives_section,
}


class GoogleOptions(TypedDict, total=False):
    """Options for parsing Google-style docstrings."""

    ignore_init_summary: bool
    """Whether to ignore the summary in `__init__` methods' docstrings."""
    trim_doctest_flags: bool
    """Whether to remove doctest flags from Python example blocks."""
    returns_multiple_items: bool
    """Whether to parse multiple items in `Yields` and `Returns` sections."""
    returns_named_value: bool
    """Whether to parse `Yields` and `Returns` section items as name and description, rather than type and description."""
    returns_type_in_property_summary: bool
    """Whether to parse the return type of properties at the beginning of their summary."""
    receives_multiple_items: bool
    """Whether to parse multiple items in `Receives` sections."""
    receives_named_value: bool
    """Whether to parse `Receives` section items as name and description, rather than type and description."""
    warn_unknown_params: bool
    """Whether to warn about unknown parameters."""
    warn_missing_types: bool
    """Whether to warn about missing types/annotations for parameters, return values, etc."""
    warnings: bool
    """Whether to issue warnings for parsing issues."""


def parse_google(
    docstring: Docstring,
    *,
    ignore_init_summary: bool = False,
    trim_doctest_flags: bool = True,
    returns_multiple_items: bool = True,
    returns_named_value: bool = True,
    returns_type_in_property_summary: bool = False,
    receives_multiple_items: bool = True,
    receives_named_value: bool = True,
    warn_unknown_params: bool = True,
    warn_missing_types: bool = True,
    warnings: bool = True,
) -> list[DocstringSection]:
    """Parse a Google-style docstring.

    This function iterates on lines of a docstring to build sections.
    It then returns this list of sections.

    Parameters:
        docstring: The docstring to parse.
        ignore_init_summary: Whether to ignore the summary in `__init__` methods' docstrings.
        trim_doctest_flags: Whether to remove doctest flags from Python example blocks.
        returns_multiple_items: Whether to parse multiple items in `Yields` and `Returns` sections.
            When true, each item's continuation lines must be indented.
            When false (single item), no further indentation is required.
        returns_named_value: Whether to parse `Yields` and `Returns` section items as name and description, rather than type and description.
            When true, type must be wrapped in parentheses: `(int): Description.`. Names are optional: `name (int): Description.`.
            When false, parentheses are optional but the items cannot be named: `int: Description`.
        receives_multiple_items: Whether to parse multiple items in `Receives` sections.
            When true, each item's continuation lines must be indented.
            When false (single item), no further indentation is required.
        receives_named_value: Whether to parse `Receives` section items as name and description, rather than type and description.
            When true, type must be wrapped in parentheses: `(int): Description.`. Names are optional: `name (int): Description.`.
            When false, parentheses are optional but the items cannot be named: `int: Description`.
        returns_type_in_property_summary: Whether to parse the return type of properties
            at the beginning of their summary: `str: Summary of the property`.
        warn_unknown_params: Warn about documented parameters not appearing in the signature.
        warn_missing_types: Warn about missing types/annotations for parameters, return values, etc.
        warnings: Whether to log warnings at all.

    Returns:
        A list of docstring sections.
    """
    sections: list[DocstringSection] = []
    current_section = []

    in_code_block = False
    lines = docstring.lines

    options = {
        "ignore_init_summary": ignore_init_summary,
        "trim_doctest_flags": trim_doctest_flags,
        "returns_multiple_items": returns_multiple_items,
        "returns_named_value": returns_named_value,
        "returns_type_in_property_summary": returns_type_in_property_summary,
        "receives_multiple_items": receives_multiple_items,
        "receives_named_value": receives_named_value,
        "warn_unknown_params": warn_unknown_params,
        "warn_missing_types": warn_missing_types,
        "warnings": warnings,
    }

    ignore_summary = (
        options["ignore_init_summary"]
        and docstring.parent is not None
        and docstring.parent.name == "__init__"
        and docstring.parent.is_function
        and docstring.parent.parent is not None
        and docstring.parent.parent.is_class
    )

    offset = 2 if ignore_summary else 0

    while offset < len(lines):
        line_lower = lines[offset].lower()

        if in_code_block:
            if line_lower.lstrip(" ").startswith("```"):
                in_code_block = False
            current_section.append(lines[offset])

        elif line_lower.lstrip(" ").startswith("```"):
            in_code_block = True
            current_section.append(lines[offset])

        elif match := _RE_ADMONITION.match(lines[offset]):
            groups = match.groupdict()
            title = groups["title"]
            admonition_type = groups["type"]
            is_section = admonition_type.lower() in _section_kind

            has_previous_line = offset > 0
            blank_line_above = not has_previous_line or _is_empty_line(lines[offset - 1])
            has_next_line = offset < len(lines) - 1
            has_next_lines = offset < len(lines) - 2
            blank_line_below = has_next_line and _is_empty_line(lines[offset + 1])
            blank_lines_below = has_next_lines and _is_empty_line(lines[offset + 2])
            indented_line_below = has_next_line and not blank_line_below and lines[offset + 1].startswith(" ")
            indented_lines_below = has_next_lines and not blank_lines_below and lines[offset + 2].startswith(" ")
            if not (indented_line_below or indented_lines_below):
                # Do not warn when there are no contents,
                # this is most probably not a section or admonition.
                current_section.append(lines[offset])
                offset += 1
                continue
            reasons = []
            kind = "section" if is_section else "admonition"
            if (indented_line_below or indented_lines_below) and not blank_line_above:
                reasons.append(f"Missing blank line above {kind}")
            if indented_lines_below and blank_line_below:
                reasons.append(f"Extraneous blank line below {kind} title")
            if reasons:
                if warnings:
                    reasons_string = "; ".join(reasons)
                    docstring_warning(
                        docstring,
                        offset,
                        f"Possible {kind} skipped, reasons: {reasons_string}",
                        LogLevel.debug,
                    )
                current_section.append(lines[offset])
                offset += 1
                continue

            if is_section:
                if current_section:
                    if any(current_section):
                        sections.append(DocstringSectionText("\n".join(current_section).rstrip("\n")))
                    current_section = []
                reader = _section_reader[_section_kind[admonition_type.lower()]]
                section, offset = reader(docstring, offset=offset + 1, **options)
                if section:
                    section.title = title
                    sections.append(section)

            else:
                contents, offset = _read_block(docstring, offset=offset + 1)
                if contents:
                    if current_section:
                        if any(current_section):
                            sections.append(DocstringSectionText("\n".join(current_section).rstrip("\n")))
                        current_section = []
                    if title is None:
                        title = admonition_type
                    admonition_type = admonition_type.lower().replace(" ", "-")
                    sections.append(DocstringSectionAdmonition(kind=admonition_type, text=contents, title=title))
                else:
                    with suppress(IndexError):
                        current_section.append(lines[offset])
        else:
            current_section.append(lines[offset])

        offset += 1

    if current_section and any(current_section):
        sections.append(DocstringSectionText("\n".join(current_section).rstrip("\n")))

    if (
        returns_type_in_property_summary
        and sections
        and docstring.parent
        and docstring.parent.is_attribute
        and "property" in docstring.parent.labels
    ):
        lines = sections[0].value.lstrip().split("\n")
        if ":" in lines[0]:
            annotation, line = lines[0].split(":", 1)
            lines = [line, *lines[1:]]
            sections[0].value = "\n".join(lines)
            sections.append(
                DocstringSectionReturns(
                    [DocstringReturn("", description="", annotation=parse_docstring_annotation(annotation, docstring))],
                ),
            )

    return sections
