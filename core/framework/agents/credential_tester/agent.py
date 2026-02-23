"""Credential Tester agent — verify synced credentials via live API calls.

A framework agent that lets the user pick a connected account and test it
by making real API calls via the provider's tools.

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
    description="Verify that a synced credential can make real API calls.",
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
    """Collect tool names for a specific Aden credential by credential_id.

    Matches on ``credential_id`` (e.g. "google" → Gmail tools only),
    NOT ``aden_provider_name`` which can be shared across products
    (e.g. both google and google_docs have aden_provider_name="google").
    """
    from aden_tools.credentials import CREDENTIAL_SPECS

    tools: list[str] = []
    for spec in CREDENTIAL_SPECS.values():
        if spec.credential_id == provider_name:
            tools.extend(spec.tools)
    return sorted(set(tools))


def list_connected_accounts() -> list[dict]:
    """List connected accounts from GET /v1/credentials."""
    import os

    from framework.credentials.aden.client import AdenClientConfig, AdenCredentialClient

    api_key = os.environ.get("ADEN_API_KEY")
    if not api_key:
        return []

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
        }
        for c in integrations
        if c.status == "active"
    ]


# ---------------------------------------------------------------------------
# Module-level hooks (read by AgentRunner.load / TUI)
# ---------------------------------------------------------------------------

skip_credential_validation = True
"""Don't validate credentials at load time — we don't know which provider yet."""

requires_account_selection = True
"""Signal TUI to show account picker before starting the agent."""


def configure_for_account(runner: AgentRunner, account: dict) -> None:
    """Scope the tester node's tools to the selected provider.

    Called by the TUI after the user picks an account from the picker.
    After scoping, re-enables credential validation so the selected
    provider's credentials are checked before the agent starts.
    """
    provider = account["provider"]
    tools = get_tools_for_provider(provider)
    tools.append("get_account_info")

    alias = account.get("alias", "unknown")
    email = account.get("identity", {}).get("email", "")
    detail = f" (email: {email})" if email else ""

    for node in runner.graph.nodes:
        if node.id == "tester":
            node.tools = sorted(set(tools))
            # Update system prompt to be provider-specific
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

    # Set intro message for TUI display
    runner.intro_message = (
        f"Testing {provider}/{alias}{detail} — "
        f"{len(tools)} tools loaded. "
        f"I'll suggest a read-only API call to verify the credential works."
    )


# ---------------------------------------------------------------------------
# Module-level graph variables (read by AgentRunner.load)
# ---------------------------------------------------------------------------
# The static node starts with minimal tools. configure_for_account() scopes
# it to the selected provider's tools before execution.

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
connected accounts can make real API calls.

# Startup

1. Call ``get_account_info`` to list the user's connected accounts.
2. Present the list and ask the user which account to test.
3. Once they pick one, note the account's **alias** (e.g. "Timothy", "work-slack").
4. Suggest a simple read-only API call to verify the credential works \
(e.g. list messages, list channels, list contacts).
5. Execute the call when the user agrees.
6. Report the result: success (with sample data) or failure (with error).
7. Let the user request additional API calls to further test the credential.

# Account routing

IMPORTANT: Always pass the account's **alias** as the ``account`` parameter \
when calling any tool. The alias is the routing key — never use the email or \
any other identifier. For example, if the alias is "Timothy", call \
``gmail_list_messages(account="Timothy", ...)``.

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
    "You are a credential tester that verifies connected accounts can make real API calls."
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
        # ... user chats via TUI or CLI ...
        await agent.stop()
    """

    def __init__(self, config=None):
        self.config = config or default_config
        self._selected_account: dict | None = None
        self._agent_runtime: AgentRuntime | None = None
        self._tool_registry: ToolRegistry | None = None
        self._storage_path: Path | None = None

    def list_accounts(self) -> list[dict]:
        """List connected accounts from the Aden credential store."""
        return list_connected_accounts()

    def select_account(self, account: dict) -> None:
        """Select an account to test.

        Args:
            account: Account dict from list_accounts() with
                     provider, alias, identity keys.
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
        identity = self._selected_account.get("identity", {})
        tools = get_tools_for_provider(provider)

        tester_node = build_tester_node(
            provider=provider,
            alias=alias,
            tools=tools,
            identity=identity,
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
