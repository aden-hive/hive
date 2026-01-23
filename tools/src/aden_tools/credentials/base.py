"""
Base classes for credential management.

Contains the core infrastructure: CredentialSpec, CredentialManager, and CredentialError.
Credential specs are defined in separate category files (llm.py, search.py, etc.).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from dotenv import dotenv_values

if TYPE_CHECKING:
    pass


@dataclass
class CredentialSpec:
    """Specification for a single credential."""

    env_var: str
    """Environment variable name (e.g., 'BRAVE_SEARCH_API_KEY')"""

    tools: List[str] = field(default_factory=list)
    """Tool names that require this credential (e.g., ['web_search'])"""

    node_types: List[str] = field(default_factory=list)
    """Node types that require this credential (e.g., ['llm_generate', 'llm_tool_use'])"""

    required: bool = True
    """Whether this credential is required (vs optional)"""

    startup_required: bool = False
    """Whether this credential must be present at server startup (Tier 1)"""

    help_url: str = ""
    """URL where user can obtain this credential"""

    description: str = ""
    """Human-readable description of what this credential is for"""


class CredentialError(Exception):
    """Raised when required credentials are missing."""

    pass


class CredentialManager:
    """
    Centralized credential management with agent-aware validation.

    Key features:
    - validate_for_tools(): Validates only credentials needed by specific tools
    - get(): Retrieves credential value by logical name
    - for_testing(): Factory for creating test instances with mock values

    Usage:
        # Production
        creds = CredentialManager()
        creds.validate_for_tools(["web_search"])  # Fails if BRAVE_SEARCH_API_KEY missing
        api_key = creds.get("brave_search")

        # Testing
        creds = CredentialManager.for_testing({"brave_search": "test-key"})
        api_key = creds.get("brave_search")  # Returns "test-key"
    """

    def __init__(
        self,
        specs: Optional[Dict[str, CredentialSpec]] = None,
        _overrides: Optional[Dict[str, str]] = None,
        dotenv_path: Optional[Path] = None,
    ):
        """
        Initialize the credential manager.

        Args:
            specs: Credential specifications (defaults to CREDENTIAL_SPECS)
            _overrides: Internal - used by for_testing() to inject test values
            dotenv_path: Optional path to .env file (defaults to cwd/.env)
        """
        if specs is None:
            # Lazy import to avoid circular dependency
            from . import CREDENTIAL_SPECS

            specs = CREDENTIAL_SPECS
        self._specs = specs
        self._overrides = _overrides or {}
        self._dotenv_path = dotenv_path
        # Build reverse mapping: tool_name -> credential_name
        self._tool_to_cred: Dict[str, str] = {}
        for cred_name, spec in self._specs.items():
            for tool_name in spec.tools:
                self._tool_to_cred[tool_name] = cred_name
        # Build reverse mapping: node_type -> credential_name
        self._node_type_to_cred: Dict[str, str] = {}
        for cred_name, spec in self._specs.items():
            for node_type in spec.node_types:
                self._node_type_to_cred[node_type] = cred_name

    @classmethod
    def for_testing(
        cls,
        overrides: Dict[str, str],
        specs: Optional[Dict[str, CredentialSpec]] = None,
        dotenv_path: Optional[Path] = None,
    ) -> "CredentialManager":
        """
        Create a CredentialManager with test values.

        Args:
            overrides: Dict mapping credential names to test values
            specs: Optional custom specs (defaults to CREDENTIAL_SPECS)
            dotenv_path: Optional path to .env file (use non-existent path to isolate from real .env)

        Returns:
            CredentialManager pre-configured for testing

        Example:
            creds = CredentialManager.for_testing({"brave_search": "test-key"})
            assert creds.get("brave_search") == "test-key"
        """
        return cls(specs=specs, _overrides=overrides, dotenv_path=dotenv_path)

    def _get_raw(self, name: str) -> Optional[str]:
        """Get credential from overrides, os.environ, or .env file.

        Priority order:
        1. Test overrides (for testing)
        2. os.environ (explicit environment variables take precedence)
        3. .env file (hot-reload support - reads fresh each time)
        """
        # 1. Check overrides (for testing)
        if name in self._overrides:
            return self._overrides[name]

        spec = self._specs.get(name)
        if spec is None:
            return None

        # 2. Check os.environ (takes precedence)
        env_value = os.environ.get(spec.env_var)
        if env_value:
            return env_value

        # 3. Fallback: read from .env file (hot-reload)
        return self._read_from_dotenv(spec.env_var)

    def _read_from_dotenv(self, env_var: str) -> Optional[str]:
        """Read a single env var from .env file.

        Uses dotenv_values() which reads the file without modifying os.environ,
        allowing for hot-reload without side effects.
        """
        dotenv_path = self._dotenv_path or Path.cwd() / ".env"
        if not dotenv_path.exists():
            return None

        # dotenv_values reads file without modifying os.environ
        values = dotenv_values(dotenv_path)
        return values.get(env_var)

    def get(self, name: str) -> Optional[str]:
        """
        Get a credential value by logical name.

        Reads fresh from environment/.env each time to support hot-reload.
        When users add credentials to .env, they take effect immediately
        without restarting the MCP server.

        Args:
            name: Logical credential name (e.g., "brave_search")

        Returns:
            The credential value, or None if not set

        Raises:
            KeyError: If the credential name is not in specs
        """
        if name not in self._specs:
            raise KeyError(
                f"Unknown credential '{name}'. "
                f"Available: {list(self._specs.keys())}"
            )

        # No caching - read fresh each time for hot-reload support
        return self._get_raw(name)

    def get_spec(self, name: str) -> CredentialSpec:
        """Get the spec for a credential."""
        if name not in self._specs:
            raise KeyError(f"Unknown credential '{name}'")
        return self._specs[name]

    def is_available(self, name: str) -> bool:
        """Check if a credential is available (set and non-empty)."""
        value = self.get(name)
        return value is not None and value != ""

    def get_credential_for_tool(self, tool_name: str) -> Optional[str]:
        """
        Get the credential name required by a tool.

        Args:
            tool_name: Name of the tool (e.g., "web_search")

        Returns:
            Credential name if tool requires one, None otherwise
        """
        return self._tool_to_cred.get(tool_name)

    def get_missing_for_tools(
        self, tool_names: List[str]
    ) -> List[Tuple[str, CredentialSpec]]:
        """
        Get list of missing credentials for the given tools.

        Args:
            tool_names: List of tool names to check

        Returns:
            List of (credential_name, spec) tuples for missing credentials
        """
        missing: List[Tuple[str, CredentialSpec]] = []
        checked: set[str] = set()

        for tool_name in tool_names:
            cred_name = self._tool_to_cred.get(tool_name)
            if cred_name is None:
                # Tool doesn't require credentials
                continue
            if cred_name in checked:
                # Already checked this credential
                continue
            checked.add(cred_name)

            spec = self._specs[cred_name]
            if spec.required and not self.is_available(cred_name):
                missing.append((cred_name, spec))

        return missing

    def validate_for_tools(self, tool_names: List[str]) -> None:
        """
        Validate that all credentials required by the given tools are available.

        Args:
            tool_names: List of tool names to validate credentials for

        Raises:
            CredentialError: If any required credentials are missing

        Example:
            creds = CredentialManager()
            creds.validate_for_tools(["web_search", "file_read"])
            # Raises CredentialError if BRAVE_SEARCH_API_KEY is not set
        """
        missing = self.get_missing_for_tools(tool_names)

        if missing:
            raise CredentialError(self._format_missing_error(missing, tool_names))

    def _format_missing_error(
        self,
        missing: List[Tuple[str, CredentialSpec]],
        tool_names: List[str],
    ) -> str:
        """Format a clear, actionable error message for missing credentials."""
        lines = ["Cannot run agent: Missing credentials\n"]
        lines.append("The following tools require credentials that are not set:\n")

        for cred_name, spec in missing:
            # Find which of the requested tools need this credential
            affected_tools = [t for t in tool_names if t in spec.tools]
            tools_str = ", ".join(affected_tools)

            lines.append(f"  {tools_str} requires {spec.env_var}")
            if spec.description:
                lines.append(f"    {spec.description}")
            if spec.help_url:
                lines.append(f"    Get an API key at: {spec.help_url}")
            lines.append(f"    Set via: export {spec.env_var}=your_key")
            lines.append("")

        lines.append("Set these environment variables and re-run the agent.")
        return "\n".join(lines)

    def get_missing_for_node_types(
        self, node_types: List[str]
    ) -> List[Tuple[str, CredentialSpec]]:
        """
        Get list of missing credentials for the given node types.

        Args:
            node_types: List of node types to check (e.g., ['llm_generate', 'llm_tool_use'])

        Returns:
            List of (credential_name, spec) tuples for missing credentials
        """
        missing: List[Tuple[str, CredentialSpec]] = []
        checked: set[str] = set()

        for node_type in node_types:
            cred_name = self._node_type_to_cred.get(node_type)
            if cred_name is None:
                # Node type doesn't require credentials
                continue
            if cred_name in checked:
                # Already checked this credential
                continue
            checked.add(cred_name)

            spec = self._specs[cred_name]
            if spec.required and not self.is_available(cred_name):
                missing.append((cred_name, spec))

        return missing

    def validate_for_node_types(self, node_types: List[str]) -> None:
        """
        Validate that all credentials required by the given node types are available.

        Args:
            node_types: List of node types to validate credentials for

        Raises:
            CredentialError: If any required credentials are missing

        Example:
            creds = CredentialManager()
            creds.validate_for_node_types(["llm_generate", "llm_tool_use"])
            # Raises CredentialError if ANTHROPIC_API_KEY is not set
        """
        missing = self.get_missing_for_node_types(node_types)

        if missing:
            raise CredentialError(
                self._format_missing_node_type_error(missing, node_types)
            )

    def _format_missing_node_type_error(
        self,
        missing: List[Tuple[str, CredentialSpec]],
        node_types: List[str],
    ) -> str:
        """Format a clear, actionable error message for missing node type credentials."""
        lines = ["Cannot run agent: Missing credentials\n"]
        lines.append("The following node types require credentials that are not set:\n")

        for cred_name, spec in missing:
            # Find which of the requested node types need this credential
            affected_types = [t for t in node_types if t in spec.node_types]
            types_str = ", ".join(affected_types)

            lines.append(f"  {types_str} nodes require {spec.env_var}")
            if spec.description:
                lines.append(f"    {spec.description}")
            if spec.help_url:
                lines.append(f"    Get an API key at: {spec.help_url}")
            lines.append(f"    Set via: export {spec.env_var}=your_key")
            lines.append("")

        lines.append("Set these environment variables and re-run the agent.")
        return "\n".join(lines)

    def validate_startup(self) -> None:
        """
        Validate that all startup-required credentials are present.

        This should be called at server startup (e.g., in mcp_server.py).
        Credentials with startup_required=True must be set before the server starts.

        Raises:
            CredentialError: If any startup-required credentials are missing

        Example:
            creds = CredentialManager()
            creds.validate_startup()  # Fails if ANTHROPIC_API_KEY is not set
        """
        missing: List[Tuple[str, CredentialSpec]] = []

        for cred_name, spec in self._specs.items():
            if spec.startup_required and not self.is_available(cred_name):
                missing.append((cred_name, spec))

        if missing:
            raise CredentialError(self._format_startup_error(missing))

    def _format_startup_error(
        self,
        missing: List[Tuple[str, CredentialSpec]],
    ) -> str:
        """Format a clear, actionable error message for missing startup credentials."""
        lines = ["Server startup failed: Missing required credentials\n"]

        for cred_name, spec in missing:
            lines.append(f"  {spec.env_var}")
            if spec.description:
                lines.append(f"    {spec.description}")
            if spec.help_url:
                lines.append(f"    Get an API key at: {spec.help_url}")
            lines.append(f"    Set via: export {spec.env_var}=your_key")
            lines.append("")

        lines.append("Set these environment variables and restart the server.")
        return "\n".join(lines)
