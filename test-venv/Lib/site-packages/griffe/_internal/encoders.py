# This module contains data encoders/serializers and decoders/deserializers.
# We only support JSON for now, but might want to add more formats in the future.

from __future__ import annotations

import json
from pathlib import Path, PosixPath, WindowsPath
from typing import TYPE_CHECKING, Any

from griffe._internal import expressions
from griffe._internal.enumerations import Kind, ParameterKind, TypeParameterKind
from griffe._internal.git import GitInfo
from griffe._internal.models import (
    Alias,
    Attribute,
    Class,
    Decorator,
    Docstring,
    Function,
    Module,
    Object,
    Parameter,
    Parameters,
    TypeAlias,
    TypeParameter,
    TypeParameters,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_json_encoder_map: dict[type, Callable[[Any], Any]] = {
    Path: str,
    PosixPath: str,
    WindowsPath: str,
    set: sorted,
}


class JSONEncoder(json.JSONEncoder):
    """JSON encoder.

    JSON encoders can be used directly, or through
    the [`json.dump`][] or [`json.dumps`][] methods.

    Examples:
        >>> from griffe import JSONEncoder
        >>> JSONEncoder(full=True).encode(..., **kwargs)

        >>> import json
        >>> from griffe import JSONEncoder
        >>> json.dumps(..., cls=JSONEncoder, full=True, **kwargs)
    """

    def __init__(
        self,
        *args: Any,
        full: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize the encoder.

        Parameters:
            *args: See [`json.JSONEncoder`][].
            full: Whether to dump full data or base data.
                If you plan to reload the data in Python memory
                using the [`json_decoder`][griffe.json_decoder],
                you don't need the full data as it can be inferred again
                using the base data. If you want to feed a non-Python
                tool instead, dump the full data.
            **kwargs: See [`json.JSONEncoder`][].
        """
        super().__init__(*args, **kwargs)
        self.full: bool = full
        """Whether to dump full data or base data."""

    def default(self, obj: Any) -> Any:  # ty:ignore[invalid-method-override]
        """Return a serializable representation of the given object.

        Parameters:
            obj: The object to serialize.

        Returns:
            A serializable representation.
        """
        try:
            return obj.as_dict(full=self.full)
        except AttributeError:
            return _json_encoder_map.get(type(obj), super().default)(obj)


def _load_docstring(obj_dict: dict) -> Docstring | None:
    if "docstring" in obj_dict:
        return Docstring(**obj_dict["docstring"])
    return None


def _load_decorators(obj_dict: dict) -> list[Decorator]:
    return [Decorator(**dec) for dec in obj_dict.get("decorators", [])]


def _load_expression(expression: dict) -> expressions.Expr:
    # The expression class name is stored in the `cls` key-value.
    cls = getattr(expressions, expression.pop("cls"))
    expr = cls(**expression)

    # For attributes, we need to re-attach names (`values`) together,
    # as a single linked list, from right to left:
    # in `a.b.c`, `c` links to `b` which links to `a`.
    # In `(a or b).c` however, `c` does not link to `(a or b)`,
    # as `(a or b)` is not a name and wouldn't allow to resolve `c`.
    if cls is expressions.ExprAttribute:
        previous = None
        for value in expr.values:
            if previous is not None:
                value.parent = previous
            if isinstance(value, expressions.ExprName):
                previous = value
    return expr


def _load_parameter(obj_dict: dict[str, Any]) -> Parameter:
    return Parameter(
        obj_dict["name"],
        annotation=obj_dict["annotation"],
        kind=ParameterKind(obj_dict["kind"]),
        default=obj_dict["default"],
        docstring=_load_docstring(obj_dict),
    )


def _load_type_parameter(obj_dict: dict[str, Any]) -> TypeParameter:
    return TypeParameter(
        obj_dict["name"],
        kind=TypeParameterKind(obj_dict["kind"]),
        bound=obj_dict["annotation"],
        default=obj_dict["default"],
    )


def _load_git_info(obj_dict: dict[str, Any]) -> GitInfo:
    return GitInfo(
        repository=Path(obj_dict["repository"]),
        service=obj_dict["service"],
        remote_url=obj_dict["remote_url"],
        commit_hash=obj_dict["commit_hash"],
    )


def _attach_parent_to_expr(expr: expressions.Expr | str | None, parent: Module | Class) -> None:
    if not isinstance(expr, expressions.Expr):
        return
    for elem in expr:
        if isinstance(elem, expressions.ExprName):
            elem.parent = parent
        elif isinstance(elem, expressions.ExprAttribute) and isinstance(elem.first, expressions.ExprName):
            elem.first.parent = parent


def _attach_parent_to_exprs(obj: Class | Function | Attribute | TypeAlias, parent: Module | Class) -> None:
    # Every name and attribute expression must be reattached
    # to its parent Griffe object (using its `parent` attribute),
    # to allow resolving names.
    if isinstance(obj, Class):
        if obj.docstring:
            _attach_parent_to_expr(obj.docstring.value, parent)
        for decorator in obj.decorators:
            _attach_parent_to_expr(decorator.value, parent)
        for type_parameter in obj.type_parameters:
            _attach_parent_to_expr(type_parameter.annotation, parent)
            _attach_parent_to_expr(type_parameter.default, parent)
    elif isinstance(obj, Function):
        if obj.docstring:
            _attach_parent_to_expr(obj.docstring.value, parent)
        for decorator in obj.decorators:
            _attach_parent_to_expr(decorator.value, parent)
        for type_parameter in obj.type_parameters:
            _attach_parent_to_expr(type_parameter.annotation, parent)
            _attach_parent_to_expr(type_parameter.default, parent)
        for param in obj.parameters:
            _attach_parent_to_expr(param.annotation, parent)
            _attach_parent_to_expr(param.default, parent)
        _attach_parent_to_expr(obj.returns, parent)
    elif isinstance(obj, Attribute):
        if obj.docstring:
            _attach_parent_to_expr(obj.docstring.value, parent)
        _attach_parent_to_expr(obj.value, parent)
    elif isinstance(obj, TypeAlias):
        if obj.docstring:
            _attach_parent_to_expr(obj.docstring.value, parent)
        for type_parameter in obj.type_parameters:
            _attach_parent_to_expr(type_parameter.annotation, parent)
            _attach_parent_to_expr(type_parameter.default, parent)
        _attach_parent_to_expr(obj.value, parent)


def _load_module(obj_dict: dict[str, Any]) -> Module:
    filepath = obj_dict.get("filepath")
    if filepath is not None:
        filepath = [*map(Path, filepath)] if isinstance(filepath, list) else Path(filepath)  # ty:ignore[invalid-argument-type]
    module = Module(
        name=obj_dict["name"],
        filepath=filepath,
        docstring=_load_docstring(obj_dict),
        runtime=obj_dict.get("runtime", True),
        analysis=obj_dict.get("analysis"),
    )
    members = obj_dict.get("members", {}).values()

    for module_member in members:
        module.set_member(module_member.name, module_member)
        _attach_parent_to_exprs(module_member, module)
    module.labels |= set(obj_dict.get("labels", ()))
    module.exports = obj_dict.get("exports")
    module.imports = obj_dict.get("imports", {})
    module.deprecated = obj_dict.get("deprecated")
    module.public = obj_dict.get("public")
    module.source_link = obj_dict.get("source_link")
    if git_info := obj_dict.get("git_info"):
        module.git_info = _load_git_info(git_info)
    return module


def _load_class(obj_dict: dict[str, Any]) -> Class:
    class_ = Class(
        name=obj_dict["name"],
        lineno=obj_dict["lineno"],
        endlineno=obj_dict.get("endlineno"),
        docstring=_load_docstring(obj_dict),
        decorators=_load_decorators(obj_dict),
        type_parameters=TypeParameters(*obj_dict["type_parameters"]) if "type_parameters" in obj_dict else None,
        bases=obj_dict["bases"],
        runtime=obj_dict.get("runtime", True),
        analysis=obj_dict.get("analysis"),
    )
    members = obj_dict.get("members", {}).values()

    for class_member in members:
        class_.set_member(class_member.name, class_member)
        _attach_parent_to_exprs(class_member, class_)
    class_.labels |= set(obj_dict.get("labels", ()))
    class_.imports = obj_dict.get("imports", {})
    class_.deprecated = obj_dict.get("deprecated")
    class_.public = obj_dict.get("public")
    class_.source_link = obj_dict.get("source_link")
    _attach_parent_to_exprs(class_, class_)
    if git_info := obj_dict.get("git_info"):
        class_.git_info = _load_git_info(git_info)
    return class_


def _load_function(obj_dict: dict[str, Any]) -> Function:
    function = Function(
        name=obj_dict["name"],
        parameters=Parameters(*obj_dict["parameters"]),
        returns=obj_dict["returns"],
        decorators=_load_decorators(obj_dict),
        type_parameters=TypeParameters(*obj_dict["type_parameters"]) if "type_parameters" in obj_dict else None,
        lineno=obj_dict["lineno"],
        endlineno=obj_dict.get("endlineno"),
        docstring=_load_docstring(obj_dict),
        runtime=obj_dict.get("runtime", True),
        analysis=obj_dict.get("analysis"),
    )
    function.labels |= set(obj_dict.get("labels", ()))
    function.deprecated = obj_dict.get("deprecated")
    function.public = obj_dict.get("public")
    function.source_link = obj_dict.get("source_link")
    if git_info := obj_dict.get("git_info"):
        function.git_info = _load_git_info(git_info)
    return function


def _load_attribute(obj_dict: dict[str, Any]) -> Attribute:
    attribute = Attribute(
        name=obj_dict["name"],
        lineno=obj_dict["lineno"],
        endlineno=obj_dict.get("endlineno"),
        docstring=_load_docstring(obj_dict),
        value=obj_dict.get("value"),
        annotation=obj_dict.get("annotation"),
        analysis=obj_dict.get("analysis"),
    )
    attribute.labels |= set(obj_dict.get("labels", ()))
    attribute.runtime = obj_dict.get("runtime", True)
    attribute.deprecated = obj_dict.get("deprecated")
    attribute.public = obj_dict.get("public")
    attribute.source_link = obj_dict.get("source_link")
    if git_info := obj_dict.get("git_info"):
        attribute.git_info = _load_git_info(git_info)
    return attribute


def _load_alias(obj_dict: dict[str, Any]) -> Alias:
    alias = Alias(
        name=obj_dict["name"],
        target=obj_dict["target_path"],
        lineno=obj_dict["lineno"],
        endlineno=obj_dict.get("endlineno"),
        runtime=obj_dict.get("runtime", True),
        inherited=obj_dict.get("inherited", False),
        analysis=obj_dict.get("analysis"),
    )
    alias.public = obj_dict.get("public")
    alias.deprecated = obj_dict.get("deprecated")
    return alias


def _load_type_alias(obj_dict: dict[str, Any]) -> TypeAlias:
    type_alias = TypeAlias(
        name=obj_dict["name"],
        value=obj_dict["value"],
        type_parameters=TypeParameters(*obj_dict["type_parameters"]),
        lineno=obj_dict["lineno"],
        endlineno=obj_dict.get("endlineno"),
        docstring=_load_docstring(obj_dict),
        analysis=obj_dict.get("analysis"),
    )
    type_alias.labels |= set(obj_dict.get("labels", ()))
    type_alias.runtime = obj_dict.get("runtime", True)
    type_alias.deprecated = obj_dict.get("deprecated")
    type_alias.public = obj_dict.get("public")
    type_alias.source_link = obj_dict.get("source_link")
    if git_info := obj_dict.get("git_info"):
        type_alias.git_info = _load_git_info(git_info)
    return type_alias


_loader_map: dict[Kind, Callable[[dict[str, Any]], Object | Alias]] = {
    Kind.MODULE: _load_module,
    Kind.CLASS: _load_class,
    Kind.FUNCTION: _load_function,
    Kind.ATTRIBUTE: _load_attribute,
    Kind.ALIAS: _load_alias,
    Kind.TYPE_ALIAS: _load_type_alias,
}


def json_decoder(
    obj_dict: dict[str, Any],
) -> dict[str, Any] | Object | Alias | Parameter | TypeParameter | str | expressions.Expr:
    """Decode dictionaries as data classes.

    The [`json.loads`][] method walks the tree from bottom to top.

    Examples:
        >>> import json
        >>> from griffe import json_decoder
        >>> json.loads(..., object_hook=json_decoder)

    Parameters:
        obj_dict: The dictionary to decode.

    Returns:
        An instance of a data class.
    """
    # Load expressions.
    if "cls" in obj_dict:
        return _load_expression(obj_dict)

    # Load objects and parameters.
    if "kind" in obj_dict:
        kind = obj_dict["kind"]
        if kind in _loader_map:
            return _loader_map[kind](obj_dict)
        # YORE: EOL 3.11: Replace `.__members__.values()` with `` within line.
        if kind in ParameterKind.__members__.values():
            return _load_parameter(obj_dict)
        # YORE: EOL 3.11: Replace `.__members__.values()` with `` within line.
        if kind in TypeParameterKind.__members__.values():
            return _load_type_parameter(obj_dict)

    # Return dict as is.
    return obj_dict
