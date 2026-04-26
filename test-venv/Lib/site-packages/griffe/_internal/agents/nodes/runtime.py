# This module contains utilities for extracting information from runtime objects.

from __future__ import annotations

import inspect
import sys
import typing
from functools import cached_property
from types import GetSetDescriptorType, ModuleType
from typing import TYPE_CHECKING, Any, ClassVar

from griffe._internal.enumerations import ObjectKind
from griffe._internal.logger import logger

if TYPE_CHECKING:
    import types
    from collections.abc import Sequence

_TYPING_MODULES: tuple[types.ModuleType, ...]
try:
    import typing_extensions
except ImportError:
    _TYPING_MODULES = (typing,)
else:
    _TYPING_MODULES = (typing, typing_extensions)


_builtin_module_names = {_.lstrip("_") for _ in sys.builtin_module_names}
_cyclic_relationships = {
    ("os", "nt"),
    ("os", "posix"),
    ("numpy.core._multiarray_umath", "numpy.core.multiarray"),
}


def _same_components(a: str, b: str, /) -> bool:
    return [cpn.lstrip("_") for cpn in a.split(".")] == [cpn.lstrip("_") for cpn in b.split(".")]


class ObjectNode:
    """Helper class to represent an object tree.

    It's not really a tree but more a backward-linked list:
    each node has a reference to its parent, but not to its child (for simplicity purposes and to avoid bugs).

    Each node stores an object, its name, and a reference to its parent node.
    """

    exclude_specials: ClassVar[set[str]] = {"__builtins__", "__loader__", "__spec__"}
    """Low level attributes known to cause issues when resolving aliases."""

    def __init__(self, obj: Any, name: str, parent: ObjectNode | None = None) -> None:
        """Initialize the object.

        Parameters:
            obj: A Python object.
            name: The object's name.
            parent: The object's parent node.
        """
        # Unwrap object.
        try:
            obj = inspect.unwrap(obj)
        except Exception as error:  # noqa: BLE001
            # `inspect.unwrap` at some point runs `hasattr(obj, "__wrapped__")`,
            # which triggers the `__getattr__` method of the object, which in
            # turn can raise various exceptions. Probably not just `__getattr__`.
            # See https://github.com/pawamoy/pytkdocs/issues/45.
            logger.debug("Could not unwrap %s: %r", name, error)

        # Unwrap cached properties (`inspect.unwrap` doesn't do that).
        if isinstance(obj, cached_property):
            is_cached_property = True
            obj = obj.func
        else:
            is_cached_property = False

        self.obj: Any = obj
        """The actual Python object."""
        self.name: str = name
        """The Python object's name."""
        self.parent: ObjectNode | None = parent
        """The parent node."""
        self.is_cached_property: bool = is_cached_property
        """Whether this node's object is a cached property."""

    def __repr__(self) -> str:
        return f"ObjectNode(name={self.name!r})"

    @property
    def path(self) -> str:
        """The object's (Python) path."""
        if self.parent is None:
            return self.name
        return f"{self.parent.path}.{self.name}"

    @property
    def module(self) -> ObjectNode:
        """The object's module, fetched from the node tree."""
        if self.is_module:
            return self
        if self.parent is not None:
            return self.parent.module
        raise ValueError(f"Object node {self.path} does not have a parent module")

    @property
    def module_path(self) -> str | None:
        """The object's module path."""
        try:
            module = self.obj.__module__
        except AttributeError:
            try:
                module = inspect.getmodule(self.obj) or self.module.obj
            except ValueError:
                return None
            try:
                return module.__spec__.name  # ty:ignore[unresolved-attribute]
            except AttributeError:
                return getattr(module, "__name__", None)
        else:
            # Some libraries mistakenly set `__module__` to a module object instead of a string.
            # Handle this case specifically, but do not cast any other object to a string.
            if isinstance(module, ModuleType):
                logger.debug(
                    "Object %s has its `__module__` attribute set to a module object: "
                    "it must be a string instead (the module fully qualified name). "
                    "Please report to the maintainers of this library.",
                    self.path,
                )
                return getattr(module, "__qualname__", getattr(module, "__name__", None))
            if isinstance(module, str):
                return module
            logger.debug(
                "Object %s has its `__module__` attribute set to a %s object: "
                "it must be a string instead (the module fully qualified name). "
                "Please report to the maintainers of this library.",
                self.path,
                getattr(type(module), "__name__", str(type(module))),
            )
            return None

    @property
    def kind(self) -> ObjectKind:
        """The kind of this node."""
        if self.is_module:
            return ObjectKind.MODULE
        if self.is_class:
            return ObjectKind.CLASS
        if self.is_staticmethod:
            return ObjectKind.STATICMETHOD
        if self.is_classmethod:
            return ObjectKind.CLASSMETHOD
        if self.is_cached_property:
            return ObjectKind.CACHED_PROPERTY
        if self.is_method:
            return ObjectKind.METHOD
        if self.is_builtin_method:
            return ObjectKind.BUILTIN_METHOD
        if self.is_coroutine:
            return ObjectKind.COROUTINE
        if self.is_builtin_function:
            return ObjectKind.BUILTIN_FUNCTION
        if self.is_method_descriptor:
            return ObjectKind.METHOD_DESCRIPTOR
        if self.is_function:
            return ObjectKind.FUNCTION
        if self.is_getset_descriptor:
            return ObjectKind.GETSET_DESCRIPTOR
        if self.is_property:
            return ObjectKind.PROPERTY
        if self.is_type_alias:
            return ObjectKind.TYPE_ALIAS
        return ObjectKind.ATTRIBUTE

    @cached_property
    def children(self) -> Sequence[ObjectNode]:
        """The children of this node."""
        children = []
        for name, member in inspect.getmembers(self.obj):
            if self._pick_member(name, member):
                children.append(ObjectNode(member, name, parent=self))
        return children

    @cached_property
    def is_module(self) -> bool:
        """Whether this node's object is a module."""
        return inspect.ismodule(self.obj)

    @cached_property
    def is_class(self) -> bool:
        """Whether this node's object is a class."""
        return inspect.isclass(self.obj)

    @cached_property
    def is_function(self) -> bool:
        """Whether this node's object is a function."""
        # `inspect.isfunction` returns `False` for partials.
        return inspect.isfunction(self.obj) or (callable(self.obj) and not self.is_class)

    @cached_property
    def is_type_alias(self) -> bool:
        """Whether this node's object is a type alias."""
        return isinstance(
            self.obj,
            tuple(module.TypeAliasType for module in _TYPING_MODULES if hasattr(module, "TypeAliasType")),
        )

    @cached_property
    def is_builtin_function(self) -> bool:
        """Whether this node's object is a builtin function."""
        return inspect.isbuiltin(self.obj)

    @cached_property
    def is_coroutine(self) -> bool:
        """Whether this node's object is a coroutine."""
        return inspect.iscoroutinefunction(self.obj)

    @cached_property
    def is_getset_descriptor(self) -> bool:
        """Whether this node's object is a get/set descriptor."""
        return isinstance(self.obj, GetSetDescriptorType)

    @cached_property
    def is_property(self) -> bool:
        """Whether this node's object is a property."""
        return isinstance(self.obj, property) or self.is_cached_property

    @cached_property
    def parent_is_class(self) -> bool:
        """Whether the object of this node's parent is a class."""
        return bool(self.parent and self.parent.is_class)

    @cached_property
    def is_method(self) -> bool:
        """Whether this node's object is a method."""
        function_type = type(lambda: None)
        return self.parent_is_class and isinstance(self.obj, function_type)

    @cached_property
    def is_method_descriptor(self) -> bool:
        """Whether this node's object is a method descriptor.

        Built-in methods (e.g. those implemented in C/Rust) are often
        method descriptors, rather than normal methods.
        """
        return inspect.ismethoddescriptor(self.obj)

    @cached_property
    def is_builtin_method(self) -> bool:
        """Whether this node's object is a builtin method."""
        return self.is_builtin_function and self.parent_is_class

    @cached_property
    def is_staticmethod(self) -> bool:
        """Whether this node's object is a staticmethod."""
        if self.parent is None:
            return False
        try:
            self_from_parent = self.parent.obj.__dict__.get(self.name, None)
        except AttributeError:
            return False
        return self.parent_is_class and isinstance(self_from_parent, staticmethod)

    @cached_property
    def is_classmethod(self) -> bool:
        """Whether this node's object is a classmethod."""
        if self.parent is None:
            return False
        try:
            self_from_parent = self.parent.obj.__dict__.get(self.name, None)
        except AttributeError:
            return False
        return self.parent_is_class and isinstance(self_from_parent, classmethod)

    @cached_property
    def is_attribute(self) -> bool:
        """Whether this node's object is an attribute."""
        return self.kind is ObjectKind.ATTRIBUTE

    @cached_property
    def _ids(self) -> set[int]:
        if self.parent is None:
            return {id(self.obj)}
        return {id(self.obj)} | self.parent._ids

    def _pick_member(self, name: str, member: Any) -> bool:
        return (
            name not in self.exclude_specials
            and member is not type
            and member is not object
            and id(member) not in self._ids
            and name in vars(self.obj)
        )

    @cached_property
    def alias_target_path(self) -> str | None:
        """Alias target path of this node, if the node should be an alias."""
        # Top-level objects can't have been imported.
        if self.parent is None:
            return None

        # We can't ever know if an attribute was imported.
        if self.is_attribute:
            return None

        # Get the path of the module the child object was declared in.
        child_module_path = self.module_path
        if not child_module_path:
            return None

        # Get the path of the module the parent object was declared in.
        parent_module_path = self.parent.module_path
        if not parent_module_path:
            return None

        # Special cases: break cycles.
        if (parent_module_path, child_module_path) in _cyclic_relationships:
            return None

        # If the current object was declared in the same module as its parent,
        # or in a module with the same path components but starting/not starting with underscores,
        # we don't want to alias it. Examples: (a, a), (a, _a), (_a, a), (_a, _a),
        # (a.b, a.b), (a.b, _a.b), (_a._b, a.b), (a._b, _a.b), etc..
        if _same_components(parent_module_path, child_module_path):
            return None

        # If the current object was declared in any other module, we alias it.
        # We remove the leading underscore from the child module path
        # if it's a built-in module (e.g. _io -> io). That's because objects
        # in built-in modules inconsistently lie about their module path,
        # so we prefer to use the non-underscored (public) version,
        # as users most likely import from the public module and not the private one.
        if child_module_path.lstrip("_") in _builtin_module_names:
            child_module_path = child_module_path.lstrip("_")

        # Child object is a module, return its path directly.
        if self.is_module:
            return child_module_path

        # Rebuild the child object path.
        child_name = getattr(self.obj, "__qualname__", self.path[len(self.module.path) + 1 :])
        return f"{child_module_path}.{child_name}"
