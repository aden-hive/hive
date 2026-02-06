"""Stage 1c: Input validation and error handling tests.

Generic tests parameterized over credential-requiring tools:
- Missing credentials returns {"error": "...", "help": "..."} — both keys
- Missing required params returns {"error": "..."}
"""

from __future__ import annotations

import importlib
import inspect

import pytest
from fastmcp import FastMCP

from aden_tools.credentials import CREDENTIAL_SPECS

from .conftest import (
    CREDENTIAL_TOOL_MODULES,
    MODULE_TO_TOOLS,
    get_minimal_args,
)

# ---------------------------------------------------------------------------
# Build parameterization data for credential-requiring tools
# ---------------------------------------------------------------------------

# Map of tool_name -> (module_import_path, tool_fn_name)
# Only includes tools that have a CredentialSpec with non-empty tools list
_CRED_TOOL_ENTRIES: list[tuple[str, str]] = []

for _spec_name, _spec in CREDENTIAL_SPECS.items():
    for _tool_name in _spec.tools:
        _CRED_TOOL_ENTRIES.append((_spec_name, _tool_name))

_CRED_TOOL_IDS = [f"{spec}:{tool}" for spec, tool in _CRED_TOOL_ENTRIES]


def _find_module_for_tool(tool_name: str) -> str | None:
    """Find the module import path that registers a given tool."""
    for short_name, tools in MODULE_TO_TOOLS.items():
        if tool_name in tools:
            # Reconstruct import path from short_name
            for import_path, sn in CREDENTIAL_TOOL_MODULES:
                if sn == short_name:
                    return import_path
    return None


def _register_and_get_fn(tool_name: str):
    """Register the tool's module and return the tool function."""
    # Find the module that provides this tool
    module_path = _find_module_for_tool(tool_name)
    if module_path is None:
        pytest.skip(f"Could not find module for tool '{tool_name}'")

    mod = importlib.import_module(module_path)
    mcp = FastMCP("test-validation")

    sig = inspect.signature(mod.register_tools)
    if "credentials" in sig.parameters:
        mod.register_tools(mcp, credentials=None)
    else:
        mod.register_tools(mcp)

    tool_entry = mcp._tool_manager._tools.get(tool_name)
    if tool_entry is None:
        pytest.skip(f"Tool '{tool_name}' not found after registration")

    return tool_entry.fn


# --- Env vars to clear for each credential spec ---

_ENV_VARS_TO_CLEAR: dict[str, list[str]] = {}
for _spec_name, _spec in CREDENTIAL_SPECS.items():
    _ENV_VARS_TO_CLEAR[_spec_name] = [_spec.env_var]

# Also clear related env vars (e.g., EMAIL_FROM for email tools)
_EXTRA_ENV_VARS: dict[str, list[str]] = {
    "resend": ["EMAIL_FROM"],
}


# ---------------------------------------------------------------------------
# 1c-1: Missing credentials returns {"error": ..., "help": ...}
# ---------------------------------------------------------------------------


class TestMissingCredentialsError:
    """Tools called without credentials must return both 'error' and 'help' keys."""

    @pytest.mark.parametrize(
        "spec_name,tool_name",
        _CRED_TOOL_ENTRIES,
        ids=_CRED_TOOL_IDS,
    )
    def test_missing_credentials_returns_error_and_help(
        self, spec_name: str, tool_name: str, monkeypatch: pytest.MonkeyPatch
    ):
        """Calling a tool without credentials returns {error, help}."""
        # Clear all credential env vars
        for env_var in _ENV_VARS_TO_CLEAR.get(spec_name, []):
            monkeypatch.delenv(env_var, raising=False)
        for env_var in _EXTRA_ENV_VARS.get(spec_name, []):
            monkeypatch.delenv(env_var, raising=False)

        # Also clear all other credential env vars to ensure clean state
        for other_spec in CREDENTIAL_SPECS.values():
            monkeypatch.delenv(other_spec.env_var, raising=False)

        fn = _register_and_get_fn(tool_name)
        args = get_minimal_args(fn)

        result = fn(**args)

        assert isinstance(result, dict), (
            f"Tool '{tool_name}' should return a dict, got {type(result)}"
        )
        assert "error" in result, (
            f"Tool '{tool_name}' missing credentials should return {{'error': ...}}, got {result}"
        )
        assert "help" in result, (
            f"Tool '{tool_name}' missing credentials should return {{'help': ...}}, got {result}"
        )


# ---------------------------------------------------------------------------
# 1c-2: Missing required params returns error
# ---------------------------------------------------------------------------


class TestMissingRequiredParams:
    """Calling a tool without required params should return an error or raise TypeError."""

    @pytest.mark.parametrize(
        "spec_name,tool_name",
        _CRED_TOOL_ENTRIES,
        ids=_CRED_TOOL_IDS,
    )
    def test_missing_required_params_returns_error(
        self, spec_name: str, tool_name: str, monkeypatch: pytest.MonkeyPatch
    ):
        """Calling a tool with no args raises TypeError or returns error dict."""
        # Set credential so we can test param validation separately
        spec = CREDENTIAL_SPECS[spec_name]
        monkeypatch.setenv(spec.env_var, "test-key")

        fn = _register_and_get_fn(tool_name)

        sig = inspect.signature(fn)
        required_params = [
            name
            for name, param in sig.parameters.items()
            if param.default is inspect.Parameter.empty
        ]

        if not required_params:
            pytest.skip(f"Tool '{tool_name}' has no required params")

        # Calling with no args should fail
        try:
            result = fn()
            # If it returns (doesn't raise), it should be an error dict
            if isinstance(result, dict):
                assert "error" in result, (
                    f"Tool '{tool_name}' called with no args returned success: {result}"
                )
        except TypeError:
            # TypeError from missing positional args is acceptable
            pass
