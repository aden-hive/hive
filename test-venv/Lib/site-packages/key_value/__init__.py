"""Key-value store library.

This package provides the py-key-value-aio async key-value library.

Deprecation Notice:
    The `key_value.shared` module has been moved to `key_value.aio._utils`
    and `key_value.aio.errors`. Imports from `key_value.shared.*` will continue
    to work at runtime with deprecation warnings, but type checkers will error.

    Migration guide:
        - `from key_value.shared.errors import X` -> `from key_value.aio.errors import X`
        - `from key_value.shared.managed_entry import X` -> `from key_value.aio._utils.managed_entry import X`
        - `from key_value.shared.* import X` -> `from key_value.aio._utils.* import X`
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

# Mapping of old shared module paths to their new locations
_SHARED_MODULE_REDIRECTS: dict[str, str] = {
    # key_value.shared.* -> key_value.aio.*
    "key_value.shared": "key_value.aio._utils",
    "key_value.shared.errors": "key_value.aio.errors",
    "key_value.shared.errors.base": "key_value.aio.errors.base",
    "key_value.shared.errors.key_value": "key_value.aio.errors.key_value",
    "key_value.shared.errors.store": "key_value.aio.errors.store",
    "key_value.shared.errors.wrappers": "key_value.aio.errors.wrappers",
    "key_value.shared.beartype": "key_value.aio._utils.beartype",
    "key_value.shared.compound": "key_value.aio._utils.compound",
    "key_value.shared.constants": "key_value.aio._utils.constants",
    "key_value.shared.managed_entry": "key_value.aio._utils.managed_entry",
    "key_value.shared.retry": "key_value.aio._utils.retry",
    "key_value.shared.sanitization": "key_value.aio._utils.sanitization",
    "key_value.shared.sanitize": "key_value.aio._utils.sanitize",
    "key_value.shared.serialization": "key_value.aio._utils.serialization",
    "key_value.shared.time_to_live": "key_value.aio._utils.time_to_live",
    "key_value.shared.wait": "key_value.aio._utils.wait",
}


class _DeprecatedModuleFinder(importlib.abc.MetaPathFinder):
    """Meta path finder that intercepts imports from deprecated paths."""

    def find_spec(
        self,
        fullname: str,
        path: object = None,  # noqa: ARG002
        target: object = None,  # noqa: ARG002
    ) -> importlib.machinery.ModuleSpec | None:
        """Find module spec, returning a redirect spec for deprecated paths."""
        if fullname in _SHARED_MODULE_REDIRECTS:
            return importlib.machinery.ModuleSpec(
                fullname,
                _DeprecatedModuleLoader(fullname, _SHARED_MODULE_REDIRECTS[fullname]),
            )
        return None


class _DeprecatedModuleLoader(importlib.abc.Loader):
    """Loader that creates deprecated module aliases."""

    def __init__(self, old_name: str, new_name: str) -> None:
        self.old_name = old_name
        self.new_name = new_name

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:  # noqa: ARG002
        """Create module - return None to use default module creation."""
        return None

    def exec_module(self, module: ModuleType) -> None:
        """Execute module by redirecting to the new location."""
        # Emit deprecation warning
        warnings.warn(
            f"Importing from '{self.old_name}' is deprecated and will be removed in a future version. "
            f"Please use '{self.new_name}' instead.",
            DeprecationWarning,
            stacklevel=6,
        )

        # Import the new module
        new_module = importlib.import_module(self.new_name)

        # Copy attributes to the deprecated module
        module.__dict__.update(new_module.__dict__)
        module.__dict__["__deprecated__"] = True
        module.__dict__["__new_name__"] = self.new_name

        # Handle parent module registration for nested modules
        parts = self.old_name.split(".")
        if len(parts) > 1:
            parent_name = ".".join(parts[:-1])
            if parent_name in sys.modules:
                setattr(sys.modules[parent_name], parts[-1], module)


def _install_deprecated_finder() -> None:
    """Install the deprecated module finder if not already installed."""
    for finder in sys.meta_path:
        if isinstance(finder, _DeprecatedModuleFinder):
            return
    sys.meta_path.insert(0, _DeprecatedModuleFinder())


# Install the finder when this module is loaded
_install_deprecated_finder()


def __getattr__(name: str) -> Any:
    """Intercept attribute access for 'shared' access."""
    if name == "shared":
        # Handle `from key_value import shared` or `key_value.shared`
        warnings.warn(
            "Accessing 'key_value.shared' is deprecated. Please use 'key_value.aio._utils' or 'key_value.aio.errors' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return importlib.import_module("key_value.shared")

    msg = f"module 'key_value' has no attribute {name!r}"
    raise AttributeError(msg)
