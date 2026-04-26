# This module contains our dynamic analysis agent,
# capable of inspecting modules and objects in memory, at runtime.

from __future__ import annotations

import ast
import functools
import types
import typing
from inspect import Parameter as SignatureParameter
from inspect import Signature, cleandoc, getsourcelines, unwrap
from inspect import signature as getsignature
from typing import TYPE_CHECKING, Any

from griffe._internal.agents.nodes.runtime import ObjectNode
from griffe._internal.collections import LinesCollection, ModulesCollection
from griffe._internal.enumerations import Kind, ParameterKind, TypeParameterKind
from griffe._internal.expressions import Expr, ExprBinOp, ExprSubscript, ExprTuple, safe_get_annotation
from griffe._internal.extensions.base import Extensions, load_extensions
from griffe._internal.importer import dynamic_import
from griffe._internal.logger import logger
from griffe._internal.models import (
    Alias,
    Attribute,
    Class,
    Docstring,
    Function,
    Module,
    Parameter,
    Parameters,
    TypeAlias,
    TypeParameter,
    TypeParameters,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from griffe._internal.docstrings.parsers import DocstringOptions, DocstringStyle
    from griffe._internal.enumerations import Parser

_TYPING_MODULES: tuple[types.ModuleType, ...]
try:
    import typing_extensions
except ImportError:
    _TYPING_MODULES = (typing,)
else:
    _TYPING_MODULES = (typing, typing_extensions)

_empty = Signature.empty


def inspect(
    module_name: str,
    *,
    filepath: Path | None = None,
    import_paths: Sequence[str | Path] | None = None,
    extensions: Extensions | None = None,
    parent: Module | None = None,
    docstring_parser: DocstringStyle | Parser | None = None,
    docstring_options: DocstringOptions | None = None,
    lines_collection: LinesCollection | None = None,
    modules_collection: ModulesCollection | None = None,
) -> Module:
    """Inspect a module.

    Sometimes we cannot get the source code of a module or an object,
    typically built-in modules like `itertools`.
    The only way to know what they are made of is to actually import them and inspect their contents.

    Sometimes, even if the source code is available,
    loading the object is desired because it was created or modified dynamically,
    and our static agent is not powerful enough to infer all these dynamic modifications.
    In this case, we load the module using introspection.

    Griffe therefore provides this function for dynamic analysis.
    It uses a [`NodeVisitor`][ast.NodeVisitor]-like class, the [`Inspector`][griffe.Inspector],
    to inspect the module with [`inspect.getmembers()`][inspect.getmembers].

    The inspection agent works similarly to the regular [`Visitor`][griffe.Visitor] agent,
    in that it maintains a state with the current object being handled, and recursively handle its members.

    Important:
        This function is generally not used directly.
        In most cases, users can rely on the [`GriffeLoader`][griffe.GriffeLoader]
        and its accompanying [`load`][griffe.load] shortcut and their respective options
        to load modules using dynamic analysis.

    Parameters:
        module_name: The module name (as when importing [from] it).
        filepath: The module file path.
        import_paths: Paths to import the module from.
        extensions: The extensions to use when inspecting the module.
        parent: The optional parent of this module.
        docstring_parser: The docstring parser to use. By default, no parsing is done.
        docstring_options: Docstring parsing options.
        lines_collection: A collection of source code lines.
        modules_collection: A collection of modules.

    Returns:
        The module, with its members populated.
    """
    return Inspector(
        module_name,
        filepath,
        extensions or load_extensions(),
        parent,
        docstring_parser=docstring_parser,
        docstring_options=docstring_options,
        lines_collection=lines_collection,
        modules_collection=modules_collection,
    ).get_module(import_paths)


class Inspector:
    """This class is used to instantiate an inspector.

    Inspectors iterate on objects members to extract data from them.
    """

    def __init__(
        self,
        module_name: str,
        filepath: Path | None,
        extensions: Extensions,
        parent: Module | None = None,
        docstring_parser: DocstringStyle | Parser | None = None,
        docstring_options: DocstringOptions | None = None,
        lines_collection: LinesCollection | None = None,
        modules_collection: ModulesCollection | None = None,
    ) -> None:
        """Initialize the inspector.

        Parameters:
            module_name: The module name.
            filepath: The optional filepath.
            extensions: Extensions to use when inspecting.
            parent: The module parent.
            docstring_parser: The docstring parser to use.
            docstring_options: Docstring parsing options.
            lines_collection: A collection of source code lines.
            modules_collection: A collection of modules.
        """
        super().__init__()

        self.module_name: str = module_name
        """The module name."""

        self.filepath: Path | None = filepath
        """The module file path."""

        self.extensions: Extensions = extensions
        """The extensions to use when inspecting."""

        self.parent: Module | None = parent
        """An optional parent for the final module object."""

        self.current: Module | Class = None  # ty:ignore[invalid-assignment]
        """The current object being inspected."""

        self.docstring_parser: DocstringStyle | Parser | None = docstring_parser
        """The docstring parser to use."""

        self.docstring_options: DocstringOptions = docstring_options or {}  # ty:ignore[invalid-assignment]
        """The docstring parsing options."""

        self.lines_collection: LinesCollection = lines_collection or LinesCollection()
        """A collection of source code lines."""

        self.modules_collection: ModulesCollection = modules_collection or ModulesCollection()
        """A collection of modules."""

    def _get_docstring(self, node: ObjectNode) -> Docstring | None:
        try:
            # Access `__doc__` directly to avoid taking the `__doc__` attribute from a parent class.
            value = getattr(node.obj, "__doc__", None)
        except Exception:  # noqa: BLE001
            return None
        if value is None:
            return None
        try:
            # We avoid `inspect.getdoc` to avoid getting
            # the `__doc__` attribute from a parent class,
            # but we still want to clean the doc.
            cleaned = cleandoc(value)
        except AttributeError:
            # Triggered on method descriptors.
            return None
        return Docstring(
            cleaned,
            parser=self.docstring_parser,
            parser_options=self.docstring_options,
        )

    def _get_linenos(self, node: ObjectNode) -> tuple[int, int] | tuple[None, None]:
        # Line numbers won't be useful if we don't have the source code.
        if not self.filepath or self.filepath not in self.lines_collection:
            return None, None
        try:
            lines, lineno = getsourcelines(node.obj)
        except (OSError, TypeError):
            return None, None
        return lineno, lineno + "".join(lines).rstrip().count("\n")

    def get_module(self, import_paths: Sequence[str | Path] | None = None) -> Module:
        """Build and return the object representing the module attached to this inspector.

        This method triggers a complete inspection of the module members.

        Parameters:
            import_paths: Paths replacing `sys.path` to import the module.

        Returns:
            A module instance.
        """
        import_path = self.module_name
        if self.parent is not None:
            import_path = f"{self.parent.path}.{import_path}"

        # Make sure `import_paths` is a list, in case we want to `insert` into it.
        import_paths = list(import_paths or ())

        # If the thing we want to import has a filepath,
        # we make sure to insert the right parent directory
        # at the front of our list of import paths.
        # We do this by counting the number of dots `.` in the import path,
        # corresponding to slashes `/` in the filesystem,
        # and go up in the file tree the same number of times.
        if self.filepath:
            parent_path = self.filepath.parent
            for _ in range(import_path.count(".")):
                parent_path = parent_path.parent
            # Climb up one more time for `__init__` modules.
            if self.filepath.stem == "__init__":
                parent_path = parent_path.parent
            if parent_path not in import_paths:
                import_paths.insert(0, parent_path)

        value = dynamic_import(import_path, import_paths)

        # We successfully imported the given object,
        # and we now create the object tree with all the necessary nodes,
        # from the root of the package to this leaf object.
        parent_node = None
        if self.parent is not None:
            for part in self.parent.path.split("."):
                parent_node = ObjectNode(None, name=part, parent=parent_node)
        module_node = ObjectNode(value, self.module_name, parent=parent_node)

        self.inspect(module_node)
        return self.current.module

    def inspect(self, node: ObjectNode) -> None:
        """Extend the base inspection with extensions.

        Parameters:
            node: The node to inspect.
        """
        getattr(self, f"inspect_{node.kind}", self.generic_inspect)(node)

    def generic_inspect(self, node: ObjectNode) -> None:
        """Extend the base generic inspection with extensions.

        Parameters:
            node: The node to inspect.
        """
        for child in node.children:
            if target_path := child.alias_target_path:
                # If the child is an actual submodule of the current module,
                # and has no `__file__` set, we won't find it on the disk so we must inspect it now.
                # For that we instantiate a new inspector and use it to inspect the submodule,
                # then assign the submodule as member of the current module.
                # If the submodule has a `__file__` set, the loader should find it on the disk,
                # so we skip it here (no member, no alias, just skip it).
                if child.is_module and target_path == f"{self.current.path}.{child.name}":
                    if not hasattr(child.obj, "__file__"):
                        logger.debug("Module %s is not discoverable on disk, inspecting right now", target_path)
                        inspector = Inspector(
                            child.name,
                            filepath=None,
                            parent=self.current.module,
                            extensions=self.extensions,
                            docstring_parser=self.docstring_parser,
                            docstring_options=self.docstring_options,
                            lines_collection=self.lines_collection,
                            modules_collection=self.modules_collection,
                        )
                        inspector.inspect_module(child)
                        self.current.set_member(child.name, inspector.current.module)
                # Otherwise, alias the object.
                else:
                    alias = Alias(child.name, target_path, analysis="dynamic")
                    self.current.set_member(child.name, alias)
                    self.extensions.call("on_alias_instance", alias=alias, node=node, agent=self)
            else:
                self.inspect(child)

    def inspect_module(self, node: ObjectNode) -> None:
        """Inspect a module.

        Parameters:
            node: The node to inspect.
        """
        self.extensions.call("on_node", node=node, agent=self)
        self.extensions.call("on_module_node", node=node, agent=self)
        self.current = module = Module(
            name=self.module_name,
            filepath=self.filepath,
            parent=self.parent,
            docstring=self._get_docstring(node),
            lines_collection=self.lines_collection,
            modules_collection=self.modules_collection,
            analysis="dynamic",
        )
        self.extensions.call("on_instance", node=node, obj=module, agent=self)
        self.extensions.call("on_module_instance", node=node, mod=module, agent=self)
        self.generic_inspect(node)
        self.extensions.call("on_members", node=node, obj=module, agent=self)
        self.extensions.call("on_module_members", node=node, mod=module, agent=self)

    def inspect_class(self, node: ObjectNode) -> None:
        """Inspect a class.

        Parameters:
            node: The node to inspect.
        """
        self.extensions.call("on_node", node=node, agent=self)
        self.extensions.call("on_class_node", node=node, agent=self)

        bases = []
        for base in node.obj.__bases__:
            if base is object:
                continue
            bases.append(f"{base.__module__}.{base.__qualname__}")

        lineno, endlineno = self._get_linenos(node)
        class_ = Class(
            name=node.name,
            docstring=self._get_docstring(node),
            bases=bases,
            type_parameters=TypeParameters(*_convert_type_parameters(node.obj, parent=self.current, member=node.name)),
            lineno=lineno,
            endlineno=endlineno,
            analysis="dynamic",
        )
        self.current.set_member(node.name, class_)
        self.current = class_
        self.extensions.call("on_instance", node=node, obj=class_, agent=self)
        self.extensions.call("on_class_instance", node=node, cls=class_, agent=self)
        self.generic_inspect(node)
        self.extensions.call("on_members", node=node, obj=class_, agent=self)
        self.extensions.call("on_class_members", node=node, cls=class_, agent=self)
        self.current = self.current.parent  # ty:ignore[invalid-assignment]

    def inspect_staticmethod(self, node: ObjectNode) -> None:
        """Inspect a static method.

        Parameters:
            node: The node to inspect.
        """
        self.handle_function(node, {"staticmethod"})

    def inspect_classmethod(self, node: ObjectNode) -> None:
        """Inspect a class method.

        Parameters:
            node: The node to inspect.
        """
        self.handle_function(node, {"classmethod"})

    def inspect_method_descriptor(self, node: ObjectNode) -> None:
        """Inspect a method descriptor.

        Parameters:
            node: The node to inspect.
        """
        self.handle_function(node, {"method descriptor"})

    def inspect_builtin_method(self, node: ObjectNode) -> None:
        """Inspect a builtin method.

        Parameters:
            node: The node to inspect.
        """
        self.handle_function(node, {"builtin"})

    def inspect_method(self, node: ObjectNode) -> None:
        """Inspect a method.

        Parameters:
            node: The node to inspect.
        """
        self.handle_function(node)

    def inspect_coroutine(self, node: ObjectNode) -> None:
        """Inspect a coroutine.

        Parameters:
            node: The node to inspect.
        """
        self.handle_function(node, {"async"})

    def inspect_builtin_function(self, node: ObjectNode) -> None:
        """Inspect a builtin function.

        Parameters:
            node: The node to inspect.
        """
        self.handle_function(node, {"builtin"})

    def inspect_function(self, node: ObjectNode) -> None:
        """Inspect a function.

        Parameters:
            node: The node to inspect.
        """
        self.handle_function(node)

    def inspect_cached_property(self, node: ObjectNode) -> None:
        """Inspect a cached property.

        Parameters:
            node: The node to inspect.
        """
        self.handle_function(node, {"cached", "property"})

    def inspect_property(self, node: ObjectNode) -> None:
        """Inspect a property.

        Parameters:
            node: The node to inspect.
        """
        self.handle_function(node, {"property"})

    def inspect_getset_descriptor(self, node: ObjectNode) -> None:
        """Inspect a get/set descriptor.

        Parameters:
            node: The node to inspect.
        """
        self.handle_function(node, {"property"})

    def handle_function(self, node: ObjectNode, labels: set | None = None) -> None:
        """Handle a function.

        Parameters:
            node: The node to inspect.
            labels: Labels to add to the data object.
        """
        self.extensions.call("on_node", node=node, agent=self)
        self.extensions.call("on_function_node", node=node, agent=self)

        try:
            signature = getsignature(node.obj)
        except Exception:  # noqa: BLE001
            # So many exceptions can be raised here:
            # AttributeError, NameError, RuntimeError, ValueError, TokenError, TypeError...
            parameters = None
            returns = None
        else:
            parameters = Parameters(
                *[
                    _convert_parameter(parameter, parent=self.current, member=node.name)
                    for parameter in signature.parameters.values()
                ],
            )
            return_annotation = signature.return_annotation
            returns = (
                None
                if return_annotation is _empty
                else _convert_object_to_annotation(return_annotation, parent=self.current, member=node.name)
            )

        lineno, endlineno = self._get_linenos(node)

        obj: Attribute | Function
        labels = labels or set()
        if "property" in labels:
            obj = Attribute(
                name=node.name,
                value=None,
                annotation=returns,
                docstring=self._get_docstring(node),
                lineno=lineno,
                endlineno=endlineno,
                analysis="dynamic",
            )
        else:
            obj = Function(
                name=node.name,
                parameters=parameters,
                returns=returns,
                type_parameters=TypeParameters(
                    *_convert_type_parameters(node.obj, parent=self.current, member=node.name),
                ),
                docstring=self._get_docstring(node),
                lineno=lineno,
                endlineno=endlineno,
                analysis="dynamic",
            )
        obj.labels |= labels
        self.current.set_member(node.name, obj)
        self.extensions.call("on_instance", node=node, obj=obj, agent=self)
        if obj.is_attribute:
            self.extensions.call("on_attribute_instance", node=node, attr=obj, agent=self)
        else:
            self.extensions.call("on_function_instance", node=node, func=obj, agent=self)

    def inspect_type_alias(self, node: ObjectNode) -> None:
        """Inspect a type alias.

        Parameters:
            node: The node to inspect.
        """
        self.extensions.call("on_node", node=node, agent=self)
        self.extensions.call("on_type_alias_node", node=node, agent=self)

        lineno, endlineno = self._get_linenos(node)

        type_alias = TypeAlias(
            name=node.name,
            value=_convert_type_to_annotation(node.obj.__value__, parent=self.current, member=node.name),
            lineno=lineno,
            endlineno=endlineno,
            type_parameters=TypeParameters(*_convert_type_parameters(node.obj, parent=self.current, member=node.name)),
            docstring=self._get_docstring(node),
            parent=self.current,
            analysis="dynamic",
        )
        self.current.set_member(node.name, type_alias)
        self.extensions.call("on_instance", node=node, obj=type_alias, agent=self)
        self.extensions.call("on_type_alias_instance", node=node, type_alias=type_alias, agent=self)

    def inspect_attribute(self, node: ObjectNode) -> None:
        """Inspect an attribute.

        Parameters:
            node: The node to inspect.
        """
        self.handle_attribute(node)

    def handle_attribute(self, node: ObjectNode, annotation: str | Expr | None = None) -> None:
        """Handle an attribute.

        Parameters:
            node: The node to inspect.
            annotation: A potential annotation.
        """
        self.extensions.call("on_node", node=node, agent=self)
        self.extensions.call("on_attribute_node", node=node, agent=self)

        # TODO: To improve.
        parent = self.current
        labels: set[str] = set()

        if parent.kind is Kind.MODULE:
            labels.add("module-attribute")
        elif parent.kind is Kind.CLASS:
            labels.add("class-attribute")
        elif parent.kind is Kind.FUNCTION:
            if parent.name != "__init__":
                return
            parent = parent.parent
            labels.add("instance-attribute")

        try:
            value = repr(node.obj)
        except Exception:  # noqa: BLE001
            value = None
        try:
            docstring = self._get_docstring(node)
        except Exception:  # noqa: BLE001
            docstring = None

        attribute = Attribute(
            name=node.name,
            value=value,
            annotation=annotation,
            docstring=docstring,
            analysis="dynamic",
        )
        attribute.labels |= labels
        parent.set_member(node.name, attribute)  # ty:ignore[unresolved-attribute]

        if node.name == "__all__":
            parent.exports = list(node.obj)  # ty:ignore[invalid-assignment]
        self.extensions.call("on_instance", node=node, obj=attribute, agent=self)
        self.extensions.call("on_attribute_instance", node=node, attr=attribute, agent=self)


_parameter_kind_map = {
    SignatureParameter.POSITIONAL_ONLY: ParameterKind.positional_only,
    SignatureParameter.POSITIONAL_OR_KEYWORD: ParameterKind.positional_or_keyword,
    SignatureParameter.VAR_POSITIONAL: ParameterKind.var_positional,
    SignatureParameter.KEYWORD_ONLY: ParameterKind.keyword_only,
    SignatureParameter.VAR_KEYWORD: ParameterKind.var_keyword,
}


def _convert_parameter(
    parameter: SignatureParameter,
    *,
    parent: Module | Class,
    member: str | None = None,
) -> Parameter:
    name = parameter.name
    annotation = (
        None
        if parameter.annotation is _empty
        else _convert_object_to_annotation(parameter.annotation, parent=parent, member=member)
    )
    kind = _parameter_kind_map[parameter.kind]
    if parameter.default is _empty:
        default = None
    elif hasattr(parameter.default, "__name__"):
        # Avoid `repr` containing chevrons and memory addresses.
        default = parameter.default.__name__
    else:
        default = repr(parameter.default)
    return Parameter(name, annotation=annotation, kind=kind, default=default)


def _convert_object_to_annotation(obj: Any, *, parent: Module | Class, member: str | None = None) -> str | Expr | None:
    # Even when *we* import future annotations,
    # the object from which we get a signature
    # can come from modules which did *not* import them,
    # so `inspect.signature` returns actual Python objects
    # that we must deal with.
    if isinstance(obj, str):
        annotation = obj
    else:
        # Always give precedence to the object's representation...
        obj_repr = repr(obj)
        if hasattr(obj, "__name__"):  # noqa: SIM108
            # ...unless it contains chevrons (which likely means it's a class),
            # in which case we use the object's name.
            annotation = obj.__name__ if "<" in obj_repr else obj_repr
        else:
            annotation = obj_repr
    try:
        annotation_node = compile(annotation, mode="eval", filename="<>", flags=ast.PyCF_ONLY_AST, optimize=2)
    except SyntaxError:
        return obj
    return safe_get_annotation(annotation_node.body, parent, member=member)  # ty:ignore[unresolved-attribute]


_type_parameter_kind_map = {
    getattr(module, attr): value
    for attr, value in {
        "TypeVar": TypeParameterKind.type_var,
        "TypeVarTuple": TypeParameterKind.type_var_tuple,
        "ParamSpec": TypeParameterKind.param_spec,
    }.items()
    for module in _TYPING_MODULES
    if hasattr(module, attr)
}


def _convert_type_parameters(
    obj: Any,
    *,
    parent: Module | Class,
    member: str | None = None,
) -> list[TypeParameter]:
    obj = unwrap(obj)

    if not hasattr(obj, "__type_params__"):
        return []

    type_parameters = []
    for type_parameter in obj.__type_params__:
        bound = getattr(type_parameter, "__bound__", None)
        if bound is not None:
            bound = _convert_type_to_annotation(bound, parent=parent, member=member)
        constraints: list[str | Expr] = [
            _convert_type_to_annotation(constraint, parent=parent, member=member)
            for constraint in getattr(type_parameter, "__constraints__", ())
        ]  # ty:ignore[invalid-assignment]

        if getattr(type_parameter, "has_default", lambda: False)():
            default = _convert_type_to_annotation(
                type_parameter.__default__,
                parent=parent,
                member=member,
            )
        else:
            default = None

        type_parameters.append(
            TypeParameter(
                type_parameter.__name__,
                kind=_type_parameter_kind_map[type(type_parameter)],
                bound=bound,
                constraints=constraints or None,
                default=default,
            ),
        )

    return type_parameters


def _convert_type_to_annotation(obj: Any, *, parent: Module | Class, member: str | None = None) -> str | Expr | None:
    origin = typing.get_origin(obj)

    if origin is None:
        return _convert_object_to_annotation(obj, parent=parent, member=member)

    args: Sequence[str | Expr | None] = [
        _convert_type_to_annotation(arg, parent=parent, member=member) for arg in typing.get_args(obj)
    ]

    if origin is types.UnionType:
        return functools.reduce(lambda left, right: ExprBinOp(left, "|", right), args)

    origin = _convert_type_to_annotation(origin, parent=parent, member=member)
    if origin is None:
        return None

    return ExprSubscript(origin, ExprTuple(args, implicit=True))  # ty:ignore[invalid-argument-type]
