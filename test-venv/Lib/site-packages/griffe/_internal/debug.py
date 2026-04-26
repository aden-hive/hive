# This module is here to help users report bugs.
# It provides a function to print environment information,
# which is called from the public `griffe.debug` module
# (when called with `python -m griffe.debug`)
# or thanks to the `--debug-info` CLI flag.

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from importlib import metadata


@dataclass
class _Variable:
    """Dataclass describing an environment variable."""

    name: str
    """Variable name."""
    value: str
    """Variable value."""


@dataclass
class _Package:
    """Dataclass describing a Python package."""

    name: str
    """Package name."""
    version: str
    """Package version."""


@dataclass
class _Environment:
    """Dataclass to store environment information."""

    interpreter_name: str
    """Python interpreter name."""
    interpreter_version: str
    """Python interpreter version."""
    interpreter_path: str
    """Path to Python executable."""
    platform: str
    """Operating System."""
    packages: list[_Package]
    """Installed packages."""
    variables: list[_Variable]
    """Environment variables."""


def _interpreter_name_version() -> tuple[str, str]:
    if hasattr(sys, "implementation"):
        impl = sys.implementation.version
        version = f"{impl.major}.{impl.minor}.{impl.micro}"
        kind = impl.releaselevel
        if kind != "final":
            version += kind[0] + str(impl.serial)
        return sys.implementation.name, version
    return "", "0.0.0"


def _get_version(dist: str = "griffelib") -> str:
    """Get version of the given distribution.

    Parameters:
        dist: A distribution name.

    Returns:
        A version number.
    """
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return "0.0.0"


def _get_debug_info() -> _Environment:
    """Get debug/environment information.

    Returns:
        Environment information.
    """
    py_name, py_version = _interpreter_name_version()
    packages = ["griffelib", "griffecli", "griffe"]
    variables = ["PYTHONPATH", *[var for var in os.environ if var.startswith("GRIFFE")]]
    return _Environment(
        interpreter_name=py_name,
        interpreter_version=py_version,
        interpreter_path=sys.executable,
        platform=platform.platform(),
        variables=[_Variable(var, val) for var in variables if (val := os.getenv(var))],
        packages=[_Package(pkg, _get_version(pkg)) for pkg in packages],
    )


def _print_debug_info() -> None:
    """Print debug/environment information."""
    info = _get_debug_info()
    print(f"- __System__: {info.platform}")
    print(f"- __Python__: {info.interpreter_name} {info.interpreter_version} ({info.interpreter_path})")
    print("- __Environment variables__:")
    for var in info.variables:
        print(f"  - `{var.name}`: `{var.value}`")
    print("- __Installed packages__:")
    for pkg in info.packages:
        print(f"  - `{pkg.name}` v{pkg.version}")
