"""
Interactive credential setup for CLI applications.

Provides a modular, reusable credential setup flow that can be triggered
when validate_agent_credentials() fails. Works with both TUI and headless CLIs.

Usage:
    from framework.credentials.setup import CredentialSetupSession

    # From agent path
    session = CredentialSetupSession.from_agent_path("exports/my-agent")
    result = session.run_interactive()

    # From nodes directly
    session = CredentialSetupSession.from_nodes(nodes)
    result = session.run_interactive()

    # With custom I/O (for integration with other UIs)
    session = CredentialSetupSession(
        missing=missing_creds,
        input_fn=my_input,
        print_fn=my_print,
    )
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.graph import NodeSpec


# ANSI colors for terminal output
class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    NC = "\033[0m"  # No Color

    @classmethod
    def disable(cls):
        """Disable colors (for non-TTY output)."""
        cls.RED = cls.GREEN = cls.YELLOW = cls.BLUE = ""
        cls.CYAN = cls.BOLD = cls.DIM = cls.NC = ""


@dataclass
class MissingCredential:
    """A credential that needs to be configured."""

    credential_name: str
    """Internal credential name (e.g., 'brave_search')"""

    env_var: str
    """Environment variable name (e.g., 'BRAVE_SEARCH_API_KEY')"""

    description: str
    """Human-readable description"""

    help_url: str
    """URL where user can obtain credential"""

    api_key_instructions: str
    """Step-by-step instructions for getting API key"""

    tools: list[str] = field(default_factory=list)
    """Tools that require this credential"""

    node_types: list[str] = field(default_factory=list)
    """Node types that require this credential"""

    aden_supported: bool = False
    """Whether Aden OAuth flow is supported"""

    direct_api_key_supported: bool = True
    """Whether direct API key entry is supported"""

    credential_id: str = ""
    """Credential store ID"""

    credential_key: str = "api_key"
    """Key name within the credential"""


@dataclass
class SetupResult:
    """Result of credential setup session."""

    success: bool
    """Whether all required credentials were configured"""

    configured: list[str] = field(default_factory=list)
    """Credentials that were successfully set up"""

    skipped: list[str] = field(default_factory=list)
    """Credentials user chose to skip"""

    errors: list[str] = field(default_factory=list)
    """Any errors encountered"""


class CredentialSetupSession:
    """
    Interactive credential setup session.

    Can be used by any CLI (runner, coding agent, etc.) to guide users
    through credential configuration when validation fails.

    Example:
        from framework.credentials.setup import CredentialSetupSession
        from framework.credentials.models import CredentialError

        try:
            validate_agent_credentials(nodes)
        except CredentialError:
            session = CredentialSetupSession.from_nodes(nodes)
            result = session.run_interactive()
            if result.success:
                # Retry - credentials are now configured
                validate_agent_credentials(nodes)
    """

    def __init__(
        self,
        missing: list[MissingCredential],
        input_fn: Callable[[str], str] | None = None,
        print_fn: Callable[[str], None] | None = None,
        password_fn: Callable[[str], str] | None = None,
    ):
        """
        Initialize the setup session.

        Args:
            missing: List of credentials that need setup
            input_fn: Custom input function (default: built-in input)
            print_fn: Custom print function (default: built-in print)
            password_fn: Custom password input function (default: getpass.getpass)
        """
        self.missing = missing
        self.input_fn = input_fn or input
        self.print_fn = print_fn or print
        self.password_fn = password_fn or getpass.getpass

        # Disable colors if not a TTY
        if not sys.stdout.isatty():
            Colors.disable()

    @classmethod
    def from_nodes(cls, nodes: list[NodeSpec]) -> CredentialSetupSession:
        """Create a setup session by detecting missing credentials from nodes."""
        missing = detect_missing_credentials_from_nodes(nodes)
        return cls(missing)

    @classmethod
    def from_agent_path(cls, agent_path: str | Path) -> CredentialSetupSession:
        """Create a setup session for an agent by path."""
        agent_path = Path(agent_path)

        # Load agent to get nodes
        agent_json = agent_path / "agent.json"
        agent_py = agent_path / "agent.py"

        nodes = []
        if agent_py.exists():
            # Python-based agent
            nodes = _load_nodes_from_python_agent(agent_path)
        elif agent_json.exists():
            # JSON-based agent
            nodes = _load_nodes_from_json_agent(agent_json)

        missing = detect_missing_credentials_from_nodes(nodes)
        return cls(missing)

    def run_interactive(self) -> SetupResult:
        """Run the interactive setup flow."""
        configured: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        if not self.missing:
            self._print(f"\n{Colors.GREEN}✓ All credentials are already configured!{Colors.NC}\n")
            return SetupResult(success=True)

        self._print_header()

        # Ensure HIVE_CREDENTIAL_KEY is set before storing anything
        if not self._ensure_credential_key():
            return SetupResult(
                success=False,
                errors=["Failed to initialize credential store encryption key"],
            )

        for cred in self.missing:
            try:
                result = self._setup_single_credential(cred)
                if result:
                    configured.append(cred.credential_name)
                else:
                    skipped.append(cred.credential_name)
            except KeyboardInterrupt:
                self._print(f"\n{Colors.YELLOW}Setup interrupted.{Colors.NC}")
                skipped.append(cred.credential_name)
                break
            except Exception as e:
                errors.append(f"{cred.credential_name}: {e}")

        self._print_summary(configured, skipped, errors)

        return SetupResult(
            success=len(errors) == 0 and len(skipped) == 0,
            configured=configured,
            skipped=skipped,
            errors=errors,
        )

    def _print(self, msg: str) -> None:
        """Print a message."""
        self.print_fn(msg)

    def _input(self, prompt: str) -> str:
        """Get input from user."""
        return self.input_fn(prompt)

    def _print_header(self) -> None:
        """Print the setup header."""
        self._print("")
        self._print(f"{Colors.YELLOW}{'=' * 60}{Colors.NC}")
        self._print(f"{Colors.BOLD}  CREDENTIAL SETUP{Colors.NC}")
        self._print(f"{Colors.YELLOW}{'=' * 60}{Colors.NC}")
        self._print("")
        self._print(f"  {len(self.missing)} credential(s) need to be configured:")
        for cred in self.missing:
            affected = cred.tools or cred.node_types
            self._print(f"    • {cred.env_var} ({', '.join(affected)})")
        self._print("")

    def _ensure_credential_key(self) -> bool:
        """Ensure HIVE_CREDENTIAL_KEY is available for encrypted storage."""
        if os.environ.get("HIVE_CREDENTIAL_KEY"):
            return True

        # Try to load from shell config
        try:
            from aden_tools.credentials.shell_config import check_env_var_in_shell_config

            found, value = check_env_var_in_shell_config("HIVE_CREDENTIAL_KEY")
            if found and value:
                os.environ["HIVE_CREDENTIAL_KEY"] = value
                return True
        except ImportError:
            pass

        # Generate a new key
        self._print(f"{Colors.YELLOW}Initializing credential store...{Colors.NC}")
        try:
            from cryptography.fernet import Fernet

            generated_key = Fernet.generate_key().decode()
            os.environ["HIVE_CREDENTIAL_KEY"] = generated_key

            # Save to shell config
            self._save_key_to_shell_config(generated_key)
            return True
        except Exception as e:
            self._print(f"{Colors.RED}Failed to initialize credential store: {e}{Colors.NC}")
            return False

    def _save_key_to_shell_config(self, key: str) -> None:
        """Save HIVE_CREDENTIAL_KEY to shell config."""
        try:
            from aden_tools.credentials.shell_config import (
                add_env_var_to_shell_config,
            )

            success, config_path = add_env_var_to_shell_config(
                "HIVE_CREDENTIAL_KEY",
                key,
                comment="Encryption key for Hive credential store",
            )
            if success:
                self._print(f"{Colors.GREEN}✓ Encryption key saved to {config_path}{Colors.NC}")
        except Exception:
            # Fallback: just tell the user
            self._print("\n")
            self._print(
                f"{Colors.YELLOW}Add this to your shell config (~/.zshrc or ~/.bashrc):{Colors.NC}"
            )
            self._print(f'  export HIVE_CREDENTIAL_KEY="{key}"')

    def _setup_single_credential(self, cred: MissingCredential) -> bool:
        """Set up a single credential. Returns True if configured."""
        self._print(f"\n{Colors.CYAN}{'─' * 60}{Colors.NC}")
        self._print(f"{Colors.BOLD}Setting up: {cred.credential_name}{Colors.NC}")
        affected = cred.tools or cred.node_types
        self._print(f"{Colors.DIM}Required for: {', '.join(affected)}{Colors.NC}")
        if cred.description:
            self._print(f"{Colors.DIM}{cred.description}{Colors.NC}")
        self._print(f"{Colors.CYAN}{'─' * 60}{Colors.NC}")

        # Show auth options
        options = self._get_auth_options(cred)
        choice = self._prompt_choice(options)

        if choice == "skip":
            return False
        elif choice == "aden":
            return self._setup_via_aden(cred)
        elif choice == "direct":
            return self._setup_direct_api_key(cred)

        return False

    def _get_auth_options(self, cred: MissingCredential) -> list[tuple[str, str, str]]:
        """Get available auth options as (key, label, description) tuples."""
        options = []

        if cred.direct_api_key_supported:
            options.append(
                (
                    "direct",
                    "Enter API key directly",
                    "Paste your API key from the provider's dashboard",
                )
            )

        if cred.aden_supported:
            options.append(
                (
                    "aden",
                    "Use Aden Platform (OAuth)",
                    "Secure OAuth2 flow via hive.adenhq.com",
                )
            )

        options.append(
            (
                "skip",
                "Skip for now",
                "Configure this credential later",
            )
        )

        return options

    def _prompt_choice(self, options: list[tuple[str, str, str]]) -> str:
        """Prompt user to choose from options."""
        self._print("")
        for i, (key, label, desc) in enumerate(options, 1):
            if key == "skip":
                self._print(f"  {Colors.DIM}{i}) {label}{Colors.NC}")
            else:
                self._print(f"  {Colors.CYAN}{i}){Colors.NC} {label}")
                self._print(f"     {Colors.DIM}{desc}{Colors.NC}")
        self._print("")

        while True:
            try:
                choice_str = self._input(f"Select option (1-{len(options)}): ").strip()
                if not choice_str:
                    continue
                choice_num = int(choice_str)
                if 1 <= choice_num <= len(options):
                    return options[choice_num - 1][0]
            except ValueError:
                pass
            self._print(f"{Colors.RED}Invalid choice. Enter 1-{len(options)}{Colors.NC}")

    def _setup_direct_api_key(self, cred: MissingCredential) -> bool:
        """Guide user through direct API key setup."""
        # Show instructions
        if cred.api_key_instructions:
            self._print(f"\n{Colors.BOLD}Setup Instructions:{Colors.NC}")
            self._print(cred.api_key_instructions)

        if cred.help_url:
            self._print(f"\n{Colors.CYAN}Get your API key at:{Colors.NC} {cred.help_url}")

        # Collect key (use password input to hide the value)
        self._print("")
        try:
            api_key = self.password_fn(f"Paste your {cred.env_var}: ").strip()
        except Exception:
            # Fallback to regular input if password input fails
            api_key = self._input(f"Paste your {cred.env_var}: ").strip()

        if not api_key:
            self._print(f"{Colors.YELLOW}No value entered. Skipping.{Colors.NC}")
            return False

        # Health check
        health_result = self._run_health_check(cred, api_key)
        if health_result is not None:
            if health_result["valid"]:
                self._print(f"{Colors.GREEN}✓ {health_result['message']}{Colors.NC}")
            else:
                self._print(f"{Colors.YELLOW}⚠ {health_result['message']}{Colors.NC}")
                confirm = self._input("Continue anyway? [y/N]: ").strip().lower()
                if confirm != "y":
                    return False

        # Store credential
        self._store_credential(cred, api_key)
        return True

    def _setup_via_aden(self, cred: MissingCredential) -> bool:
        """Guide user through Aden OAuth flow."""
        self._print(f"\n{Colors.BOLD}Aden Platform Setup{Colors.NC}")
        self._print("This will sync credentials from your Aden account.")
        self._print("")

        # Check for ADEN_API_KEY
        aden_key = os.environ.get("ADEN_API_KEY")
        if not aden_key:
            self._print("You need an Aden API key to use this method.")
            self._print(f"{Colors.CYAN}Get one at:{Colors.NC} https://hive.adenhq.com")
            self._print("")

            try:
                aden_key = self.password_fn("Paste your ADEN_API_KEY: ").strip()
            except Exception:
                aden_key = self._input("Paste your ADEN_API_KEY: ").strip()

            if not aden_key:
                self._print(f"{Colors.YELLOW}No key entered. Skipping.{Colors.NC}")
                return False

            os.environ["ADEN_API_KEY"] = aden_key

            # Save to shell config
            try:
                from aden_tools.credentials.shell_config import add_env_var_to_shell_config

                add_env_var_to_shell_config(
                    "ADEN_API_KEY",
                    aden_key,
                    comment="Aden Platform API key",
                )
            except Exception:
                pass

        # Sync from Aden
        try:
            from framework.credentials import CredentialStore

            store = CredentialStore.with_aden_sync(
                base_url="https://api.adenhq.com",
                auto_sync=True,
            )

            # Check if the credential was synced
            cred_id = cred.credential_id or cred.credential_name
            if store.is_available(cred_id):
                self._print(f"{Colors.GREEN}✓ {cred.credential_name} synced from Aden{Colors.NC}")
                # Export to current session
                try:
                    value = store.get_key(cred_id, cred.credential_key)
                    if value:
                        os.environ[cred.env_var] = value
                except Exception:
                    pass
                return True
            else:
                self._print(
                    f"{Colors.YELLOW}⚠ {cred.credential_name} not found in Aden account.{Colors.NC}"
                )
                self._print("Please connect this integration on https://hive.adenhq.com first.")
                return False
        except Exception as e:
            self._print(f"{Colors.RED}Failed to sync from Aden: {e}{Colors.NC}")
            return False

    def _run_health_check(self, cred: MissingCredential, value: str) -> dict[str, Any] | None:
        """Run health check on credential value."""
        try:
            from aden_tools.credentials import check_credential_health

            result = check_credential_health(cred.credential_name, value)
            return {
                "valid": result.valid,
                "message": result.message,
                "details": result.details,
            }
        except Exception:
            # No health checker available
            return None

    def _store_credential(self, cred: MissingCredential, value: str) -> None:
        """Store credential in encrypted store and export to env."""
        from pydantic import SecretStr

        from framework.credentials import CredentialKey, CredentialObject, CredentialStore

        try:
            store = CredentialStore.with_encrypted_storage()
            cred_id = cred.credential_id or cred.credential_name
            key_name = cred.credential_key or "api_key"

            cred_obj = CredentialObject(
                id=cred_id,
                name=cred.description or cred.credential_name,
                keys={key_name: CredentialKey(name=key_name, value=SecretStr(value))},
            )
            store.save_credential(cred_obj)
            self._print(f"{Colors.GREEN}✓ Stored in ~/.hive/credentials/{Colors.NC}")
        except Exception as e:
            self._print(f"{Colors.YELLOW}⚠ Could not store in credential store: {e}{Colors.NC}")

        # Export to current session
        os.environ[cred.env_var] = value
        self._print(f"{Colors.GREEN}✓ Exported to current session{Colors.NC}")

    def _print_summary(self, configured: list[str], skipped: list[str], errors: list[str]) -> None:
        """Print final summary."""
        self._print("")
        self._print(f"{Colors.YELLOW}{'=' * 60}{Colors.NC}")
        self._print(f"{Colors.BOLD}  SETUP COMPLETE{Colors.NC}")
        self._print(f"{Colors.YELLOW}{'=' * 60}{Colors.NC}")

        if configured:
            self._print(f"\n{Colors.GREEN}✓ Configured:{Colors.NC}")
            for name in configured:
                self._print(f"    • {name}")

        if skipped:
            self._print(f"\n{Colors.YELLOW}⏭ Skipped:{Colors.NC}")
            for name in skipped:
                self._print(f"    • {name}")

        if errors:
            self._print(f"\n{Colors.RED}✗ Errors:{Colors.NC}")
            for err in errors:
                self._print(f"    • {err}")

        if not skipped and not errors:
            self._print(f"\n{Colors.GREEN}All credentials configured successfully!{Colors.NC}")
        elif skipped:
            self._print(f"\n{Colors.YELLOW}Note: Skipped credentials must be configured ")
            self._print(f"before running the agent.{Colors.NC}")

        self._print("")


def detect_missing_credentials_from_nodes(nodes: list) -> list[MissingCredential]:
    """
    Detect missing credentials for a list of nodes.

    Args:
        nodes: List of NodeSpec objects

    Returns:
        List of MissingCredential objects for credentials that need setup
    """
    try:
        from aden_tools.credentials import CREDENTIAL_SPECS

        from framework.credentials import CredentialStore
        from framework.credentials.storage import (
            CompositeStorage,
            EncryptedFileStorage,
            EnvVarStorage,
        )
    except ImportError:
        return []

    # Collect required tools and node types
    required_tools: set[str] = set()
    node_types: set[str] = set()

    for node in nodes:
        if hasattr(node, "tools") and node.tools:
            required_tools.update(node.tools)
        if hasattr(node, "node_type"):
            node_types.add(node.node_type)

    # Build credential store to check availability.
    # Env vars take priority over encrypted store (fresh key wins over stale).
    env_mapping = {
        (spec.credential_id or name): spec.env_var for name, spec in CREDENTIAL_SPECS.items()
    }
    env_storage = EnvVarStorage(env_mapping=env_mapping)
    if os.environ.get("HIVE_CREDENTIAL_KEY"):
        storage = CompositeStorage(primary=env_storage, fallbacks=[EncryptedFileStorage()])
    else:
        storage = env_storage
    store = CredentialStore(storage=storage)

    # Build reverse mappings
    tool_to_cred: dict[str, str] = {}
    node_type_to_cred: dict[str, str] = {}
    for cred_name, spec in CREDENTIAL_SPECS.items():
        for tool_name in spec.tools:
            tool_to_cred[tool_name] = cred_name
        for nt in spec.node_types:
            node_type_to_cred[nt] = cred_name

    missing: list[MissingCredential] = []
    checked: set[str] = set()

    # Check tool credentials
    for tool_name in sorted(required_tools):
        cred_name = tool_to_cred.get(tool_name)
        if cred_name is None or cred_name in checked:
            continue
        checked.add(cred_name)

        spec = CREDENTIAL_SPECS[cred_name]
        cred_id = spec.credential_id or cred_name
        if spec.required and not store.is_available(cred_id):
            affected_tools = sorted(t for t in required_tools if t in spec.tools)
            missing.append(
                MissingCredential(
                    credential_name=cred_name,
                    env_var=spec.env_var,
                    description=spec.description,
                    help_url=spec.help_url,
                    api_key_instructions=spec.api_key_instructions,
                    tools=affected_tools,
                    aden_supported=spec.aden_supported,
                    direct_api_key_supported=spec.direct_api_key_supported,
                    credential_id=spec.credential_id,
                    credential_key=spec.credential_key,
                )
            )

    # Check node type credentials
    for nt in sorted(node_types):
        cred_name = node_type_to_cred.get(nt)
        if cred_name is None or cred_name in checked:
            continue
        checked.add(cred_name)

        spec = CREDENTIAL_SPECS[cred_name]
        cred_id = spec.credential_id or cred_name
        if spec.required and not store.is_available(cred_id):
            affected_types = sorted(t for t in node_types if t in spec.node_types)
            missing.append(
                MissingCredential(
                    credential_name=cred_name,
                    env_var=spec.env_var,
                    description=spec.description,
                    help_url=spec.help_url,
                    api_key_instructions=spec.api_key_instructions,
                    node_types=affected_types,
                    aden_supported=spec.aden_supported,
                    direct_api_key_supported=spec.direct_api_key_supported,
                    credential_id=spec.credential_id,
                    credential_key=spec.credential_key,
                )
            )

    return missing


def _load_nodes_from_python_agent(agent_path: Path) -> list:
    """Load nodes from a Python-based agent."""
    import importlib.util

    agent_py = agent_path / "agent.py"
    if not agent_py.exists():
        return []

    try:
        # Add agent path and its parent to sys.path so imports work
        paths_to_add = [str(agent_path), str(agent_path.parent)]
        for p in paths_to_add:
            if p not in sys.path:
                sys.path.insert(0, p)

        spec = importlib.util.spec_from_file_location(
            f"{agent_path.name}.agent",
            agent_py,
            submodule_search_locations=[str(agent_path)],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return getattr(module, "nodes", [])
    except Exception:
        return []


def _load_nodes_from_json_agent(agent_json: Path) -> list:
    """Load nodes from a JSON-based agent."""
    try:
        with open(agent_json) as f:
            data = json.load(f)

        from framework.graph import NodeSpec

        nodes_data = data.get("graph", {}).get("nodes", [])
        nodes = []
        for node_data in nodes_data:
            nodes.append(
                NodeSpec(
                    id=node_data.get("id", ""),
                    name=node_data.get("name", ""),
                    description=node_data.get("description", ""),
                    node_type=node_data.get("node_type", ""),
                    tools=node_data.get("tools", []),
                    input_keys=node_data.get("input_keys", []),
                    output_keys=node_data.get("output_keys", []),
                )
            )
        return nodes
    except Exception:
        return []


def run_credential_setup_cli(agent_path: str | Path | None = None) -> int:
    """
    Standalone CLI entry point for credential setup.

    Can be called from:
    - `hive setup-credentials <agent>`
    - After CredentialError in runner CLI
    - From coding agent CLI

    Args:
        agent_path: Optional path to agent directory

    Returns:
        Exit code (0 = success, 1 = failure/skipped)
    """
    if agent_path:
        session = CredentialSetupSession.from_agent_path(agent_path)
    else:
        # No agent specified - detect from current context or show error
        print("Usage: hive setup-credentials <agent_path>")
        return 1

    result = session.run_interactive()
    return 0 if result.success else 1
