# TODO: Support `extra_items=type`.
# TODO: Support `closed=True/False`.

from __future__ import annotations

import ast
from itertools import chain
from typing import TYPE_CHECKING, Any, TypedDict

from griffe._internal.docstrings.models import (
    DocstringParameter,
    DocstringSectionParameters,
)
from griffe._internal.enumerations import DocstringSectionKind, ParameterKind
from griffe._internal.expressions import Expr, ExprSubscript
from griffe._internal.extensions.base import Extension
from griffe._internal.models import Class, Docstring, Function, Parameter, Parameters

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


class _TypedDictAttr(TypedDict):
    name: str
    annotation: str | Expr | None
    docstring: Docstring | None


def _unwrap_annotation(annotation: str | Expr | None, *, default_required: bool) -> tuple[str | Expr | None, bool]:
    required = default_required

    # Annotations can be written ReadOnly[Required[T]] or Required[ReadOnly[T]],
    # so we unwrap a first time here and a second time at the end.
    if isinstance(annotation, ExprSubscript) and annotation.canonical_path in {
        "typing.ReadOnly",
        "typing_extensions.ReadOnly",
    }:
        annotation = annotation.slice

    # Unwrap `Required` and `NotRequired`, set `required` accordingly.
    if isinstance(annotation, ExprSubscript):
        if annotation.canonical_path in {
            "typing.Required",
            "typing_extensions.Required",
        }:
            annotation = annotation.slice
            required = True
        elif annotation.canonical_path in {
            "typing.NotRequired",
            "typing_extensions.NotRequired",
        }:
            annotation = annotation.slice
            required = False

    # Unwrap `ReadOnly` a second time here.
    if isinstance(annotation, ExprSubscript) and annotation.canonical_path in {
        "typing.ReadOnly",
        "typing_extensions.ReadOnly",
    }:
        annotation = annotation.slice

    return annotation, required


def _get_or_set_attrs(cls: Class) -> tuple[list[_TypedDictAttr], list[_TypedDictAttr]]:
    if (attrs := cls.extra.get("unpack_typeddict", {}).get("_attributes")) is not None:
        return attrs

    # Inspect `total` keyword argument to determine default requiredness.
    default_required = True
    for arg, value in cls.keywords.items():
        if arg == "total":
            try:
                total = ast.literal_eval(str(value))
            except (ValueError, SyntaxError):
                break
            if total is True:
                default_required = True
            elif total is False:
                default_required = False
            break

    # Extract attributes.
    required_attrs = []
    optional_attrs = []
    for attr in cls.attributes.values():
        annotation, required = _unwrap_annotation(attr.annotation, default_required=default_required)
        if required:
            required_attrs.append(
                _TypedDictAttr(
                    name=attr.name,
                    annotation=annotation,
                    docstring=attr.docstring,
                ),
            )
        else:
            optional_attrs.append(
                _TypedDictAttr(
                    name=attr.name,
                    annotation=annotation,
                    docstring=attr.docstring,
                ),
            )

    cls.extra["unpack_typeddict"]["_attributes"] = (required_attrs, optional_attrs)
    return (required_attrs, optional_attrs)


def _update_docstring(
    func: Function,
    required: Iterable[_TypedDictAttr],
    optional: Iterable[_TypedDictAttr],
    kwparam: Parameter | None = None,
) -> None:
    if not func.docstring:
        func.docstring = Docstring("", parent=func)

    params_section = None
    sections = func.docstring.parsed

    # Find existing "Parameters" section.
    section_gen = (section for section in sections if section.kind is DocstringSectionKind.parameters)
    params_section = next(section_gen, None)

    # Pop original variadic keyword parameter from section.
    if kwparam and params_section is not None:
        param_gen = (i for i, arg in enumerate(params_section.value) if arg.name.lstrip("*") == kwparam.name)
        if (kwarg_pos := next(param_gen, None)) is not None:
            params_section.value.pop(kwarg_pos)

    # If we have required parameters, add them to the "Parameters" section.
    if required:
        # Create a "Parameters" section if none exists.
        if params_section is None:
            params_section = DocstringSectionParameters([])
            func.docstring.parsed.append(params_section)

        # Add required parameters to the section.
        for attr in required:
            params_section.value.append(
                DocstringParameter(
                    name=attr["name"],
                    description=attr["docstring"].value if attr["docstring"] else "",
                    annotation=attr["annotation"],
                ),
            )

    # If we have optional parameters, add them to the "Parameters" section too,
    # with a default value of `...`.
    if optional:
        # Create a "Parameters" section if none exists.
        if params_section is None:
            params_section = DocstringSectionParameters([])
            func.docstring.parsed.append(params_section)

        # Add optional parameters to the section.
        for attr in optional:
            params_section.value.append(
                DocstringParameter(
                    name=attr["name"],
                    description=attr["docstring"].value if attr["docstring"] else "",
                    annotation=attr["annotation"],
                    value="...",
                ),
            )

    # TODO: Add `**kwargs` parameter if extra items are allowed.


def _params_from_attrs(required: Iterable[_TypedDictAttr], optional: Iterable[_TypedDictAttr]) -> Iterator[Parameter]:
    for attr in required:
        yield Parameter(
            name=attr["name"],
            annotation=attr["annotation"],
            kind=ParameterKind.keyword_only,
            docstring=attr["docstring"],
        )
    for attr in optional:
        yield Parameter(
            name=attr["name"],
            annotation=attr["annotation"],
            kind=ParameterKind.keyword_only,
            default="...",
            docstring=attr["docstring"],
        )


class UnpackTypedDictExtension(Extension):
    """An extension to handle `Unpack[TypeDict]`."""

    def on_class(self, *, cls: Class, **kwargs: Any) -> None:  # noqa: ARG002
        """Add an `__init__` method to `TypedDict` classes if missing."""
        for base in cls.bases:
            if isinstance(base, Expr) and base.canonical_path in {"typing.TypedDict", "typing_extensions.TypedDict"}:
                cls.labels.add("typed-dict")
                break
        else:
            return

        required, optional = _get_or_set_attrs(cls)

        if "__init__" not in cls.members:
            # Build the `__init__` method and add it to the class.
            parameters = Parameters(
                Parameter(name="self", kind=ParameterKind.positional_or_keyword),
                *_params_from_attrs(required, optional),
            )
            # TODO: Add `**kwargs` parameter if extra items are allowed.
            init = Function(name="__init__", parameters=parameters, returns="None")
            cls.set_member("__init__", init)
            # Update the `__init__` docstring.
            _update_docstring(init, required, optional)

        # Remove attributes from the class, as they are now in the `__init__` method.
        for attr in chain(required, optional):
            cls.del_member(attr["name"])

    def on_function(self, *, func: Function, **kwargs: Any) -> None:  # noqa: ARG002
        """Expand `**kwargs: Unpack[TypedDict]` in function signatures."""
        # Find any `**kwargs: Unpack[TypedDict]` parameter.
        for parameter in func.parameters:
            if parameter.kind is ParameterKind.var_keyword:
                annotation = parameter.annotation
                if isinstance(annotation, ExprSubscript) and annotation.canonical_path in {
                    "typing.Annotated",
                    "typing_extensions.Annotated",
                }:
                    annotation = annotation.slice.elements[0]
                if isinstance(annotation, ExprSubscript) and annotation.canonical_path in {
                    "typing.Unpack",
                    "typing_extensions.Unpack",
                }:
                    slice_path = annotation.slice.canonical_path
                    typed_dict = func.modules_collection[slice_path]
                    break
        else:
            return

        required, optional = _get_or_set_attrs(typed_dict)

        # Update any parameter section in the docstring.
        # We do this before updating the signature so that
        # parsing the docstring doesn't emit warnings.
        _update_docstring(func, required, optional, parameter)

        # Update the function parameters.
        del func.parameters[parameter.name]
        for param in _params_from_attrs(required, optional):
            func.parameters[param.name] = Parameter(
                name=param.name,
                annotation=param.annotation,
                kind=ParameterKind.keyword_only,
                default=param.default,
                docstring=param.docstring,
            )

        # TODO: Add `**kwargs` parameter if extra items are allowed.
