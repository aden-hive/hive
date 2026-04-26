# This module contains helpers. They simplify programmatic use of Griffe,
# for example to load data from strings or to create temporary packages.
# They are particularly useful for our own tests suite.

from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import invalidate_caches
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

from griffe._internal.agents.inspector import inspect
from griffe._internal.agents.visitor import visit
from griffe._internal.collections import LinesCollection
from griffe._internal.loader import load
from griffe._internal.models import Module, Object

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from griffe._internal.collections import ModulesCollection
    from griffe._internal.docstrings.parsers import DocstringOptions, DocstringStyle
    from griffe._internal.enumerations import Parser
    from griffe._internal.extensions.base import Extensions

_TMPDIR_PREFIX = "griffe_"


@dataclass
class TmpPackage:
    """A temporary package.

    The `tmpdir` and `path` parameters can be passed as relative path.
    They will be resolved to absolute paths after initialization.
    """

    tmpdir: Path
    """The temporary directory containing the package."""
    name: str
    """The package name, as to dynamically import it."""
    path: Path
    """The package path."""

    def __post_init__(self) -> None:
        self.tmpdir = self.tmpdir.resolve()
        self.path = self.path.resolve()


@contextmanager
def temporary_pyfile(code: str, *, module_name: str = "module") -> Iterator[tuple[str, Path]]:
    """Create a Python file containing the given code in a temporary directory.

    Parameters:
        code: The code to write to the temporary file.
        module_name: The name of the temporary module.

    Yields:
        module_name: The module name, as to dynamically import it.
        module_path: The module path.
    """
    with tempfile.TemporaryDirectory(prefix=_TMPDIR_PREFIX) as tmpdir:
        tmpfile = Path(tmpdir) / f"{module_name}.py"
        tmpfile.write_text(dedent(code), encoding="utf8")
        yield module_name, tmpfile


@contextmanager
def temporary_pypackage(
    package: str,
    modules: Sequence[str] | Mapping[str, str] | None = None,
    *,
    init: bool = True,
    inits: bool = True,
) -> Iterator[TmpPackage]:
    """Create a package containing the given modules in a temporary directory.

    Parameters:
        package: The package name. Example: `"a"` gives
            a package named `a`, while `"a/b"` gives a namespace package
            named `a` with a package inside named `b`.
            If `init` is false, then `b` is also a namespace package.
        modules: Additional modules to create in the package.
            If a list, simply touch the files: `["b.py", "c/d.py", "e/f"]`.
            If a dict, keys are the file names and values their contents:
            `{"b.py": "b = 1", "c/d.py": "print('hey from c')"}`.
        init: Whether to create an `__init__` module in the top package.
        inits: Whether to create `__init__` modules in subpackages.

    Yields:
        A temporary package.
    """
    modules = modules or {}
    if isinstance(modules, list):
        modules = dict.fromkeys(modules, "")
    mkdir_kwargs = {"parents": True, "exist_ok": True}
    with tempfile.TemporaryDirectory(prefix=_TMPDIR_PREFIX) as tmpdir:
        tmpdirpath = Path(tmpdir)
        package_name = ".".join(Path(package).parts)
        package_path = tmpdirpath / package
        package_path.mkdir(**mkdir_kwargs)
        if init:
            package_path.joinpath("__init__.py").touch()
        for module_name, module_contents in modules.items():  # ty:ignore[unresolved-attribute]
            current_path = package_path
            for part in Path(module_name).parts:
                if part.endswith((".py", ".pyi")):
                    current_path.joinpath(part).write_text(dedent(module_contents), encoding="utf8")
                else:
                    current_path /= part
                    current_path.mkdir(**mkdir_kwargs)
                    if inits:
                        current_path.joinpath("__init__.py").touch()
        yield TmpPackage(tmpdirpath, package_name, package_path)


@contextmanager
def temporary_visited_package(
    package: str,
    modules: Sequence[str] | Mapping[str, str] | None = None,
    *,
    init: bool = True,
    inits: bool = True,
    extensions: Extensions | None = None,
    docstring_parser: DocstringStyle | Parser | None = None,
    docstring_options: DocstringOptions | None = None,
    lines_collection: LinesCollection | None = None,
    modules_collection: ModulesCollection | None = None,
    allow_inspection: bool = False,
    store_source: bool = True,
    resolve_aliases: bool = False,
    resolve_external: bool | None = None,
    resolve_implicit: bool = False,
    search_sys_path: bool = False,
) -> Iterator[Module]:
    """Create and visit a temporary package.

    Parameters:
        package: The package name. Example: `"a"` gives
            a package named `a`, while `"a/b"` gives a namespace package
            named `a` with a package inside named `b`.
            If `init` is false, then `b` is also a namespace package.
        modules: Additional modules to create in the package.
            If a list, simply touch the files: `["b.py", "c/d.py", "e/f"]`.
            If a dict, keys are the file names and values their contents:
            `{"b.py": "b = 1", "c/d.py": "print('hey from c')"}`.
        init: Whether to create an `__init__` module in the top package.
        inits: Whether to create `__init__` modules in subpackages.
        extensions: The extensions to use.
        docstring_parser: The docstring parser to use. By default, no parsing is done.
        docstring_options: Docstring parsing options.
        lines_collection: A collection of source code lines.
        modules_collection: A collection of modules.
        allow_inspection: Whether to allow inspecting modules when visiting them is not possible.
        store_source: Whether to store code source in the lines collection.
        resolve_aliases: Whether to resolve aliases.
        resolve_external: Whether to try to load unspecified modules to resolve aliases.
            Default value (`None`) means to load external modules only if they are the private sibling
            or the origin module (for example when `ast` imports from `_ast`).
        resolve_implicit: When false, only try to resolve an alias if it is explicitly exported.
        search_sys_path: Whether to search the system paths for the package.

    Yields:
        A module.
    """
    search_paths = sys.path if search_sys_path else []
    with temporary_pypackage(package, modules, init=init, inits=inits) as tmp_package:
        yield load(
            tmp_package.name,
            search_paths=[tmp_package.tmpdir, *search_paths],
            extensions=extensions,
            docstring_parser=docstring_parser,
            docstring_options=docstring_options,
            lines_collection=lines_collection,
            modules_collection=modules_collection,
            allow_inspection=allow_inspection,
            store_source=store_source,
            resolve_aliases=resolve_aliases,
            resolve_external=resolve_external,
            resolve_implicit=resolve_implicit,
            force_inspection=False,
        )


@contextmanager
def temporary_inspected_package(
    package: str,
    modules: Sequence[str] | Mapping[str, str] | None = None,
    *,
    init: bool = True,
    inits: bool = True,
    extensions: Extensions | None = None,
    docstring_parser: DocstringStyle | Parser | None = None,
    docstring_options: DocstringOptions | None = None,
    lines_collection: LinesCollection | None = None,
    modules_collection: ModulesCollection | None = None,
    allow_inspection: bool = True,
    store_source: bool = True,
    resolve_aliases: bool = False,
    resolve_external: bool | None = None,
    resolve_implicit: bool = False,
    search_sys_path: bool = False,
) -> Iterator[Module]:
    """Create and inspect a temporary package.

    Parameters:
        package: The package name. Example: `"a"` gives
            a package named `a`, while `"a/b"` gives a namespace package
            named `a` with a package inside named `b`.
            If `init` is false, then `b` is also a namespace package.
        modules: Additional modules to create in the package.
            If a list, simply touch the files: `["b.py", "c/d.py", "e/f"]`.
            If a dict, keys are the file names and values their contents:
            `{"b.py": "b = 1", "c/d.py": "print('hey from c')"}`.
        init: Whether to create an `__init__` module in the top package.
        inits: Whether to create `__init__` modules in subpackages.
        extensions: The extensions to use.
        docstring_parser: The docstring parser to use. By default, no parsing is done.
        docstring_options: Docstring parsing options.
        lines_collection: A collection of source code lines.
        modules_collection: A collection of modules.
        allow_inspection: Whether to allow inspecting modules.
        store_source: Whether to store code source in the lines collection.
        resolve_aliases: Whether to resolve aliases.
        resolve_external: Whether to try to load unspecified modules to resolve aliases.
            Default value (`None`) means to load external modules only if they are the private sibling
            or the origin module (for example when `ast` imports from `_ast`).
        resolve_implicit: When false, only try to resolve an alias if it is explicitly exported.
        search_sys_path: Whether to search the system paths for the package.

    Yields:
        A module.
    """
    search_paths = sys.path if search_sys_path else []
    with temporary_pypackage(package, modules, init=init, inits=inits) as tmp_package:
        try:
            yield load(
                tmp_package.name,
                search_paths=[tmp_package.tmpdir, *search_paths],
                extensions=extensions,
                docstring_parser=docstring_parser,
                docstring_options=docstring_options,
                lines_collection=lines_collection,
                modules_collection=modules_collection,
                allow_inspection=allow_inspection,
                store_source=store_source,
                resolve_aliases=resolve_aliases,
                resolve_external=resolve_external,
                resolve_implicit=resolve_implicit,
                force_inspection=True,
            )
        finally:
            for name in tuple(sys.modules.keys()):
                if name == package or name.startswith(f"{package}."):
                    sys.modules.pop(name, None)
            invalidate_caches()


@contextmanager
def temporary_visited_module(
    code: str,
    *,
    module_name: str = "module",
    extensions: Extensions | None = None,
    parent: Module | None = None,
    docstring_parser: DocstringStyle | Parser | None = None,
    docstring_options: DocstringOptions | None = None,
    lines_collection: LinesCollection | None = None,
    modules_collection: ModulesCollection | None = None,
) -> Iterator[Module]:
    """Create and visit a temporary module with the given code.

    Parameters:
        code: The code of the module.
        module_name: The name of the temporary module.
        extensions: The extensions to use when visiting the AST.
        parent: The optional parent of this module.
        docstring_parser: The docstring parser to use. By default, no parsing is done.
        docstring_options: Docstring parsing options.
        lines_collection: A collection of source code lines.
        modules_collection: A collection of modules.

    Yields:
        The visited module.
    """
    code = dedent(code)
    with temporary_pyfile(code, module_name=module_name) as (_, path):
        lines_collection = lines_collection or LinesCollection()
        lines_collection[path] = code.splitlines()
        module = visit(
            module_name,
            filepath=path,
            code=code,
            extensions=extensions,
            parent=parent,
            docstring_parser=docstring_parser,
            docstring_options=docstring_options,
            lines_collection=lines_collection,
            modules_collection=modules_collection,
        )
        module.modules_collection[module_name] = module
        yield module


@contextmanager
def temporary_inspected_module(
    code: str,
    *,
    module_name: str = "module",
    import_paths: list[Path] | None = None,
    extensions: Extensions | None = None,
    parent: Module | None = None,
    docstring_parser: DocstringStyle | Parser | None = None,
    docstring_options: DocstringOptions | None = None,
    lines_collection: LinesCollection | None = None,
    modules_collection: ModulesCollection | None = None,
) -> Iterator[Module]:
    """Create and inspect a temporary module with the given code.

    Parameters:
        code: The code of the module.
        module_name: The name of the temporary module.
        import_paths: Paths to import the module from.
        extensions: The extensions to use when visiting the AST.
        parent: The optional parent of this module.
        docstring_parser: The docstring parser to use. By default, no parsing is done.
        docstring_options: Docstring parsing options.
        lines_collection: A collection of source code lines.
        modules_collection: A collection of modules.

    Yields:
        The inspected module.
    """
    with temporary_pyfile(code, module_name=module_name) as (_, path):
        lines_collection = lines_collection or LinesCollection()
        lines_collection[path] = code.splitlines()
        try:
            module = inspect(
                module_name,
                filepath=path,
                import_paths=import_paths,
                extensions=extensions,
                parent=parent,
                docstring_parser=docstring_parser,
                docstring_options=docstring_options,
                lines_collection=lines_collection,
                modules_collection=modules_collection,
            )
            module.modules_collection[module_name] = module
            yield module
        finally:
            if module_name in sys.modules:
                del sys.modules[module_name]
            invalidate_caches()


def vtree(*objects: Object, return_leaf: bool = False) -> Object:
    """Link objects together, vertically.

    Parameters:
        *objects: A sequence of objects. The first one is at the top of the tree.
        return_leaf: Whether to return the leaf instead of the root.

    Raises:
        ValueError: When no objects are provided.

    Returns:
        The top or leaf object.
    """
    if not objects:
        raise ValueError("At least one object must be provided")
    top = objects[0]
    leaf = top
    for obj in objects[1:]:
        leaf.set_member(obj.name, obj)
        leaf = obj
    return leaf if return_leaf else top


def htree(*objects: Object) -> Object:
    """Link objects together, horizontally.

    Parameters:
        *objects: A sequence of objects. All objects starting at the second become members of the first.

    Raises:
        ValueError: When no objects are provided.

    Returns:
        The first given object, with all the other objects as members of it.
    """
    if not objects:
        raise ValueError("At least one object must be provided")
    top = objects[0]
    for obj in objects[1:]:
        top.set_member(obj.name, obj)
    return top


def module_vtree(path: str, *, leaf_package: bool = True, return_leaf: bool = False) -> Module:
    """Link objects together, vertically.

    Parameters:
        path: The complete module path, like `"a.b.c.d"`.
        leaf_package: Whether the deepest module should also be a package.
        return_leaf: Whether to return the leaf instead of the root.

    Raises:
        ValueError: When no objects are provided.

    Returns:
        The top or leaf module.
    """
    parts = path.split(".")
    modules = [Module(name, filepath=Path(*parts[:index], "__init__.py")) for index, name in enumerate(parts)]
    if not leaf_package:
        filepath = modules[-1].filepath.with_stem(parts[-1])  # ty:ignore[unresolved-attribute]
        modules[-1]._filepath = filepath
    return vtree(*modules, return_leaf=return_leaf)  # ty:ignore[invalid-return-type]
