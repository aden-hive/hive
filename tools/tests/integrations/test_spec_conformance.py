"""Stage 1a: Spec conformance tests.

Verifies that every tool module follows codebase structural conventions:
- __init__.py re-exports register_tools
- register_tools has the correct signature
- CredentialSpec fields are complete
- spec.tools match actual @mcp.tool() functions
- Specs are merged into CREDENTIAL_SPECS
- Tool names appear in register_all_tools() return list
"""

from __future__ import annotations

import importlib
import inspect

import pytest
from fastmcp import FastMCP

from aden_tools.credentials import (
    CREDENTIAL_SPECS,
    EMAIL_CREDENTIALS,
    GITHUB_CREDENTIALS,
    HUBSPOT_CREDENTIALS,
    LLM_CREDENTIALS,
    SEARCH_CREDENTIALS,
    SLACK_CREDENTIALS,
)
from aden_tools.tools import register_all_tools

from .conftest import (
    CREDENTIAL_STORE_META_MODULES,
    CREDENTIAL_TOOL_MODULE_IDS,
    CREDENTIAL_TOOL_MODULES,
    KNOWN_PHANTOM_TOOLS,
    MODULE_TO_TOOLS,
    TOOL_MODULE_IDS,
    TOOL_MODULES,
)

# ---------------------------------------------------------------------------
# 1a-1: Module has __init__.py re-exporting register_tools
# ---------------------------------------------------------------------------


class TestModuleStructure:
    """Every tool module must export register_tools from its __init__.py."""

    @pytest.mark.parametrize(
        "import_path,short_name",
        TOOL_MODULES,
        ids=TOOL_MODULE_IDS,
    )
    def test_module_exports_register_tools(self, import_path: str, short_name: str):
        """register_tools is importable from the module's package."""
        mod = importlib.import_module(import_path)
        assert hasattr(mod, "register_tools"), (
            f"Module {import_path} does not export 'register_tools'"
        )
        assert callable(mod.register_tools), f"{import_path}.register_tools is not callable"

    @pytest.mark.parametrize(
        "import_path,short_name",
        TOOL_MODULES,
        ids=TOOL_MODULE_IDS,
    )
    def test_register_tools_in_all(self, import_path: str, short_name: str):
        """register_tools appears in __all__ if __all__ is defined."""
        mod = importlib.import_module(import_path)
        all_list = getattr(mod, "__all__", None)
        if all_list is not None:
            assert "register_tools" in all_list, (
                f"{import_path}.__all__ does not include 'register_tools'"
            )


# ---------------------------------------------------------------------------
# 1a-2: register_tools signature
# ---------------------------------------------------------------------------


class TestRegisterToolsSignature:
    """register_tools must have the correct signature."""

    @pytest.mark.parametrize(
        "import_path,short_name",
        TOOL_MODULES,
        ids=TOOL_MODULE_IDS,
    )
    def test_accepts_mcp_param(self, import_path: str, short_name: str):
        """All register_tools functions must accept an 'mcp' parameter."""
        mod = importlib.import_module(import_path)
        sig = inspect.signature(mod.register_tools)
        params = list(sig.parameters.keys())
        assert len(params) >= 1, f"{import_path}.register_tools has no parameters"
        assert params[0] == "mcp", (
            f"{import_path}.register_tools first param should be 'mcp', got '{params[0]}'"
        )

    @pytest.mark.parametrize(
        "import_path,short_name",
        CREDENTIAL_TOOL_MODULES,
        ids=CREDENTIAL_TOOL_MODULE_IDS,
    )
    def test_credential_tools_accept_credentials_param(self, import_path: str, short_name: str):
        """Tools with CredentialSpecs must accept a 'credentials' parameter."""
        mod = importlib.import_module(import_path)
        sig = inspect.signature(mod.register_tools)
        assert "credentials" in sig.parameters, (
            f"{import_path}.register_tools should accept 'credentials' param"
        )

        param = sig.parameters["credentials"]
        assert param.default is None, (
            f"{import_path}.register_tools 'credentials' param should default to None"
        )


# ---------------------------------------------------------------------------
# 1a-3: CredentialSpec field completeness
# ---------------------------------------------------------------------------


class TestCredentialSpecFields:
    """Every CredentialSpec must have non-empty required fields."""

    @pytest.mark.parametrize("spec_name", list(CREDENTIAL_SPECS.keys()))
    def test_env_var_non_empty(self, spec_name: str):
        """CredentialSpec.env_var must be non-empty."""
        spec = CREDENTIAL_SPECS[spec_name]
        assert spec.env_var, f"Spec '{spec_name}' has empty env_var"

    @pytest.mark.parametrize("spec_name", list(CREDENTIAL_SPECS.keys()))
    def test_tools_or_node_types_non_empty(self, spec_name: str):
        """CredentialSpec must have non-empty tools or node_types."""
        spec = CREDENTIAL_SPECS[spec_name]
        assert spec.tools or spec.node_types, (
            f"Spec '{spec_name}' has both empty tools and empty node_types"
        )

    @pytest.mark.parametrize("spec_name", list(CREDENTIAL_SPECS.keys()))
    def test_help_url_non_empty(self, spec_name: str):
        """CredentialSpec.help_url must be non-empty."""
        spec = CREDENTIAL_SPECS[spec_name]
        assert spec.help_url, f"Spec '{spec_name}' has empty help_url"

    @pytest.mark.parametrize("spec_name", list(CREDENTIAL_SPECS.keys()))
    def test_description_non_empty(self, spec_name: str):
        """CredentialSpec.description must be non-empty."""
        spec = CREDENTIAL_SPECS[spec_name]
        assert spec.description, f"Spec '{spec_name}' has empty description"

    @pytest.mark.parametrize("spec_name", list(CREDENTIAL_SPECS.keys()))
    def test_credential_id_non_empty(self, spec_name: str):
        """CredentialSpec.credential_id must be non-empty."""
        spec = CREDENTIAL_SPECS[spec_name]
        assert spec.credential_id, f"Spec '{spec_name}' has empty credential_id"

    @pytest.mark.parametrize("spec_name", list(CREDENTIAL_SPECS.keys()))
    def test_credential_key_non_empty(self, spec_name: str):
        """CredentialSpec.credential_key must be non-empty."""
        spec = CREDENTIAL_SPECS[spec_name]
        assert spec.credential_key, f"Spec '{spec_name}' has empty credential_key"


# ---------------------------------------------------------------------------
# 1a-4: spec.tools match actual registered @mcp.tool() functions
# ---------------------------------------------------------------------------


class TestSpecToolsMatchRegistered:
    """Every tool name in a CredentialSpec.tools must be a real registered tool."""

    @pytest.fixture(scope="class")
    def registered_tools(self) -> set[str]:
        """Register all tools and return the set of registered tool names."""
        mcp = FastMCP("spec-check")
        register_all_tools(mcp, credentials=None)
        return set(mcp._tool_manager._tools.keys())

    @pytest.mark.parametrize("spec_name", list(CREDENTIAL_SPECS.keys()))
    def test_spec_tools_are_registered(self, spec_name: str, registered_tools: set[str]):
        """Every name in spec.tools must exist in the registered tools.

        Known phantom tool names (used for multi-provider credential grouping)
        are excluded — see KNOWN_PHANTOM_TOOLS in conftest.py.
        """
        spec = CREDENTIAL_SPECS[spec_name]
        for tool_name in spec.tools:
            if tool_name in KNOWN_PHANTOM_TOOLS:
                continue
            assert tool_name in registered_tools, (
                f"Spec '{spec_name}' references tool '{tool_name}' "
                f"which is not registered. Registered tools: {sorted(registered_tools)}"
            )


# ---------------------------------------------------------------------------
# 1a-5: All credential category dicts are merged into CREDENTIAL_SPECS
# ---------------------------------------------------------------------------


class TestSpecsMergedIntoCredentialSpecs:
    """All category credential dicts must be merged into the global CREDENTIAL_SPECS."""

    CATEGORY_DICTS = {
        "LLM_CREDENTIALS": LLM_CREDENTIALS,
        "SEARCH_CREDENTIALS": SEARCH_CREDENTIALS,
        "EMAIL_CREDENTIALS": EMAIL_CREDENTIALS,
        "GITHUB_CREDENTIALS": GITHUB_CREDENTIALS,
        "HUBSPOT_CREDENTIALS": HUBSPOT_CREDENTIALS,
        "SLACK_CREDENTIALS": SLACK_CREDENTIALS,
    }

    @pytest.mark.parametrize("category_name", list(CATEGORY_DICTS.keys()))
    def test_category_merged(self, category_name: str):
        """Every key in the category dict must exist in CREDENTIAL_SPECS."""
        category = self.CATEGORY_DICTS[category_name]
        for spec_name, spec in category.items():
            assert spec_name in CREDENTIAL_SPECS, (
                f"'{spec_name}' from {category_name} is not in CREDENTIAL_SPECS"
            )
            assert CREDENTIAL_SPECS[spec_name] is spec, (
                f"'{spec_name}' in CREDENTIAL_SPECS is not the same object as in {category_name}"
            )


# ---------------------------------------------------------------------------
# 1a-6: Tool names appear in register_all_tools() return list
# ---------------------------------------------------------------------------


class TestToolNamesInReturnList:
    """Tool names from CredentialSpecs must appear in register_all_tools() return."""

    @pytest.fixture(scope="class")
    def all_tools_return(self) -> list[str]:
        """Call register_all_tools and return the tool name list."""
        mcp = FastMCP("return-check")
        return register_all_tools(mcp, credentials=None)

    @pytest.mark.parametrize("spec_name", list(CREDENTIAL_SPECS.keys()))
    def test_spec_tools_in_return_list(self, spec_name: str, all_tools_return: list[str]):
        """Every tool name in spec.tools appears in register_all_tools() return.

        Known phantom tool names are excluded — see KNOWN_PHANTOM_TOOLS.
        """
        spec = CREDENTIAL_SPECS[spec_name]
        for tool_name in spec.tools:
            if tool_name in KNOWN_PHANTOM_TOOLS:
                continue
            assert tool_name in all_tools_return, (
                f"Tool '{tool_name}' (from spec '{spec_name}') "
                f"not in register_all_tools() return list"
            )


# ---------------------------------------------------------------------------
# 1a-7: Credential coverage - tools accepting credentials must have specs
# ---------------------------------------------------------------------------


class TestCredentialCoverage:
    """Every tool that accepts credentials must have a corresponding CredentialSpec.

    This enforces the convention:
    - register_tools(mcp) -> no credentials needed
    - register_tools(mcp, credentials=None) -> must have CredentialSpec entries

    This eliminates the need for a separate "no_credentials" list.
    """

    @pytest.fixture(scope="class")
    def all_spec_tools(self) -> set[str]:
        """Collect all tool names referenced in CREDENTIAL_SPECS."""
        tools: set[str] = set()
        for spec in CREDENTIAL_SPECS.values():
            tools.update(spec.tools)
        tools.update(KNOWN_PHANTOM_TOOLS)
        return tools

    @pytest.mark.parametrize(
        "import_path,short_name",
        CREDENTIAL_TOOL_MODULES,
        ids=CREDENTIAL_TOOL_MODULE_IDS,
    )
    def test_credential_tools_have_specs(
        self, import_path: str, short_name: str, all_spec_tools: set[str]
    ):
        """Every tool from a module with credentials param must have a spec.

        If this test fails, you have two options:
        1. Add a CredentialSpec in credentials/<category>.py for your tool
        2. Remove the 'credentials' param from register_tools() if no credentials needed
        """
        if short_name in CREDENTIAL_STORE_META_MODULES:
            pytest.skip(f"'{short_name}' is a credential-store meta-module")
        tools_in_module = MODULE_TO_TOOLS.get(short_name, [])
        for tool_name in tools_in_module:
            assert tool_name in all_spec_tools, (
                f"Tool '{tool_name}' from module '{short_name}' accepts credentials "
                f"but has no CredentialSpec.\n\n"
                f"Fix by either:\n"
                f"  1. Adding a CredentialSpec in credentials/<category>.py with "
                f"tools=['{tool_name}'], or\n"
                f"  2. Removing 'credentials' param from register_tools() if this "
                f"tool doesn't need credentials"
            )
