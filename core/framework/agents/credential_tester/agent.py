"""Credential Tester agent — verify credentials via live API calls.

Supports both Aden OAuth2-synced accounts AND locally-stored API key accounts.
Aden accounts use account="alias" routing; local accounts inject the key into
the session environment so tools read it without an account= parameter.

When loaded via AgentRunner.load() (TUI picker, ``hive run``), the module-level
``nodes`` / ``edges`` variables provide a static graph.  The TUI detects
``requires_account_selection`` and shows an account picker *before* starting
the agent.  ``configure_for_account()`` then scopes the node's tools to the
selected provider.

When used directly (``CredentialTesterAgent``), the graph is built dynamically
after the user picks an account programmatically.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from framework.graph import Goal, NodeSpec, SuccessCriterion
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config
from .nodes import build_tester_node

if TYPE_CHECKING:
    from framework.runner import AgentRunner

# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------

goal = Goal(
    id="credential-tester",
    name="Credential Tester",
    description="Verify that a credential can make real API calls.",
    success_criteria=[
        SuccessCriterion(
            id="api-call-success",
            description="At least one API call succeeds using the credential",
            metric="api_call_success",
            target="true",
            weight=1.0,
        ),
    ],
    constraints=[],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_tools_for_provider(provider_name: str) -> list[str]:
    """Collect tool names for a credential by credential_id OR credential_group.

    Matches on both ``credential_id`` (e.g. "google" → Gmail tools) and
    ``credential_group`` (e.g. "google_custom_search" → all google search tools).
    """
    from aden_tools.credentials import CREDENTIAL_SPECS

    tools: list[str] = []
    for spec in CREDENTIAL_SPECS.values():
        if spec.credential_id == provider_name or spec.credential_group == provider_name:
            tools.extend(spec.tools)
    return sorted(set(tools))


def _list_aden_accounts() -> list[dict]:
    """List active accounts from the Aden platform (requires ADEN_API_KEY)."""
    import os

    api_key = os.environ.get("ADEN_API_KEY")
    if not api_key:
        return []

    try:
        from framework.credentials.aden.client import AdenClientConfig, AdenCredentialClient

        client = AdenCredentialClient(
            AdenClientConfig(
                base_url=os.environ.get("ADEN_API_URL", "https://api.adenhq.com"),
            )
        )
        try:
            integrations = client.list_integrations()
        finally:
            client.close()

        return [
            {
                "provider": c.provider,
                "alias": c.alias,
                "identity": {"email": c.email} if c.email else {},
                "integration_id": c.integration_id,
                "source": "aden",
            }
            for c in integrations
            if c.status == "active"
        ]
    except Exception:
        return []


def _list_local_accounts() -> list[dict]:
    """List named local API key accounts from LocalCredentialRegistry."""
    try:
        from framework.credentials.local.registry import LocalCredentialRegistry

        return [
            info.to_account_dict() for info in LocalCredentialRegistry.default().list_accounts()
        ]
    except Exception:
        return []


def _list_env_fallback_accounts() -> list[dict]:
    """Surface configured-but-unregistered credentials as testable entries.

    Detects credentials available via env vars OR stored in the encrypted
    store in the old flat format (e.g. ``brave_search`` with no alias).
    These are users who haven't yet run ``save_account()`` but have a working key.
    Shows with alias="default" and status="unknown".
    """
    import os

    from aden_tools.credentials import CREDENTIAL_SPECS

    # Collect IDs in encrypted store (includes old flat entries like "brave_search")
    try:
        from framework.credentials.storage import EncryptedFileStorage

        encrypted_ids: set[str] = set(EncryptedFileStorage().list_all())
    except Exception:
        encrypted_ids = set()

    def _is_configured(cred_name: str, spec) -> bool:
        # 1. Env var present
        if os.environ.get(spec.env_var):
            return True
        # 2. Old flat encrypted entry (no slash — new entries have {x}/{y})
        if cred_name in encrypted_ids:
            return True
        return False

    seen_groups: set[str] = set()
    accounts: list[dict] = []

    for cred_name, spec in CREDENTIAL_SPECS.items():
        if not spec.direct_api_key_supported or not spec.tools:
            continue

        if spec.credential_group:
            if spec.credential_group in seen_groups:
                continue
            group_available = all(
                _is_configured(n, s)
                for n, s in CREDENTIAL_SPECS.items()
                if s.credential_group == spec.credential_group
            )
            if not group_available:
                continue
            seen_groups.add(spec.credential_group)
            provider = spec.credential_group
        else:
            if not _is_configured(cred_name, spec):
                continue
            provider = cred_name

        accounts.append(
            {
                "provider": provider,
                "alias": "default",
                "identity": {},
                "integration_id": None,
                "source": "local",
                "status": "unknown",
            }
        )

    return accounts


def list_connected_accounts() -> list[dict]:
    """List all testable accounts: Aden-synced + named local + env-var fallbacks."""
    aden = _list_aden_accounts()
    local = _list_local_accounts()

    # Show env-var fallbacks only for credentials not already in the named registry
    local_providers = {a["provider"] for a in local}
    env_fallbacks = [
        a for a in _list_env_fallback_accounts() if a["provider"] not in local_providers
    ]

    return aden + local + env_fallbacks


# ---------------------------------------------------------------------------
# Module-level hooks (read by AgentRunner.load / TUI)
# ---------------------------------------------------------------------------

skip_credential_validation = True
"""Don't validate credentials at load time — we don't know which provider yet."""

skip_guardian = True
"""Don't attach the Hive Coder guardian — this is a standalone utility agent."""

requires_account_selection = True
"""Signal TUI to show account picker before starting the agent."""


def configure_for_account(runner: AgentRunner, account: dict) -> None:
    """Scope the tester node's tools to the selected provider.

    Handles both Aden accounts (account= routing) and local accounts
    (session-level env var injection, no account= parameter in prompt).
    """
    provider = account["provider"]
    source = account.get("source", "aden")
    alias = account.get("alias", "unknown")
    identity = account.get("identity", {})
    tools = get_tools_for_provider(provider)

    if source == "aden":
        tools.append("get_account_info")
        email = identity.get("email", "")
        detail = f" (email: {email})" if email else ""
        _configure_aden_node(runner, provider, alias, detail, tools)
    else:
        status = account.get("status", "unknown")
        _activate_local_account(provider, alias)
        _configure_local_node(runner, provider, alias, identity, tools, status)


def _activate_local_account(credential_id: str, alias: str) -> None:
    """Inject a named local account's key into the session environment.

    Handles three cases:
    1. Named account in LocalCredentialRegistry (new format: {credential_id}/{alias})
    2. Old flat credential in EncryptedFileStorage (id == credential_id, no alias)
    3. Env var already set — skip injection (nothing to do)
    """
    import os

    from aden_tools.credentials import CREDENTIAL_SPECS

    # Collect specs for this credential (handles grouped credentials too)
    group_specs = [
        (cred_name, spec)
        for cred_name, spec in CREDENTIAL_SPECS.items()
        if spec.credential_group == credential_id
        or spec.credential_id == credential_id
        or cred_name == credential_id
    ]
    # Deduplicate — credential_id and credential_group may both match the same spec
    seen_env_vars: set[str] = set()

    try:
        from framework.credentials.local.registry import LocalCredentialRegistry
        from framework.credentials.storage import EncryptedFileStorage

        registry = LocalCredentialRegistry.default()
        flat_storage = EncryptedFileStorage()

        for _cred_name, spec in group_specs:
            if spec.env_var in seen_env_vars:
                continue
            # If env var is already set, nothing to do for this one
            if os.environ.get(spec.env_var):
                seen_env_vars.add(spec.env_var)
                continue

            seen_env_vars.add(spec.env_var)

            # Determine key name based on spec
            key_name = "api_key"
            if spec.credential_group and "cse" in spec.env_var.lower():
                key_name = "cse_id"

            key: str | None = None

            # 1. Try named account in registry (new format)
            if alias != "default":
                key = registry.get_key(credential_id, alias, key_name)
            else:
                # For "default" alias, check registry first, then fall back to flat store
                key = registry.get_key(credential_id, "default", key_name)

            # 2. Fall back to old flat encrypted entry (id == credential_id, no alias)
            if key is None:
                flat_cred = flat_storage.load(credential_id)
                if flat_cred is not None:
                    key = flat_cred.get_key(key_name) or flat_cred.get_default_key()

            if key:
                os.environ[spec.env_var] = key
    except Exception:
        pass


def _configure_aden_node(
    runner: AgentRunner,
    provider: str,
    alias: str,
    detail: str,
    tools: list[str],
) -> None:
    for node in runner.graph.nodes:
        if node.id == "tester":
            node.tools = sorted(set(tools))
            node.system_prompt = f"""\
You are a credential tester for the account: {provider}/{alias}{detail}

# Instructions

1. Suggest a simple read-only API call to verify the credential works \
(e.g. list messages, list channels, list contacts).
2. Execute the call when the user agrees.
3. Report the result: success (with sample data) or failure (with error).
4. Let the user request additional API calls to further test the credential.

# Account routing

IMPORTANT: Always pass `account="{alias}"` when calling any tool. \
This routes the API call to the correct credential. Never use the email \
or any other identifier — always use the alias exactly as shown.

# Rules

- Start with read-only operations (list, get) before write operations.
- Always confirm with the user before performing write operations.
- If a call fails, report the exact error — this helps diagnose credential issues.
- Be concise. No emojis.
"""
            break

    runner.intro_message = (
        f"Testing {provider}/{alias}{detail} — "
        f"{len(tools)} tools loaded. "
        "I'll suggest a read-only API call to verify the credential works."
    )


def _configure_local_node(
    runner: AgentRunner,
    provider: str,
    alias: str,
    identity: dict,
    tools: list[str],
    status: str,
) -> None:
    identity_parts = [f"{k}: {v}" for k, v in identity.items() if v]
    detail = f" ({', '.join(identity_parts)})" if identity_parts else ""
    status_note = " [key not yet validated]" if status == "unknown" else ""

    for node in runner.graph.nodes:
        if node.id == "tester":
            node.tools = sorted(set(tools))
            node.system_prompt = f"""\
You are a credential tester for the local API key: {provider}/{alias}{detail}{status_note}

# Instructions

1. Suggest a simple test call to verify the credential works \
(e.g. search for "test", list items, get profile info).
2. Execute the call when the user agrees.
3. Report the result: success (with sample data) or failure (with error).
4. Let the user request additional API calls to further test the credential.

# Rules

- Do NOT pass an `account` parameter — this credential is injected \
directly into the session environment and tools read it automatically.
- Start with read-only operations before write operations.
- Always confirm with the user before performing write operations.
- If a call fails, report the exact error — this helps diagnose credential issues.
- Be concise. No emojis.
"""
            break

    runner.intro_message = (
        f"Testing {provider}/{alias}{detail} — "
        f"{len(tools)} tools loaded. "
        "I'll suggest a test API call to verify the credential works."
    )


# ---------------------------------------------------------------------------
# Module-level graph variables (read by AgentRunner.load)
# ---------------------------------------------------------------------------

nodes = [
    NodeSpec(
        id="tester",
        name="Credential Tester",
        description=(
            "Interactive credential testing — lets the user pick an account "
            "and verify it via API calls."
        ),
        node_type="event_loop",
        client_facing=True,
        max_node_visits=0,
        input_keys=[],
        output_keys=[],
        tools=["get_account_info"],
        system_prompt="""\
You are a credential tester. Your job is to help the user verify that their \
connected accounts and API keys can make real API calls.

# Startup

1. Call ``get_account_info`` to list the user's connected accounts.
2. Present the list and ask the user which account to test.
3. Once they pick one, note the account's **alias** (e.g. "Timothy", "work-slack").
4. Suggest a simple read-only API call to verify the credential works \
(e.g. list messages, list channels, list contacts).
5. Execute the call when the user agrees.
6. Report the result: success (with sample data) or failure (with error).
7. Let the user request additional API calls to further test the credential.

# Account routing (Aden accounts only)

IMPORTANT: For Aden-synced accounts, always pass the account's **alias** as the \
``account`` parameter when calling any tool. For local API key accounts, do NOT \
pass an account parameter — they are pre-injected into the session.

# Rules

- Start with read-only operations (list, get) before write operations.
- Always confirm with the user before performing write operations.
- If a call fails, report the exact error — this helps diagnose credential issues.
- Be concise. No emojis.
""",
    ),
]

edges = []

entry_node = "tester"
entry_points = {"start": "tester"}
pause_nodes = []
terminal_nodes = []  # Forever-alive: loops until user exits

conversation_mode = "continuous"
identity_prompt = (
    "You are a credential tester that verifies connected accounts and API keys "
    "can make real API calls."
)
loop_config = {
    "max_iterations": 50,
    "max_tool_calls_per_turn": 10,
    "max_history_tokens": 32000,
}

# ---------------------------------------------------------------------------
# Programmatic agent class (used by __main__.py CLI)
# ---------------------------------------------------------------------------


class CredentialTesterAgent:
    """Interactive agent that tests a specific credential via API calls.

    Usage:
        agent = CredentialTesterAgent()
        accounts = agent.list_accounts()
        agent.select_account(accounts[0])
        await agent.start()
        await agent.stop()
    """

    def __init__(self, config=None):
        self.config = config or default_config
        self._selected_account: dict | None = None
        self._agent_runtime: AgentRuntime | None = None
        self._tool_registry: ToolRegistry | None = None
        self._storage_path: Path | None = None

    def list_accounts(self) -> list[dict]:
        """List all testable accounts (Aden + local named + env-var fallbacks)."""
        return list_connected_accounts()

    def select_account(self, account: dict) -> None:
        """Select an account to test.

        Args:
            account: Account dict from list_accounts() with
                     provider, alias, identity, source keys.
        """
        self._selected_account = account

    @property
    def selected_provider(self) -> str:
        if self._selected_account is None:
            raise RuntimeError("No account selected. Call select_account() first.")
        return self._selected_account["provider"]

    @property
    def selected_alias(self) -> str:
        if self._selected_account is None:
            raise RuntimeError("No account selected. Call select_account() first.")
        return self._selected_account.get("alias", "unknown")

    def _build_graph(self) -> GraphSpec:
        provider = self.selected_provider
        alias = self.selected_alias
        source = self._selected_account.get("source", "aden")
        identity = self._selected_account.get("identity", {})
        tools = get_tools_for_provider(provider)

        if source == "local":
            _activate_local_account(provider, alias)
        elif source == "aden":
            tools.append("get_account_info")

        tester_node = build_tester_node(
            provider=provider,
            alias=alias,
            tools=tools,
            identity=identity,
            source=source,
        )

        return GraphSpec(
            id="credential-tester-graph",
            goal_id=goal.id,
            version="1.0.0",
            entry_node="tester",
            entry_points={"start": "tester"},
            terminal_nodes=[],
            pause_nodes=[],
            nodes=[tester_node],
            edges=[],
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            loop_config={
                "max_iterations": 50,
                "max_tool_calls_per_turn": 10,
                "max_history_tokens": 32000,
            },
            conversation_mode="continuous",
            identity_prompt=(
                f"You are testing the {provider}/{alias} credential. "
                "Help the user verify it works by making real API calls."
            ),
        )

    def _setup(self) -> None:
        if self._selected_account is None:
            raise RuntimeError("No account selected. Call select_account() first.")

        self._storage_path = Path.home() / ".hive" / "agents" / "credential_tester"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

        extra_kwargs = getattr(self.config, "extra_kwargs", {}) or {}
        llm = LiteLLMProvider(
            model=self.config.model,
            api_key=self.config.api_key,
            api_base=self.config.api_base,
            **extra_kwargs,
        )

        tool_executor = self._tool_registry.get_executor()
        tools = list(self._tool_registry.get_tools().values())

        graph = self._build_graph()

        self._agent_runtime = create_agent_runtime(
            graph=graph,
            goal=goal,
            storage_path=self._storage_path,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Test Credential",
                    entry_node="tester",
                    trigger_type="manual",
                    isolation_level="isolated",
                ),
            ],
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=CheckpointConfig(enabled=False),
            graph_id="credential_tester",
        )

    async def start(self) -> None:
        """Set up and start the agent runtime."""
        if self._agent_runtime is None:
            self._setup()
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self) -> None:
        """Stop the agent runtime."""
        if self._agent_runtime and self._agent_runtime.is_running:
            await self._agent_runtime.stop()
        self._agent_runtime = None

    async def run(self) -> ExecutionResult:
        """Run the agent (convenience for single execution)."""
        await self.start()
        try:
            result = await self._agent_runtime.trigger_and_wait(
                entry_point_id="start",
                input_data={},
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()
