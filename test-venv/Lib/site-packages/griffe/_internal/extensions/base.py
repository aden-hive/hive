# This module contains the base class for extensions
# and the functions to load them.

from __future__ import annotations

import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from inspect import isclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from griffe._internal.agents.nodes.ast import ast_children, ast_kind
from griffe._internal.exceptions import ExtensionNotLoadedError
from griffe._internal.importer import dynamic_import

if TYPE_CHECKING:
    import ast
    from types import ModuleType

    from griffe._internal.agents.inspector import Inspector
    from griffe._internal.agents.nodes.runtime import ObjectNode
    from griffe._internal.agents.visitor import Visitor
    from griffe._internal.loader import GriffeLoader
    from griffe._internal.models import Alias, Attribute, Class, Function, Module, Object, TypeAlias


class Extension:
    """Base class for Griffe extensions."""

    def visit(self, node: ast.AST) -> None:
        """Visit a node.

        Parameters:
            node: The node to visit.
        """
        getattr(self, f"visit_{ast_kind(node)}", lambda _: None)(node)

    def generic_visit(self, node: ast.AST) -> None:
        """Visit children nodes.

        Parameters:
            node: The node to visit the children of.
        """
        for child in ast_children(node):
            self.visit(child)

    def inspect(self, node: ObjectNode) -> None:
        """Inspect a node.

        Parameters:
            node: The node to inspect.
        """
        getattr(self, f"inspect_{node.kind}", lambda _: None)(node)

    def generic_inspect(self, node: ObjectNode) -> None:
        """Extend the base generic inspection with extensions.

        Parameters:
            node: The node to inspect.
        """
        for child in node.children:
            if not child.alias_target_path:
                self.inspect(child)

    def on_node(self, *, node: ast.AST | ObjectNode, agent: Visitor | Inspector, **kwargs: Any) -> None:
        """Run when visiting a new node during static/dynamic analysis.

        Parameters:
            node: The currently visited node.
        """

    def on_instance(
        self,
        *,
        node: ast.AST | ObjectNode,
        obj: Object,
        agent: Visitor | Inspector,
        **kwargs: Any,
    ) -> None:
        """Run when an Object has been created.

        Warning:
            This method runs while the object tree is still being constructed:
            data might be incomplete (class inheritance, alias resolution, etc.).
            Only hook onto this event if you know what you're doing.

        Parameters:
            node: The currently visited node.
            obj: The object instance.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_object(self, *, obj: Object, loader: GriffeLoader, **kwargs: Any) -> None:
        """Run on objects (every kind) once the object tree has been fully constructed.

        Note:
            This method runs once the object tree has been fully constructed:
            data is therefore complete and you can safely hook onto this event.

        Parameters:
            obj: The object instance.
            loader: The loader currently in use.
            **kwargs: For forward-compatibility.
        """

    def on_members(self, *, node: ast.AST | ObjectNode, obj: Object, agent: Visitor | Inspector, **kwargs: Any) -> None:
        """Run when members of an Object have been loaded.

        Warning:
            This method runs while the object tree is still being constructed:
            data might be incomplete (class inheritance, alias resolution, etc.).
            Only hook onto this event if you know what you're doing.

        Parameters:
            node: The currently visited node.
            obj: The object instance.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_module_node(self, *, node: ast.AST | ObjectNode, agent: Visitor | Inspector, **kwargs: Any) -> None:
        """Run when visiting a new module node during static/dynamic analysis.

        Parameters:
            node: The currently visited node.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_module_instance(
        self,
        *,
        node: ast.AST | ObjectNode,
        mod: Module,
        agent: Visitor | Inspector,
        **kwargs: Any,
    ) -> None:
        """Run when a Module has been created.

        Warning:
            This method runs while the object tree is still being constructed:
            data might be incomplete (class inheritance, alias resolution, etc.).
            Only hook onto this event if you know what you're doing.

        Parameters:
            node: The currently visited node.
            mod: The module instance.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_module(self, *, mod: Module, loader: GriffeLoader, **kwargs: Any) -> None:
        """Run on modules once the object tree has been fully constructed.

        Note:
            This method runs once the object tree has been fully constructed:
            data is therefore complete and you can safely hook onto this event.

        Parameters:
            mod: The module instance.
            loader: The loader currently in use.
            **kwargs: For forward-compatibility.
        """

    def on_module_members(
        self,
        *,
        node: ast.AST | ObjectNode,
        mod: Module,
        agent: Visitor | Inspector,
        **kwargs: Any,
    ) -> None:
        """Run when members of a Module have been loaded.

        Warning:
            This method runs while the object tree is still being constructed:
            data might be incomplete (class inheritance, alias resolution, etc.).
            Only hook onto this event if you know what you're doing.

        Parameters:
            node: The currently visited node.
            mod: The module instance.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_class_node(self, *, node: ast.AST | ObjectNode, agent: Visitor | Inspector, **kwargs: Any) -> None:
        """Run when visiting a new class node during static/dynamic analysis.

        Parameters:
            node: The currently visited node.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_class_instance(
        self,
        *,
        node: ast.AST | ObjectNode,
        cls: Class,
        agent: Visitor | Inspector,
        **kwargs: Any,
    ) -> None:
        """Run when a Class has been created.

        Warning:
            This method runs while the object tree is still being constructed:
            data might be incomplete (class inheritance, alias resolution, etc.).
            Only hook onto this event if you know what you're doing.

        Parameters:
            node: The currently visited node.
            cls: The class instance.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_class(self, *, cls: Class, loader: GriffeLoader, **kwargs: Any) -> None:
        """Run on classes once the object tree has been fully constructed.

        Note:
            This method runs once the object tree has been fully constructed:
            data is therefore complete and you can safely hook onto this event.

        Parameters:
            cls: The class instance.
            loader: The loader currently in use.
            **kwargs: For forward-compatibility.
        """

    def on_class_members(
        self,
        *,
        node: ast.AST | ObjectNode,
        cls: Class,
        agent: Visitor | Inspector,
        **kwargs: Any,
    ) -> None:
        """Run when members of a Class have been loaded.

        Warning:
            This method runs while the object tree is still being constructed:
            data might be incomplete (class inheritance, alias resolution, etc.).
            Only hook onto this event if you know what you're doing.

        Parameters:
            node: The currently visited node.
            cls: The class instance.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_function_node(self, *, node: ast.AST | ObjectNode, agent: Visitor | Inspector, **kwargs: Any) -> None:
        """Run when visiting a new function node during static/dynamic analysis.

        Parameters:
            node: The currently visited node.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_function_instance(
        self,
        *,
        node: ast.AST | ObjectNode,
        func: Function,
        agent: Visitor | Inspector,
        **kwargs: Any,
    ) -> None:
        """Run when a Function has been created.

        Warning:
            This method runs while the object tree is still being constructed:
            data might be incomplete (class inheritance, alias resolution, etc.).
            Only hook onto this event if you know what you're doing.

        Parameters:
            node: The currently visited node.
            func: The function instance.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_function(self, *, func: Function, loader: GriffeLoader, **kwargs: Any) -> None:
        """Run on functions once the object tree has been fully constructed.

        Note:
            This method runs once the object tree has been fully constructed:
            data is therefore complete and you can safely hook onto this event.

        Parameters:
            func: The function instance.
            loader: The loader currently in use.
            **kwargs: For forward-compatibility.
        """

    def on_attribute_node(self, *, node: ast.AST | ObjectNode, agent: Visitor | Inspector, **kwargs: Any) -> None:
        """Run when visiting a new attribute node during static/dynamic analysis.

        Parameters:
            node: The currently visited node.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_attribute_instance(
        self,
        *,
        node: ast.AST | ObjectNode,
        attr: Attribute,
        agent: Visitor | Inspector,
        **kwargs: Any,
    ) -> None:
        """Run when an Attribute has been created.

        Warning:
            This method runs while the object tree is still being constructed:
            data might be incomplete (class inheritance, alias resolution, etc.).
            Only hook onto this event if you know what you're doing.

        Parameters:
            node: The currently visited node.
            attr: The attribute instance.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_attribute(self, *, attr: Attribute, loader: GriffeLoader, **kwargs: Any) -> None:
        """Run on attributes once the object tree has been fully constructed.

        Note:
            This method runs once the object tree has been fully constructed:
            data is therefore complete and you can safely hook onto this event.

        Parameters:
            attr: The attribute instance.
            loader: The loader currently in use.
            **kwargs: For forward-compatibility.
        """

    def on_type_alias_node(self, *, node: ast.AST | ObjectNode, agent: Visitor | Inspector, **kwargs: Any) -> None:
        """Run when visiting a new type alias node during static/dynamic analysis.

        Parameters:
            node: The currently visited node.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_type_alias_instance(
        self,
        *,
        node: ast.AST | ObjectNode,
        type_alias: TypeAlias,
        agent: Visitor | Inspector,
        **kwargs: Any,
    ) -> None:
        """Run when a TypeAlias has been created.

        Warning:
            This method runs while the object tree is still being constructed:
            data might be incomplete (class inheritance, alias resolution, etc.).
            Only hook onto this event if you know what you're doing.

        Parameters:
            node: The currently visited node.
            type_alias: The type alias instance.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """

    def on_type_alias(self, *, type_alias: TypeAlias, loader: GriffeLoader, **kwargs: Any) -> None:
        """Run on type aliases once the object tree has been fully constructed.

        Note:
            This method runs once the object tree has been fully constructed:
            data is therefore complete and you can safely hook onto this event.

        Parameters:
            type_alias: The type alias instance.
            loader: The loader currently in use.
            **kwargs: For forward-compatibility.
        """

    def on_alias_instance(
        self,
        *,
        node: ast.AST | ObjectNode,
        alias: Alias,
        agent: Visitor | Inspector,
        **kwargs: Any,
    ) -> None:
        """Run when an Alias has been created.

        Warning:
            This method runs while the object tree is still being constructed:
            data might be incomplete (class inheritance, alias resolution, etc.).
            Only hook onto this event if you know what you're doing.

        Parameters:
            node: The currently visited node.
            alias: The alias instance.
            agent: The analysis agent currently running.
            **kwargs: For forward-compatibility.
        """
        if getattr(self, "__old_on_alias", False):
            self.on_alias(node=node, alias=alias, agent=agent, **kwargs)

    def on_alias(self, *, alias: Alias, loader: GriffeLoader, **kwargs: Any) -> None:
        """Run on aliases once the object tree has been fully constructed.

        Note:
            This method runs once the object tree has been fully constructed:
            data is therefore complete and you can safely hook onto this event.

        Parameters:
            alias: The alias instance.
            loader: The loader currently in use.
            **kwargs: For forward-compatibility.
        """

    def on_package(self, *, pkg: Module, loader: GriffeLoader, **kwargs: Any) -> None:
        """Run when a package has been completely loaded.

        Note:
            This method runs once the object tree has been fully constructed:
            data is therefore complete and you can safely hook onto this event.

        Parameters:
            pkg: The package (Module) instance.
            loader: The loader currently in use.
            **kwargs: For forward-compatibility.
        """


LoadableExtensionType = str | dict[str, Any] | Extension | type[Extension]
"""All the types that can be passed to `load_extensions`."""


class Extensions:
    """This class helps iterating on extensions that should run at different times."""

    def __init__(self, *extensions: Extension) -> None:
        """Initialize the extensions container.

        Parameters:
            *extensions: The extensions to add.
        """
        self._extensions: list[Extension] = []
        self.add(*extensions)

    def add(self, *extensions: Extension) -> None:
        """Add extensions to this container.

        Parameters:
            *extensions: The extensions to add.
        """
        for extension in extensions:
            self._extensions.append(extension)

    def _noop(self, **kwargs: Any) -> None:
        """No-op method for extension hooks."""

    def call(self, event: str, **kwargs: Any) -> None:
        """Call the extension hook for the given event.

        Parameters:
            event: The triggered event.
            **kwargs: Arguments passed to the hook.
        """
        for extension in self._extensions:
            getattr(extension, event, self._noop)(**kwargs)


builtin_extensions: set[str] = {
    "dataclasses",
    "unpack_typeddict",
}
"""The names of built-in Griffe extensions."""


def _load_extension_path(path: str) -> ModuleType:
    module_name = os.path.basename(path).rsplit(".", 1)[0]  # noqa: PTH119
    spec = spec_from_file_location(module_name, path)
    if not spec:
        raise ExtensionNotLoadedError(f"Could not import module from path '{path}'")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # ty:ignore[unresolved-attribute]
    return module


def _load_extension(
    extension: str | dict[str, Any] | Extension | type[Extension],
) -> Extension | list[Extension]:
    """Load a configured extension.

    Parameters:
        extension: An extension, with potential configuration options.

    Raises:
        ExtensionNotLoadedError: When the extension cannot be loaded,
            either because the module is not found, or because it does not expose
            the Extension attribute. ImportError will bubble up so users can see
            the traceback.

    Returns:
        An extension instance.
    """
    ext_object = None

    # If it's already an extension instance, return it.
    if isinstance(extension, Extension):
        return extension

    # If it's an extension class, instantiate it (without options) and return it.
    if isclass(extension) and issubclass(extension, Extension):
        return extension()

    # If it's a dictionary, we expect the only key to be an import path
    # and the value to be a dictionary of options.
    if isinstance(extension, dict):
        import_path, options = next(iter(extension.items()))
        # Force path to be a string, as it could have been passed from `mkdocs.yml`,
        # using the custom YAML tag `!relative`, which gives an instance of MkDocs
        # path placeholder classes, which are not iterable.
        import_path = str(import_path)

    # Otherwise we consider it's an import path, without options.
    else:
        import_path = str(extension)
        options = {}

    # If the import path contains a colon, we split into path and class name.
    colons = import_path.count(":")
    # Special case for The Annoying Operating System.
    if colons > 1 or (colons and ":" not in Path(import_path).drive):
        import_path, extension_name = import_path.rsplit(":", 1)
    else:
        extension_name = None

    # If the import path corresponds to a built-in extension, expand it.
    if import_path in builtin_extensions:
        import_path = f"griffe._internal.extensions.{import_path}"
    # If the import path is a path to an existing file, load it.
    elif os.path.exists(import_path):  # noqa: PTH110
        try:
            ext_object = _load_extension_path(import_path)
        except ImportError as error:
            raise ExtensionNotLoadedError(f"Extension module '{import_path}' could not be found") from error

    # If the extension wasn't loaded yet, we consider the import path
    # to be a Python dotted path like `package.module` or `package.module.Extension`.
    if not ext_object:
        try:
            ext_object = dynamic_import(import_path)
        except ModuleNotFoundError as error:
            raise ExtensionNotLoadedError(f"Extension module '{import_path}' could not be found") from error
        except ImportError as error:
            raise ExtensionNotLoadedError(f"Error while importing extension '{import_path}': {error}") from error

    # If the loaded object is an extension class, instantiate it with options and return it.
    if isclass(ext_object) and issubclass(ext_object, Extension):
        return ext_object(**options)

    # Otherwise the loaded object is a module, so we get the extension class by name,
    # instantiate it with options and return it.
    if extension_name:
        try:
            return getattr(ext_object, extension_name)(**options)
        except AttributeError as error:
            raise ExtensionNotLoadedError(
                f"Extension module '{import_path}' has no '{extension_name}' attribute",
            ) from error

    # No class name was specified so we search all extension classes in the module,
    # instantiate each with the same options, and return them.
    extensions = [
        obj for obj in vars(ext_object).values() if isclass(obj) and issubclass(obj, Extension) and obj is not Extension
    ]
    return [ext(**options) for ext in extensions]


def load_extensions(*exts: LoadableExtensionType) -> Extensions:
    """Load configured extensions.

    Parameters:
        exts: Extensions with potential configuration options.

    Returns:
        An extensions container.
    """
    extensions = Extensions()

    for extension in exts:
        ext = _load_extension(extension)
        if isinstance(ext, list):
            extensions.add(*ext)  # ty:ignore[invalid-argument-type]
        else:
            extensions.add(ext)

    # TODO: Deprecate and remove at some point?
    # Always add our built-in dataclasses extension.
    from griffe._internal.extensions.dataclasses import DataclassesExtension  # noqa: PLC0415

    for ext in extensions._extensions:
        if type(ext) is DataclassesExtension:
            break
    else:
        extensions.add(*_load_extension("dataclasses"))  # ty:ignore[not-iterable]

    return extensions
