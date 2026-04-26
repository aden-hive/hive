# This module contains utilities to merge stubs data and concrete data.

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from griffe._internal.exceptions import AliasResolutionError, CyclicAliasError
from griffe._internal.expressions import Expr
from griffe._internal.logger import logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from griffe._internal.models import Attribute, Class, Function, Module, Object, TypeAlias


def _merge_module_stubs(module: Module, stubs: Module) -> None:
    _merge_stubs_docstring(module, stubs)
    _merge_stubs_overloads(module, stubs)
    _merge_stubs_members(module, stubs)


def _merge_class_stubs(class_: Class, stubs: Class) -> None:
    _merge_stubs_docstring(class_, stubs)
    _merge_stubs_overloads(class_, stubs)
    _merge_stubs_type_parameters(class_, stubs)
    _merge_stubs_members(class_, stubs)


def _merge_function_stubs(function: Function, stubs: Function) -> None:
    _merge_stubs_docstring(function, stubs)
    for parameter in stubs.parameters:
        with suppress(KeyError):
            function.parameters[parameter.name].annotation = parameter.annotation
    function.returns = stubs.returns
    _merge_stubs_type_parameters(function, stubs)


def _merge_attribute_stubs(attribute: Attribute, stubs: Attribute) -> None:
    _merge_stubs_docstring(attribute, stubs)
    attribute.annotation = stubs.annotation
    if stubs.value not in (None, "..."):
        attribute.value = stubs.value


def _merge_type_alias_stubs(type_alias: TypeAlias, stubs: TypeAlias) -> None:
    _merge_stubs_docstring(type_alias, stubs)
    _merge_stubs_type_parameters(type_alias, stubs)


def _merge_stubs_docstring(obj: Object, stubs: Object) -> None:
    if not obj.docstring and stubs.docstring:
        obj.docstring = stubs.docstring


def _merge_stubs_type_parameters(obj: Class | Function | TypeAlias, stubs: Class | Function | TypeAlias) -> None:
    if not obj.type_parameters and stubs.type_parameters:
        obj.type_parameters = stubs.type_parameters


def _merge_stubs_overloads(obj: Module | Class, stubs: Module | Class) -> None:
    for function_name, overloads in list(stubs.overloads.items()):
        if overloads:
            with suppress(KeyError):
                _merge_overload_annotations(obj.get_member(function_name), overloads)
        del stubs.overloads[function_name]


def _merge_annotations(annotations: Sequence[Expr]) -> Expr | None:
    if len(annotations) == 1:
        return annotations[0]
    if annotations:
        return Expr._to_binop(annotations, op="|")
    return None


def _merge_overload_annotations(function: Function, overloads: list[Function]) -> None:
    function.overloads = overloads
    for parameter in function.parameters:
        if parameter.annotation is None:
            seen = set()
            annotations = []
            for overload in overloads:
                with suppress(KeyError):
                    annotation = overload.parameters[parameter.name].annotation
                    str_annotation = str(annotation)
                    if isinstance(annotation, Expr) and str_annotation not in seen:
                        annotations.append(annotation)
                        seen.add(str_annotation)
            parameter.annotation = _merge_annotations(annotations)
    if function.returns is None:
        seen = set()
        return_annotations = []
        for overload in overloads:
            str_annotation = str(overload.returns)
            if isinstance(overload.returns, Expr) and str_annotation not in seen:
                return_annotations.append(overload.returns)
                seen.add(str_annotation)
        function.returns = _merge_annotations(return_annotations)


def _merge_stubs_members(obj: Module | Class, stubs: Module | Class) -> None:
    # Merge imports to later know if objects coming from the stubs were imported.
    obj.imports.update(stubs.imports)

    # Override exports to later know if objects coming from the stubs were exported.
    if stubs.exports is not None:
        obj.exports = stubs.exports

    for member_name, stub_member in stubs.members.items():
        if member_name in obj.members:
            # We don't merge imported stub objects that already exist in the concrete module.
            # Stub objects must be defined where they are exposed in the concrete package,
            # not be imported from other stub modules.
            if stub_member.is_alias:
                continue
            obj_member = obj.get_member(member_name)
            with suppress(AliasResolutionError, CyclicAliasError):
                # An object's canonical location can differ from its equivalent stub location.
                # Devs usually declare stubs at the public location of the corresponding object,
                # not the canonical one. Therefore, we must allow merging stubs into the target of an alias,
                # as long as the stub and target are of the same kind.
                if obj_member.kind is not stub_member.kind:
                    # If the stub and the target are not of the same kind, prefer the
                    # stub over the target.
                    logger.debug(
                        "Source object `%s` will be overwritten by stub object.",
                        obj_member.path,
                    )
                    obj.set_member(stub_member.name, stub_member)
                elif obj_member.is_module:
                    _merge_module_stubs(obj_member, stub_member)  # ty:ignore[invalid-argument-type]
                elif obj_member.is_class:
                    _merge_class_stubs(obj_member, stub_member)  # ty:ignore[invalid-argument-type]
                elif obj_member.is_function:
                    _merge_function_stubs(obj_member, stub_member)  # ty:ignore[invalid-argument-type]
                elif obj_member.is_attribute:
                    _merge_attribute_stubs(obj_member, stub_member)  # ty:ignore[invalid-argument-type]
                elif obj_member.is_type_alias:
                    _merge_type_alias_stubs(obj_member, stub_member)  # ty:ignore[invalid-argument-type]
        else:
            stub_member.runtime = False
            obj.set_member(member_name, stub_member)


def merge_stubs(mod1: Module, mod2: Module) -> Module:
    """Merge stubs into a module.

    Parameters:
        mod1: A regular module or stubs module.
        mod2: A regular module or stubs module.

    Raises:
        ValueError: When both modules are regular modules (no stubs is passed).

    Returns:
        The regular module.
    """
    logger.debug("Trying to merge %s and %s", mod1.filepath, mod2.filepath)
    if mod1.filepath.suffix == ".pyi":  # ty:ignore[unresolved-attribute]
        stubs = mod1
        module = mod2
    elif mod2.filepath.suffix == ".pyi":  # ty:ignore[unresolved-attribute]
        stubs = mod2
        module = mod1
    else:
        raise ValueError("cannot merge regular (non-stubs) modules together")
    _merge_module_stubs(module, stubs)
    return module
