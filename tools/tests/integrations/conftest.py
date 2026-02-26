"""Shared fixtures and discovery utilities for Stage 1 tests.

Discovers all tool modules under aden_tools.tools and provides
parameterization data for conformance testing.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from aden_tools.credentials import CREDENTIAL_SPECS

# --- Known Issues ---
# google_search and google_cse specs use tools=["google_search"] but
# the actual MCP tool is "web_search" (multi-provider). This is because
# _tool_to_cred is 1:1 and web_search already maps to brave_search.
# These specs use a phantom tool name for credential grouping.
KNOWN_PHANTOM_TOOLS: set[str] = {"google_search"}

# Modules that accept `credentials` to query the credential store itself
# (meta-tools), not for external API auth. They don't need CredentialSpecs.
CREDENTIAL_STORE_META_MODULES: set[str] = {"account_info_tool"}

# --- Tool Module Discovery ---

TOOLS_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "aden_tools" / "tools"


def _discover_tool_modules() -> list[tuple[str, str]]:
    """Discover all tool module import paths and short names.

    Scans aden_tools/tools/ for packages that re-export ``register_tools``
    in their ``__init__.py``.

    Returns:
        List of (import_path, short_name) tuples.
        E.g. ("aden_tools.tools.web_search_tool", "web_search_tool")
    """
    modules: list[tuple[str, str]] = []

    for item in sorted(TOOLS_SRC.iterdir()):
        if item.name.startswith("_") or item.name == "__pycache__":
            continue

        if item.is_dir() and (item / "__init__.py").exists():
            init_text = (item / "__init__.py").read_text()

            if "register_tools" in init_text:
                # Direct tool package (e.g., web_search_tool, email_tool)
                modules.append((f"aden_tools.tools.{item.name}", item.name))
            else:
                # Toolkit directory (e.g., file_system_toolkits) — scan sub-packages
                for sub in sorted(item.iterdir()):
                    if sub.name.startswith("_") or sub.name == "__pycache__":
                        continue
                    if sub.is_dir() and (sub / "__init__.py").exists():
                        sub_init_text = (sub / "__init__.py").read_text()
                        if "register_tools" in sub_init_text:
                            modules.append(
                                (
                                    f"aden_tools.tools.{item.name}.{sub.name}",
                                    f"{item.name}/{sub.name}",
                                )
                            )

    return modules


# Computed once at import time
TOOL_MODULES: list[tuple[str, str]] = _discover_tool_modules()
TOOL_MODULE_IDS: list[str] = [name for _, name in TOOL_MODULES]


def _get_credential_tool_modules() -> list[tuple[str, str]]:
    """Return tool modules that accept a ``credentials`` parameter."""
    result = []
    for import_path, short_name in TOOL_MODULES:
        mod = importlib.import_module(import_path)
        register_fn = getattr(mod, "register_tools", None)
        if register_fn is None:
            continue
        sig = inspect.signature(register_fn)
        if "credentials" in sig.parameters:
            result.append((import_path, short_name))
    return result


CREDENTIAL_TOOL_MODULES: list[tuple[str, str]] = _get_credential_tool_modules()
CREDENTIAL_TOOL_MODULE_IDS: list[str] = [name for _, name in CREDENTIAL_TOOL_MODULES]


def _get_module_to_tools_mapping() -> dict[str, list[str]]:
    """Map each tool module to the tool names it registers.

    Registers each module's tools individually into a fresh FastMCP instance
    and collects the tool names that appear.
    """
    mapping: dict[str, list[str]] = {}

    for import_path, short_name in TOOL_MODULES:
        mod = importlib.import_module(import_path)
        register_fn = getattr(mod, "register_tools", None)
        if register_fn is None:
            continue

        mcp = FastMCP("discovery")
        sig = inspect.signature(register_fn)
        if "credentials" in sig.parameters:
            register_fn(mcp, credentials=None)
        else:
            register_fn(mcp)

        mapping[short_name] = list(mcp._tool_manager._tools.keys())

    return mapping


# Computed once at import time
MODULE_TO_TOOLS: dict[str, list[str]] = _get_module_to_tools_mapping()


def get_all_credential_tool_names() -> list[str]:
    """Get all tool names that have associated CredentialSpecs."""
    names: list[str] = []
    for spec in CREDENTIAL_SPECS.values():
        names.extend(spec.tools)
    return names


def get_minimal_args(fn: Any) -> dict[str, Any]:
    """Build minimal keyword arguments for a tool function.

    Uses the function signature to determine required parameters and
    provides sensible minimal values for common types.
    """
    sig = inspect.signature(fn)
    args: dict[str, Any] = {}

    for name, param in sig.parameters.items():
        if param.default is not inspect.Parameter.empty:
            continue  # Skip optional params

        # Infer a minimal value from annotation
        annotation = param.annotation
        annotation_str = str(annotation)

        if annotation is str or "str" in annotation_str:
            args[name] = "test"
        elif annotation is int or annotation_str == "int":
            args[name] = 1
        elif annotation is float or annotation_str == "float":
            args[name] = 1.0
        elif annotation is bool or annotation_str == "bool":
            args[name] = True
        elif "list" in annotation_str.lower():
            args[name] = ["test@example.com"]
        elif "dict" in annotation_str.lower():
            args[name] = {}
        else:
            args[name] = "test"

    return args
