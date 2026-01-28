from contextlib import contextmanager as _contextmanager

# Find the implementation with the latest Lua version available.
_newest_lib = None


@_contextmanager
def allow_lua_module_loading():
    """
    A context manager for enabling binary Lua module loading when importing Lua.

    This can only be used once within a Python runtime and must wrap the import of the
    ``lupa.*`` Lua module, e.g.::

        import lupa
        with lupa.allow_lua_module_loading()
            from lupa import lua54

        lua = lua54.LuaRuntime()
        lua.require('cjson')
    """
    try:
        from os import RTLD_NOW, RTLD_GLOBAL
    except ImportError:
        try:
            from DLFCN import RTLD_NOW, RTLD_GLOBAL  # Py2.7
        except ImportError:
            # MS-Windows does not have dlopen-flags.
            yield
            return

    dlopen_flags = RTLD_NOW | RTLD_GLOBAL

    import sys
    old_flags = sys.getdlopenflags()

    try:
        sys.setdlopenflags(dlopen_flags)
        yield
    finally:
        sys.setdlopenflags(old_flags)


def _import_newest_lib():
    global _newest_lib
    if _newest_lib is not None:
        return _newest_lib

    import os.path
    import re

    package_dir = os.path.dirname(__file__)
    modules = [
        match.groups() for match in (
            re.match(r"((lua[a-z]*)([0-9]*))\..*", filename)
            for filename in os.listdir(package_dir)
        )
        if match
    ]
    if not modules:
        raise RuntimeError("Failed to import Lupa binary module.")
    # prefer Lua over LuaJIT and high versions over low versions.
    module_name = max(modules, key=lambda m: (m[1] == 'lua', tuple(map(int, m[2] or '0'))))

    _newest_lib = __import__(module_name[0], level=1, fromlist="*", globals=globals())
    return _newest_lib


def __getattr__(name):
    """
    Get a name from the latest available Lua (or LuaJIT) module.
    Imports the module as needed.
    """
    if name.startswith('lua'):
        import re
        if re.match(r"((lua[a-z]*)([0-9]*))$", name):
            # "from lupa import lua54" etc.
            assert name not in globals()
            try:
                module = __import__(name, globals=globals(), locals=locals(), level=1)
            except ImportError:
                raise AttributeError(name)
            else:
                assert name in globals()
                return module

    # Import the default Lua implementation and look up the attribute there.
    lua = _newest_lib if _newest_lib is not None else _import_newest_lib()
    globals()[name] = attr = getattr(lua, name)
    return attr


import sys
if sys.version_info < (3, 7):
    # Module level "__getattr__" requires Py3.7 or later => import latest Lua now
    _import_newest_lib()
    globals().update(
        (name, getattr(_newest_lib, name))
        for name in _newest_lib.__all__
    )
del sys

try:
    from lupa.version import __version__
except ImportError:
    pass
