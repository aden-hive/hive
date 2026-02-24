"""Agent Runner - loads and runs exported agents."""

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.config import get_hive_config, get_preferred_model
from framework.credentials.validation import (
    ensure_credential_key_env as _ensure_credential_key_env,
    validate_agent_credentials,
)
from framework.graph import Goal
from framework.graph.edge import (
    DEFAULT_MAX_TOKENS,
    AsyncEntryPointSpec,
    EdgeCondition,
    EdgeSpec,
    GraphSpec,
)
from framework.graph.executor import ExecutionResult
from framework.graph.node import NodeSpec
from framework.llm.provider import LLMProvider, Tool
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, AgentRuntimeConfig, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec
from framework.runtime.runtime_log_store import RuntimeLogStore

if TYPE_CHECKING:
    from framework.runner.protocol import AgentMessage, CapabilityResponse


logger = logging.getLogger(__name__)

CLAUDE_CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"
CLAUDE_OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
CLAUDE_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

# Buffer in seconds before token expiry to trigger a proactive refresh
_TOKEN_REFRESH_BUFFER_SECS = 300  # 5 minutes


def _refresh_claude_code_token(refresh_token: str) -> dict | None:
    """Refresh the Claude Code OAuth token using the refresh token.

    POSTs to the Anthropic OAuth token endpoint with form-urlencoded data
    (per OAuth 2.0 RFC 6749 Section 4.1.3).

    Returns:
        Dict with new token data (access_token, refresh_token, expires_in)
        on success, None on failure.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLAUDE_OAUTH_CLIENT_ID,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        CLAUDE_OAUTH_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as exc:
        logger.debug("Claude Code token refresh failed: %s", exc)
        return None


def _save_refreshed_credentials(token_data: dict) -> None:
    """Write refreshed token data back to ~/.claude/.credentials.json."""
    import time

    if not CLAUDE_CREDENTIALS_FILE.exists():
        return

    try:
        with open(CLAUDE_CREDENTIALS_FILE) as f:
            creds = json.load(f)

        oauth = creds.get("claudeAiOauth", {})
        oauth["accessToken"] = token_data["access_token"]
        if "refresh_token" in token_data:
            oauth["refreshToken"] = token_data["refresh_token"]
        if "expires_in" in token_data:
            oauth["expiresAt"] = int((time.time() + token_data["expires_in"]) * 1000)
        creds["claudeAiOauth"] = oauth

        with open(CLAUDE_CREDENTIALS_FILE, "w") as f:
            json.dump(creds, f, indent=2)
        logger.debug("Claude Code credentials refreshed successfully")
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        logger.debug("Failed to save refreshed credentials: %s", exc)


def get_claude_code_token() -> str | None:
    """Get the OAuth token from Claude Code subscription with auto-refresh.

    Reads from ~/.claude/.credentials.json which is created by the
    Claude Code CLI when users authenticate with their subscription.

    If the token is expired or close to expiry, attempts an automatic
    refresh using the stored refresh token.

    Returns:
        The access token if available, None otherwise.
    """
    import time

    if not CLAUDE_CREDENTIALS_FILE.exists():
        return None

    try:
        with open(CLAUDE_CREDENTIALS_FILE) as f:
            creds = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    oauth = creds.get("claudeAiOauth", {})
    access_token = oauth.get("accessToken")
    if not access_token:
        return None

    # Check token expiry (expiresAt is in milliseconds)
    expires_at_ms = oauth.get("expiresAt", 0)
    now_ms = int(time.time() * 1000)
    buffer_ms = _TOKEN_REFRESH_BUFFER_SECS * 1000

    if expires_at_ms > now_ms + buffer_ms:
        # Token is still valid
        return access_token

    # Token is expired or near expiry — attempt refresh
    refresh_token = oauth.get("refreshToken")
    if not refresh_token:
        logger.warning("Claude Code token expired and no refresh token available")
        return access_token  # Return expired token; it may still work briefly

    logger.info("Claude Code token expired or near expiry, refreshing...")
    token_data = _refresh_claude_code_token(refresh_token)

    if token_data and "access_token" in token_data:
        _save_refreshed_credentials(token_data)
        return token_data["access_token"]

    # Refresh failed — return the existing token and warn
    logger.warning("Claude Code token refresh failed. Run 'claude' to re-authenticate.")
    return access_token


@dataclass
class AgentInfo:
    """Information about an exported agent."""

    name: str
    description: str
    goal_name: str
    goal_description: str
    node_count: int
    edge_count: int
    nodes: list[dict]
    edges: list[dict]
    entry_node: str
    terminal_nodes: list[str]
    success_criteria: list[dict]
    constraints: list[dict]
    required_tools: list[str]
    has_tools_module: bool
    # Multi-entry-point support
    async_entry_points: list[dict] = field(default_factory=list)
    is_multi_entry_point: bool = False


@dataclass
class ValidationResult:
    """Result of agent validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)
    missing_credentials: list[str] = field(default_factory=list)


def load_agent_export(data: str | dict) -> tuple[GraphSpec, Goal]:
    """
    Load GraphSpec and Goal from export_graph() output.

    Args:
        data: JSON string or dict from export_graph()

    Returns:
        Tuple of (GraphSpec, Goal)
    """
    if isinstance(data, str):
        data = json.loads(data)

    # Extract graph and goal
    graph_data = data.get("graph", {})
    goal_data = data.get("goal", {})

    # Build NodeSpec objects
    nodes = []
    for node_data in graph_data.get("nodes", []):
        nodes.append(NodeSpec(**node_data))

    # Build EdgeSpec objects
    edges = []
    for edge_data in graph_data.get("edges", []):
        condition_str = edge_data.get("condition", "on_success")
        condition_map = {
            "always": EdgeCondition.ALWAYS,
            "on_success": EdgeCondition.ON_SUCCESS,
            "on_failure": EdgeCondition.ON_FAILURE,
            "conditional": EdgeCondition.CONDITIONAL,
            "llm_decide": EdgeCondition.LLM_DECIDE,
        }
        edge = EdgeSpec(
            id=edge_data["id"],
            source=edge_data["source"],
            target=edge_data["target"],
            condition=condition_map.get(condition_str, EdgeCondition.ON_SUCCESS),
            condition_expr=edge_data.get("condition_expr"),
            priority=edge_data.get("priority", 0),
            input_mapping=edge_data.get("input_mapping", {}),
        )
        edges.append(edge)

    # Build AsyncEntryPointSpec objects for multi-entry-point support
    async_entry_points = []
    for aep_data in graph_data.get("async_entry_points", []):
        async_entry_points.append(
            AsyncEntryPointSpec(
                id=aep_data["id"],
                name=aep_data.get("name", aep_data["id"]),
                entry_node=aep_data["entry_node"],
                trigger_type=aep_data.get("trigger_type", "manual"),
                trigger_config=aep_data.get("trigger_config", {}),
                isolation_level=aep_data.get("isolation_level", "shared"),
                priority=aep_data.get("priority", 0),
                max_concurrent=aep_data.get("max_concurrent", 10),
            )
        )

    # Build GraphSpec
    graph = GraphSpec(
        id=graph_data.get("id", "agent-graph"),
        goal_id=graph_data.get("goal_id", ""),
        version=graph_data.get("version", "1.0.0"),
        entry_node=graph_data.get("entry_node", ""),
        entry_points=graph_data.get("entry_points", {}),  # Support pause/resume architecture
        async_entry_points=async_entry_points,  # Support multi-entry-point agents
        terminal_nodes=graph_data.get("terminal_nodes", []),
        pause_nodes=graph_data.get("pause_nodes", []),  # Support pause/resume architecture
        nodes=nodes,
        edges=edges,
        max_steps=graph_data.get("max_steps", 100),
        max_retries_per_node=graph_data.get("max_retries_per_node", 3),
        description=graph_data.get("description", ""),
    )

    # Build Goal
    from framework.graph.goal import Constraint, SuccessCriterion

    success_criteria = []
    for sc_data in goal_data.get("success_criteria", []):
        success_criteria.append(
            SuccessCriterion(
                id=sc_data["id"],
                description=sc_data["description"],
                metric=sc_data.get("metric", ""),
                target=sc_data.get("target", ""),
                weight=sc_data.get("weight", 1.0),
            )
        )

    constraints = []
    for c_data in goal_data.get("constraints", []):
        constraints.append(
            Constraint(
                id=c_data["id"],
                description=c_data["description"],
                constraint_type=c_data.get("constraint_type", "hard"),
                category=c_data.get("category", "safety"),
                check=c_data.get("check", ""),
            )
        )

    goal = Goal(
        id=goal_data.get("id", ""),
        name=goal_data.get("name", ""),
        description=goal_data.get("description", ""),
        success_criteria=success_criteria,
        constraints=constraints,
    )

    return graph, goal


class AgentRunner:
    """
    Loads and runs exported agents with minimal boilerplate.

    Handles:
    - Loading graph and goal from agent.json
    - Auto-discovering tools from tools.py
    - Setting up Runtime, LLM, and executor
    - Executing with dynamic edge traversal

    Usage:
        # Simple usage
        runner = AgentRunner.load("exports/outbound-sales-agent")
        result = await runner.run({"lead_id": "123"})

        # With context manager
        async with AgentRunner.load("exports/outbound-sales-agent") as runner:
            result = await runner.run({"lead_id": "123"})

        # With custom tools
        runner = AgentRunner.load("exports/outbound-sales-agent")
        runner.register_tool("my_tool", my_tool_func)
        result = await runner.run({"lead_id": "123"})
    """

    @staticmethod
    def _resolve_default_model() -> str:
        """Resolve the default model from ~/.hive/configuration.json."""
        return get_preferred_model()

    def __init__(
        self,
        agent_path: Path,
        graph: GraphSpec,
        goal: Goal,
        mock_mode: bool = False,
        storage_path: Path | None = None,
        model: str | None = None,
        intro_message: str = "",
        runtime_config: "AgentRuntimeConfig | None" = None,
        interactive: bool = True,
        skip_credential_validation: bool = False,
        requires_account_selection: bool = False,
        configure_for_account: Callable | None = None,
        list_accounts: Callable | None = None,
    ):
        """
        Initialize the runner (use AgentRunner.load() instead).

        Args:
            agent_path: Path to agent folder
            graph: Loaded GraphSpec object
            goal: Loaded Goal object
            mock_mode: If True, use mock LLM responses
            storage_path: Path for runtime storage (defaults to temp)
            model: Model to use (reads from agent config or ~/.hive/configuration.json if None)
            intro_message: Optional greeting shown to user on TUI load
            runtime_config: Optional AgentRuntimeConfig (webhook settings, etc.)
            interactive: If True (default), offer interactive credential setup on failure.
                Set to False when called from the TUI (which handles setup via its own screen).
            skip_credential_validation: If True, skip credential checks at load time.
            requires_account_selection: If True, TUI shows account picker before starting.
            configure_for_account: Callback(runner, account_dict) to scope tools after selection.
            list_accounts: Callback() -> list[dict] to fetch available accounts.
        """
        self.agent_path = agent_path
        self.graph = graph
        self.goal = goal
        self.mock_mode = mock_mode
        self.model = model or self._resolve_default_model()
        self.intro_message = intro_message
        self.runtime_config = runtime_config
        self._interactive = interactive
        self.skip_credential_validation = skip_credential_validation
        self.requires_account_selection = requires_account_selection
        self._configure_for_account = configure_for_account
        self._list_accounts = list_accounts

        # Set up storage
        if storage_path:
            self._storage_path = storage_path
            self._temp_dir = None
        else:
            # Use persistent storage in ~/.hive/agents/{agent_name}/ per RUNTIME_LOGGING.md spec
            home = Path.home()
            default_storage = home / ".hive" / "agents" / agent_path.name
            default_storage.mkdir(parents=True, exist_ok=True)
            self._storage_path = default_storage
            self._temp_dir = None

        # Load HIVE_CREDENTIAL_KEY from shell config if not in env.
        # Must happen before MCP subprocesses are spawned so they inherit it.
        _ensure_credential_key_env()

        # Initialize components
        self._tool_registry = ToolRegistry()
        self._llm: LLMProvider | None = None
        self._approval_callback: Callable | None = None

        # AgentRuntime — unified execution path for all agents
        self._agent_runtime: AgentRuntime | None = None
        self._uses_async_entry_points = self.graph.has_async_entry_points()

        # Validate credentials before spawning MCP servers.
        # Fails fast with actionable guidance — no MCP noise on screen.
        self._validate_credentials()

        # Auto-discover tools from tools.py
        tools_path = agent_path / "tools.py"
        if tools_path.exists():
            self._tool_registry.discover_from_module(tools_path)

        # Auto-discover MCP servers from mcp_servers.json
        mcp_config_path = agent_path / "mcp_servers.json"
        if mcp_config_path.exists():
            self._load_mcp_servers_from_config(mcp_config_path)

    def _validate_credentials(self) -> None:
        """Check that required credentials are available before spawning MCP servers.

        If ``interactive`` is True and stdin is a TTY, automatically launches
        the interactive credential setup flow so the user can fix the issue
        in-place.  Re-validates after setup succeeds.

        When ``interactive`` is False (e.g. TUI callers), the CredentialError
        propagates immediately so the caller can handle it with its own UI.
        """
        if self.skip_credential_validation:
            return

        if not self._interactive:
            # Let the CredentialError propagate — caller handles UI.
            validate_agent_credentials(self.graph.nodes)
            return

        import sys

        from framework.credentials.models import CredentialError

        try:
            validate_agent_credentials(self.graph.nodes)
            return  # All good
        except CredentialError as e:
            if not sys.stdin.isatty():
                raise

            # Interactive: show the error then enter credential setup
            print(f"\n{e}", file=sys.stderr)

            from framework.credentials.validation import build_setup_session_from_error

            session = build_setup_session_from_error(e, nodes=self.graph.nodes)
            if not session.missing:
                raise

            result = session.run_interactive()
            if not result.success:
                raise CredentialError(
                    "Credential setup incomplete. "
                    "Run again after configuring the required credentials."
                ) from None

            # Re-validate after setup
            validate_agent_credentials(self.graph.nodes)

    @staticmethod
    def _import_agent_module(agent_path: Path):
        """Import an agent package from its directory path.

        Tries package import first (works when exports/ is on sys.path,
        which cli.py:_configure_paths() ensures). Falls back to direct
        file import of agent.py via importlib.util.
        """
        import importlib

        package_name = agent_path.name

        # Try importing as a package (works when exports/ is on sys.path)
        try:
            return importlib.import_module(package_name)
        except ImportError:
            pass

        # Fallback: import agent.py directly via file path
        import importlib.util

        agent_py = agent_path / "agent.py"
        if not agent_py.exists():
            raise FileNotFoundError(
                f"No importable agent found at {agent_path}. "
                f"Expected a Python package with agent.py."
            )
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.agent",
            agent_py,
            submodule_search_locations=[str(agent_path)],
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @classmethod
    def load(
        cls,
        agent_path: str | Path,
        mock_mode: bool = False,
        storage_path: Path | None = None,
        model: str | None = None,
        interactive: bool = True,
    ) -> "AgentRunner":
        """
        Load an agent from an export folder.

        Imports the agent's Python package and reads module-level variables
        (goal, nodes, edges, etc.) to build a GraphSpec. Falls back to
        agent.json if no Python module is found.

        Args:
            agent_path: Path to agent folder
            mock_mode: If True, use mock LLM responses
            storage_path: Path for runtime storage (defaults to ~/.hive/agents/{name})
            model: LLM model to use (reads from agent's default_config if None)
            interactive: If True (default), offer interactive credential setup.
                Set to False from TUI callers that handle setup via their own UI.

        Returns:
            AgentRunner instance ready to run
        """
        agent_path = Path(agent_path)

        # Try loading from Python module first (code-based agents)
        agent_py = agent_path / "agent.py"
        if agent_py.exists():
            agent_module = cls._import_agent_module(agent_path)

            goal = getattr(agent_module, "goal", None)
            nodes = getattr(agent_module, "nodes", None)
            edges = getattr(agent_module, "edges", None)

            if goal is None or nodes is None or edges is None:
                raise ValueError(
                    f"Agent at {agent_path} must define 'goal', 'nodes', and 'edges' "
                    f"in agent.py (or __init__.py)"
                )

            # Read model and max_tokens from agent's config if not explicitly provided
            agent_config = getattr(agent_module, "default_config", None)
            if model is None:
                if agent_config and hasattr(agent_config, "model"):
                    model = agent_config.model

            if agent_config and hasattr(agent_config, "max_tokens"):
                max_tokens = agent_config.max_tokens
            else:
                hive_config = get_hive_config()
                max_tokens = hive_config.get("llm", {}).get("max_tokens", DEFAULT_MAX_TOKENS)

            # Read intro_message from agent metadata (shown on TUI load)
            agent_metadata = getattr(agent_module, "metadata", None)
            intro_message = ""
            if agent_metadata and hasattr(agent_metadata, "intro_message"):
                intro_message = agent_metadata.intro_message

            # Build GraphSpec from module-level variables
            graph_kwargs: dict = {
                "id": f"{agent_path.name}-graph",
                "goal_id": goal.id,
                "version": "1.0.0",
                "entry_node": getattr(agent_module, "entry_node", nodes[0].id),
                "entry_points": getattr(agent_module, "entry_points", {}),
                "async_entry_points": getattr(agent_module, "async_entry_points", []),
                "terminal_nodes": getattr(agent_module, "terminal_nodes", []),
                "pause_nodes": getattr(agent_module, "pause_nodes", []),
                "nodes": nodes,
                "edges": edges,
                "max_tokens": max_tokens,
                "loop_config": getattr(agent_module, "loop_config", {}),
            }
            # Only pass optional fields if explicitly defined by the agent module
            conversation_mode = getattr(agent_module, "conversation_mode", None)
            if conversation_mode is not None:
                graph_kwargs["conversation_mode"] = conversation_mode
            identity_prompt = getattr(agent_module, "identity_prompt", None)
            if identity_prompt is not None:
                graph_kwargs["identity_prompt"] = identity_prompt

            graph = GraphSpec(**graph_kwargs)

            # Read runtime config (webhook settings, etc.) if defined
            agent_runtime_config = getattr(agent_module, "runtime_config", None)

            # Read pre-run hooks (e.g., credential_tester needs account selection)
            skip_cred = getattr(agent_module, "skip_credential_validation", False)
            needs_acct = getattr(agent_module, "requires_account_selection", False)
            configure_fn = getattr(agent_module, "configure_for_account", None)
            list_accts_fn = getattr(agent_module, "list_connected_accounts", None)

            return cls(
                agent_path=agent_path,
                graph=graph,
                goal=goal,
                mock_mode=mock_mode,
                storage_path=storage_path,
                model=model,
                intro_message=intro_message,
                runtime_config=agent_runtime_config,
                interactive=interactive,
                skip_credential_validation=skip_cred,
                requires_account_selection=needs_acct,
                configure_for_account=configure_fn,
                list_accounts=list_accts_fn,
            )

        # Fallback: load from agent.json (legacy JSON-based agents)
        agent_json_path = agent_path / "agent.json"
        if not agent_json_path.exists():
            raise FileNotFoundError(f"No agent.py or agent.json found in {agent_path}")

        with open(agent_json_path) as f:
            graph, goal = load_agent_export(f.read())

        return cls(
            agent_path=agent_path,
            graph=graph,
            goal=goal,
            mock_mode=mock_mode,
            storage_path=storage_path,
            model=model,
            interactive=interactive,
        )

    def register_tool(
        self,
        name: str,
        tool_or_func: Tool | Callable,
        executor: Callable | None = None,
    ) -> None:
        """
        Register a tool for use by the agent.

        Args:
            name: Tool name
            tool_or_func: Either a Tool object or a callable function
            executor: Executor function (required if tool_or_func is a Tool)
        """
        if isinstance(tool_or_func, Tool):
            if executor is None:
                raise ValueError("executor required when registering a Tool object")
            self._tool_registry.register(name, tool_or_func, executor)
        else:
            # It's a function, auto-generate Tool
            self._tool_registry.register_function(tool_or_func, name=name)

    def register_tools_from_module(self, module_path: Path) -> int:
        """
        Auto-discover and register tools from a Python module.

        Args:
            module_path: Path to tools.py file

        Returns:
            Number of tools discovered
        """
        return self._tool_registry.discover_from_module(module_path)

    def register_mcp_server(
        self,
        name: str,
        transport: str,
        **config_kwargs,
    ) -> int:
        """
        Register an MCP server and discover its tools.

        Args:
            name: Server name
            transport: "stdio" or "http"
            **config_kwargs: Additional configuration (command, args, url, etc.)

        Returns:
            Number of tools registered from this server

        Example:
            # Register STDIO MCP server
            runner.register_mcp_server(
                name="tools",
                transport="stdio",
                command="python",
                args=["-m", "aden_tools.mcp_server", "--stdio"],
                cwd="/path/to/tools"
            )

            # Register HTTP MCP server
            runner.register_mcp_server(
                name="tools",
                transport="http",
                url="http://localhost:4001"
            )
        """
        server_config = {
            "name": name,
            "transport": transport,
            **config_kwargs,
        }
        return self._tool_registry.register_mcp_server(server_config)

    def _load_mcp_servers_from_config(self, config_path: Path) -> None:
        """Load and register MCP servers from a configuration file."""
        self._tool_registry.load_mcp_config(config_path)

    def set_approval_callback(self, callback: Callable) -> None:
        """
        Set a callback for human-in-the-loop approval during execution.

        Args:
            callback: Function to call for approval (receives node info, returns bool)
        """
        self._approval_callback = callback

    def _setup(self) -> None:
        """Set up runtime, LLM, and executor."""
        # Configure structured logging (auto-detects JSON vs human-readable)
        from framework.observability import configure_logging

        configure_logging(level="INFO", format="auto")

        # Set up session context for tools (workspace_id, agent_id, session_id)
        workspace_id = "default"  # Could be derived from storage path
        agent_id = self.graph.id or "unknown"
        # Use "current" as a stable session_id for persistent memory
        session_id = "current"

        self._tool_registry.set_session_context(
            workspace_id=workspace_id,
            agent_id=agent_id,
            session_id=session_id,
        )

        # Create LLM provider
        # Uses LiteLLM which auto-detects the provider from model name
        if self.mock_mode:
            # Use mock LLM for testing without real API calls
            from framework.llm.mock import MockLLMProvider

            self._llm = MockLLMProvider(model=self.model)
        else:
            from framework.llm.litellm import LiteLLMProvider

            # Check if Claude Code subscription is configured
            config = get_hive_config()
            llm_config = config.get("llm", {})
            use_claude_code = llm_config.get("use_claude_code_subscription", False)
            api_base = llm_config.get("api_base")

            api_key = None
            if use_claude_code:
                # Get OAuth token from Claude Code subscription
                api_key = get_claude_code_token()
                if not api_key:
                    print("Warning: Claude Code subscription configured but no token found.")
                    print("Run 'claude' to authenticate, then try again.")

            if api_key and use_claude_code:
                # Use litellm's built-in Anthropic OAuth support.
                # The lowercase "authorization" key triggers OAuth detection which
                # adds the required anthropic-beta and browser-access headers.
                self._llm = LiteLLMProvider(
                    model=self.model,
                    api_key=api_key,
                    api_base=api_base,
                    extra_headers={"authorization": f"Bearer {api_key}"},
                )
            else:
                # Local models (e.g. Ollama) don't need an API key
                if self._is_local_model(self.model):
                    self._llm = LiteLLMProvider(
                        model=self.model,
                        api_base=api_base,
                    )
                else:
                    # Fall back to environment variable
                    # First check api_key_env_var from config (set by quickstart)
                    api_key_env = llm_config.get("api_key_env_var") or self._get_api_key_env_var(
                        self.model
                    )
                    if api_key_env and os.environ.get(api_key_env):
                        self._llm = LiteLLMProvider(
                            model=self.model,
                            api_key=os.environ[api_key_env],
                            api_base=api_base,
                        )
                    else:
                        # Fall back to credential store
                        api_key = self._get_api_key_from_credential_store()
                        if api_key:
                            self._llm = LiteLLMProvider(
                                model=self.model, api_key=api_key, api_base=api_base
                            )
                            # Set env var so downstream code (e.g. cleanup LLM in
                            # node._extract_json) can also find it
                            if api_key_env:
                                os.environ[api_key_env] = api_key
                        elif api_key_env:
                            print(f"Warning: {api_key_env} not set. LLM calls will fail.")
                            print(f"Set it with: export {api_key_env}=your-api-key")

            # Fail fast if the agent needs an LLM but none was configured
            if self._llm is None:
                has_llm_nodes = any(node.node_type == "event_loop" for node in self.graph.nodes)
                if has_llm_nodes:
                    from framework.credentials.models import CredentialError

                    if self._is_local_model(self.model):
                        raise CredentialError(
                            f"Failed to initialize LLM for local model '{self.model}'. "
                            f"Ensure your local LLM server is running "
                            f"(e.g. 'ollama serve' for Ollama)."
                        )
                    api_key_env = self._get_api_key_env_var(self.model)
                    hint = (
                        f"Set it with: export {api_key_env}=your-api-key"
                        if api_key_env
                        else "Configure an API key for your LLM provider."
                    )
                    raise CredentialError(f"LLM API key not found for model '{self.model}'. {hint}")

        # Get tools for runtime
        tools = list(self._tool_registry.get_tools().values())
        tool_executor = self._tool_registry.get_executor()

        # Collect connected account info for system prompt injection
        accounts_prompt = ""
        accounts_data: list[dict] | None = None
        tool_provider_map: dict[str, str] | None = None
        try:
            from aden_tools.credentials.store_adapter import CredentialStoreAdapter

            adapter = CredentialStoreAdapter.default()
            accounts_data = adapter.get_all_account_info()
            tool_provider_map = adapter.get_tool_provider_map()
            if accounts_data:
                from framework.graph.prompt_composer import build_accounts_prompt

                accounts_prompt = build_accounts_prompt(accounts_data, tool_provider_map)
        except Exception:
            pass  # Best-effort — agent works without account info

        self._setup_agent_runtime(
            tools,
            tool_executor,
            accounts_prompt=accounts_prompt,
            accounts_data=accounts_data,
            tool_provider_map=tool_provider_map,
        )

    def _get_api_key_env_var(self, model: str) -> str | None:
        """Get the environment variable name for the API key based on model name."""
        model_lower = model.lower()

        # Map model prefixes to API key environment variables
        # LiteLLM uses these conventions
        if model_lower.startswith("cerebras/"):
            return "CEREBRAS_API_KEY"
        elif model_lower.startswith("openai/") or model_lower.startswith("gpt-"):
            return "OPENAI_API_KEY"
        elif model_lower.startswith("anthropic/") or model_lower.startswith("claude"):
            return "ANTHROPIC_API_KEY"
        elif model_lower.startswith("gemini/") or model_lower.startswith("google/"):
            return "GEMINI_API_KEY"
        elif model_lower.startswith("mistral/"):
            return "MISTRAL_API_KEY"
        elif model_lower.startswith("groq/"):
            return "GROQ_API_KEY"
        elif self._is_local_model(model_lower):
            return None  # Local models don't need an API key
        elif model_lower.startswith("azure/"):
            return "AZURE_API_KEY"
        elif model_lower.startswith("cohere/"):
            return "COHERE_API_KEY"
        elif model_lower.startswith("replicate/"):
            return "REPLICATE_API_KEY"
        elif model_lower.startswith("together/"):
            return "TOGETHER_API_KEY"
        else:
            # Default: assume OpenAI-compatible
            return "OPENAI_API_KEY"

    def _get_api_key_from_credential_store(self) -> str | None:
        """Get the LLM API key from the encrypted credential store.

        Maps model name to credential store ID (e.g. "anthropic/..." -> "anthropic")
        and retrieves the key via CredentialStore.get().
        """
        if not os.environ.get("HIVE_CREDENTIAL_KEY"):
            return None

        # Map model prefix to credential store ID
        model_lower = self.model.lower()
        cred_id = None
        if model_lower.startswith("anthropic/") or model_lower.startswith("claude"):
            cred_id = "anthropic"
        # Add more mappings as providers are added to LLM_CREDENTIALS

        if cred_id is None:
            return None

        try:
            from framework.credentials import CredentialStore

            store = CredentialStore.with_encrypted_storage()
            return store.get(cred_id)
        except Exception:
            return None

    @staticmethod
    def _is_local_model(model: str) -> bool:
        """Check if a model is a local model that doesn't require an API key.

        Local providers like Ollama run on the user's machine and do not
        need any authentication credentials.
        """
        LOCAL_PREFIXES = (
            "ollama/",
            "ollama_chat/",
            "vllm/",
            "lm_studio/",
            "llamacpp/",
        )
        return model.lower().startswith(LOCAL_PREFIXES)

    def _setup_agent_runtime(
        self,
        tools: list,
        tool_executor: Callable | None,
        accounts_prompt: str = "",
        accounts_data: list[dict] | None = None,
        tool_provider_map: dict[str, str] | None = None,
    ) -> None:
        """Set up multi-entry-point execution using AgentRuntime."""
        # Convert AsyncEntryPointSpec to EntryPointSpec for AgentRuntime
        entry_points = []
        for async_ep in self.graph.async_entry_points:
            ep = EntryPointSpec(
                id=async_ep.id,
                name=async_ep.name,
                entry_node=async_ep.entry_node,
                trigger_type=async_ep.trigger_type,
                trigger_config=async_ep.trigger_config,
                isolation_level=async_ep.isolation_level,
                priority=async_ep.priority,
                max_concurrent=async_ep.max_concurrent,
            )
            entry_points.append(ep)

        # Always create a primary entry point for the graph's entry node.
        # For multi-entry-point agents this ensures the primary path (e.g.
        # user-facing rule setup) is reachable alongside async entry points.
        if self.graph.entry_node:
            entry_points.insert(
                0,
                EntryPointSpec(
                    id="default",
                    name="Default",
                    entry_node=self.graph.entry_node,
                    trigger_type="manual",
                    isolation_level="shared",
                ),
            )

        # Create AgentRuntime with all entry points
        log_store = RuntimeLogStore(base_path=self._storage_path / "runtime_logs")

        # Enable checkpointing by default for resumable sessions
        from framework.graph.checkpoint_config import CheckpointConfig

        checkpoint_config = CheckpointConfig(
            enabled=True,
            checkpoint_on_node_start=False,  # Only checkpoint after nodes complete
            checkpoint_on_node_complete=True,
            checkpoint_max_age_days=7,
            async_checkpoint=True,  # Non-blocking
        )

        # Handle runtime_config - ensure it's AgentRuntimeConfig, not RuntimeConfig
        # RuntimeConfig is for LLM settings; AgentRuntimeConfig is for AgentRuntime settings
        runtime_config = None
        if self.runtime_config is not None:
            from framework.config import RuntimeConfig

            # If it's a RuntimeConfig (LLM config), don't pass it
            if isinstance(self.runtime_config, RuntimeConfig):
                runtime_config = None
            else:
                # It's already an AgentRuntimeConfig or compatible type
                runtime_config = self.runtime_config

        self._agent_runtime = create_agent_runtime(
            graph=self.graph,
            goal=self.goal,
            storage_path=self._storage_path,
            entry_points=entry_points,
            llm=self._llm,
            tools=tools,
            tool_executor=tool_executor,
            runtime_log_store=log_store,
            checkpoint_config=checkpoint_config,
            config=runtime_config,
            graph_id=self.graph.id or self.agent_path.name,
            accounts_prompt=accounts_prompt,
            accounts_data=accounts_data,
            tool_provider_map=tool_provider_map,
        )

        # Pass intro_message through for TUI display
        self._agent_runtime.intro_message = self.intro_message

    async def run(
        self,
        input_data: dict | None = None,
        session_state: dict | None = None,
        entry_point_id: str | None = None,
    ) -> ExecutionResult:
        """
        Execute the agent with given input data.

        Validates credentials before execution. If any required credentials
        are missing, returns an error result with instructions on how to
        provide them.

        For single-entry-point agents, this is the standard execution path.
        For multi-entry-point agents, you can optionally specify which entry point to use.

        Args:
            input_data: Input data for the agent (e.g., {"lead_id": "123"})
            session_state: Optional session state to resume from
            entry_point_id: For multi-entry-point agents, which entry point to trigger
                           (defaults to first entry point or "default")

        Returns:
            ExecutionResult with output, path, and metrics
        """
        # Validate credentials before execution (fail-fast)
        validation = self.validate()
        if validation.missing_credentials:
            error_lines = ["Cannot run agent: missing required credentials\n"]
            for warning in validation.warnings:
                if "Missing " in warning:
                    error_lines.append(f"  {warning}")
            error_lines.append("\nSet the required environment variables and re-run the agent.")
            error_msg = "\n".join(error_lines)
            return ExecutionResult(
                success=False,
                error=error_msg,
            )

        return await self._run_with_agent_runtime(
            input_data=input_data or {},
            entry_point_id=entry_point_id,
            session_state=session_state,
        )

    async def _run_with_agent_runtime(
        self,
        input_data: dict,
        entry_point_id: str | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult:
        """Run using AgentRuntime."""
        import sys

        if self._agent_runtime is None:
            self._setup()

        # Start runtime if not running
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

        # Set up stdin-based I/O for client-facing nodes in headless mode.
        # When a client_facing EventLoopNode calls ask_user(), it emits
        # CLIENT_INPUT_REQUESTED on the event bus and blocks.  We subscribe
        # a handler that prints the prompt and reads from stdin, then injects
        # the user's response back into the node to unblock it.
        has_client_facing = any(n.client_facing for n in self.graph.nodes)
        sub_ids: list[str] = []

        if has_client_facing and sys.stdin.isatty():
            from framework.runtime.event_bus import EventType

            runtime = self._agent_runtime

            async def _handle_client_output(event):
                """Print agent output to stdout as it streams."""
                content = event.data.get("content", "")
                if content:
                    print(content, end="", flush=True)

            async def _handle_input_requested(event):
                """Read user input from stdin and inject it into the node."""
                import asyncio

                node_id = event.node_id
                try:
                    loop = asyncio.get_event_loop()
                    user_input = await loop.run_in_executor(None, input, "\n>>> ")
                except EOFError:
                    user_input = ""

                # Inject into the waiting EventLoopNode via runtime
                await runtime.inject_input(node_id, user_input)

            sub_ids.append(
                runtime.subscribe_to_events(
                    event_types=[EventType.CLIENT_OUTPUT_DELTA],
                    handler=_handle_client_output,
                )
            )
            sub_ids.append(
                runtime.subscribe_to_events(
                    event_types=[EventType.CLIENT_INPUT_REQUESTED],
                    handler=_handle_input_requested,
                )
            )

        # Determine entry point
        if entry_point_id is None:
            # Use first entry point or "default" if no entry points defined
            entry_points = self._agent_runtime.get_entry_points()
            if entry_points:
                entry_point_id = entry_points[0].id
            else:
                entry_point_id = "default"

        try:
            # Trigger and wait for result
            result = await self._agent_runtime.trigger_and_wait(
                entry_point_id=entry_point_id,
                input_data=input_data,
                session_state=session_state,
            )

            # Return result or create error result
            if result is not None:
                return result
            else:
                return ExecutionResult(
                    success=False,
                    error="Execution timed out or failed to complete",
                )
        finally:
            # Clean up subscriptions
            for sub_id in sub_ids:
                self._agent_runtime.unsubscribe_from_events(sub_id)

    # === Runtime API ===

    async def start(self) -> None:
        """Start the agent runtime."""
        if self._agent_runtime is None:
            self._setup()

        await self._agent_runtime.start()

    async def stop(self) -> None:
        """Stop the agent runtime."""
        if self._agent_runtime is not None:
            await self._agent_runtime.stop()

    async def trigger(
        self,
        entry_point_id: str,
        input_data: dict[str, Any],
        correlation_id: str | None = None,
    ) -> str:
        """
        Trigger execution at a specific entry point (non-blocking).

        Returns execution ID for tracking.

        Args:
            entry_point_id: Which entry point to trigger
            input_data: Input data for the execution
            correlation_id: Optional ID to correlate related executions

        Returns:
            Execution ID for tracking
        """
        if self._agent_runtime is None:
            self._setup()

        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

        return await self._agent_runtime.trigger(
            entry_point_id=entry_point_id,
            input_data=input_data,
            correlation_id=correlation_id,
        )

    async def get_goal_progress(self) -> dict[str, Any]:
        """
        Get goal progress across all execution streams.

        Returns:
            Dict with overall_progress, criteria_status, constraint_violations, etc.
        """
        if self._agent_runtime is None:
            self._setup()

        return await self._agent_runtime.get_goal_progress()

    def get_entry_points(self) -> list[EntryPointSpec]:
        """
        Get all registered entry points.

        Returns:
            List of EntryPointSpec objects
        """
        if self._agent_runtime is None:
            self._setup()

        return self._agent_runtime.get_entry_points()

    @property
    def is_running(self) -> bool:
        """Check if the agent runtime is running (for multi-entry-point agents)."""
        if self._agent_runtime is None:
            return False
        return self._agent_runtime.is_running

    def info(self) -> AgentInfo:
        """Return agent metadata (nodes, edges, goal, required tools)."""
        # Extract required tools from nodes
        required_tools = set()
        nodes_info = []

        for node in self.graph.nodes:
            node_info = {
                "id": node.id,
                "name": node.name,
                "description": node.description,
                "type": node.node_type,
                "input_keys": node.input_keys,
                "output_keys": node.output_keys,
            }

            if node.tools:
                required_tools.update(node.tools)
                node_info["tools"] = node.tools

            nodes_info.append(node_info)

        edges_info = [
            {
                "id": edge.id,
                "source": edge.source,
                "target": edge.target,
                "condition": edge.condition.value,
            }
            for edge in self.graph.edges
        ]

        # Build async entry points info
        async_entry_points_info = [
            {
                "id": ep.id,
                "name": ep.name,
                "entry_node": ep.entry_node,
                "trigger_type": ep.trigger_type,
                "isolation_level": ep.isolation_level,
                "max_concurrent": ep.max_concurrent,
            }
            for ep in self.graph.async_entry_points
        ]

        return AgentInfo(
            name=self.graph.id,
            description=self.graph.description,
            goal_name=self.goal.name,
            goal_description=self.goal.description,
            node_count=len(self.graph.nodes),
            edge_count=len(self.graph.edges),
            nodes=nodes_info,
            edges=edges_info,
            entry_node=self.graph.entry_node,
            terminal_nodes=self.graph.terminal_nodes,
            success_criteria=[
                {
                    "id": sc.id,
                    "description": sc.description,
                    "metric": sc.metric,
                    "target": sc.target,
                }
                for sc in self.goal.success_criteria
            ],
            constraints=[
                {"id": c.id, "description": c.description, "type": c.constraint_type}
                for c in self.goal.constraints
            ],
            required_tools=sorted(required_tools),
            has_tools_module=(self.agent_path / "tools.py").exists(),
            async_entry_points=async_entry_points_info,
            is_multi_entry_point=self._uses_async_entry_points,
        )

    def validate(self) -> ValidationResult:
        """
        Check agent is valid and all required tools are registered.

        Returns:
            ValidationResult with errors, warnings, and missing tools
        """
        errors = []
        warnings = []
        missing_tools = []

        # Validate graph structure
        graph_errors = self.graph.validate()
        errors.extend(graph_errors)

        # Check goal has success criteria
        if not self.goal.success_criteria:
            warnings.append("Goal has no success criteria defined")

        # Check required tools are registered
        info = self.info()
        for tool_name in info.required_tools:
            if not self._tool_registry.has_tool(tool_name):
                missing_tools.append(tool_name)

        if missing_tools:
            warnings.append(f"Missing tool implementations: {', '.join(missing_tools)}")

        # Check credentials for required tools and node types
        # Uses CredentialStoreAdapter.default() which includes Aden sync support
        missing_credentials = []
        try:
            from aden_tools.credentials.store_adapter import CredentialStoreAdapter

            adapter = CredentialStoreAdapter.default()

            # Check tool credentials
            for _cred_name, spec in adapter.get_missing_for_tools(list(info.required_tools)):
                missing_credentials.append(spec.env_var)
                affected_tools = [t for t in info.required_tools if t in spec.tools]
                tools_str = ", ".join(affected_tools)
                warning_msg = f"Missing {spec.env_var} for {tools_str}"
                if spec.help_url:
                    warning_msg += f"\n  Get it at: {spec.help_url}"
                warnings.append(warning_msg)

            # Check node type credentials (e.g., ANTHROPIC_API_KEY for LLM nodes)
            node_types = list({node.node_type for node in self.graph.nodes})
            for _cred_name, spec in adapter.get_missing_for_node_types(node_types):
                missing_credentials.append(spec.env_var)
                affected_types = [t for t in node_types if t in spec.node_types]
                types_str = ", ".join(affected_types)
                warning_msg = f"Missing {spec.env_var} for {types_str} nodes"
                if spec.help_url:
                    warning_msg += f"\n  Get it at: {spec.help_url}"
                warnings.append(warning_msg)
        except ImportError:
            # aden_tools not installed - fall back to direct check
            has_llm_nodes = any(node.node_type == "event_loop" for node in self.graph.nodes)
            if has_llm_nodes:
                api_key_env = self._get_api_key_env_var(self.model)
                if api_key_env and not os.environ.get(api_key_env):
                    if api_key_env not in missing_credentials:
                        missing_credentials.append(api_key_env)
                    warnings.append(
                        f"Agent has LLM nodes but {api_key_env} not set (model: {self.model})"
                    )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            missing_tools=missing_tools,
            missing_credentials=missing_credentials,
        )

    async def can_handle(
        self, request: dict, llm: LLMProvider | None = None
    ) -> "CapabilityResponse":
        """
        Ask the agent if it can handle this request.

        Uses LLM to evaluate the request against the agent's goal and capabilities.

        Args:
            request: The request to evaluate
            llm: LLM provider to use (uses self._llm if not provided)

        Returns:
            CapabilityResponse with level, confidence, and reasoning
        """
        from framework.runner.protocol import CapabilityLevel, CapabilityResponse

        # Use provided LLM or set up our own
        eval_llm = llm
        if eval_llm is None:
            if self._llm is None:
                self._setup()
            eval_llm = self._llm

        # If still no LLM (mock mode), do keyword matching
        if eval_llm is None:
            return self._keyword_capability_check(request)

        # Build context about this agent
        info = self.info()
        agent_context = f"""Agent: {info.name}
Goal: {info.goal_name}
Description: {info.goal_description}

What this agent does:
{info.description}

Nodes in the workflow:
{chr(10).join(f"- {n['name']}: {n['description']}" for n in info.nodes[:5])}
{"..." if len(info.nodes) > 5 else ""}
"""

        # Ask LLM to evaluate
        prompt = f"""You are evaluating whether an agent can handle a request.

{agent_context}

Request to evaluate:
{json.dumps(request, indent=2)}

Evaluate how well this agent can handle this request. Consider:
1. Does the request match what this agent is designed to do?
2. Does the agent have the required capabilities?
3. How confident are you in this assessment?

Respond with JSON only:
{{
    "level": "best_fit" | "can_handle" | "uncertain" | "cannot_handle",
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation",
    "estimated_steps": number or null
}}"""

        try:
            response = await eval_llm.acomplete(
                messages=[{"role": "user", "content": prompt}],
                system="You are a capability evaluator. Respond with JSON only.",
                max_tokens=256,
            )

            # Parse response
            import re

            json_match = re.search(r"\{[^{}]*\}", response.content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                level_map = {
                    "best_fit": CapabilityLevel.BEST_FIT,
                    "can_handle": CapabilityLevel.CAN_HANDLE,
                    "uncertain": CapabilityLevel.UNCERTAIN,
                    "cannot_handle": CapabilityLevel.CANNOT_HANDLE,
                }
                return CapabilityResponse(
                    agent_name=info.name,
                    level=level_map.get(data.get("level", "uncertain"), CapabilityLevel.UNCERTAIN),
                    confidence=float(data.get("confidence", 0.5)),
                    reasoning=data.get("reasoning", ""),
                    estimated_steps=data.get("estimated_steps"),
                )
        except Exception:
            # Fall back to keyword matching on error
            pass

        return self._keyword_capability_check(request)

    def _keyword_capability_check(self, request: dict) -> "CapabilityResponse":
        """Simple keyword-based capability check (fallback when no LLM)."""
        from framework.runner.protocol import CapabilityLevel, CapabilityResponse

        info = self.info()
        request_str = json.dumps(request).lower()
        description_lower = info.description.lower()
        goal_lower = info.goal_description.lower()

        # Check for keyword matches
        matches = 0
        keywords = request_str.split()
        for keyword in keywords:
            if len(keyword) > 3:  # Skip short words
                if keyword in description_lower or keyword in goal_lower:
                    matches += 1

        # Determine level based on matches
        match_ratio = matches / max(len(keywords), 1)
        if match_ratio > 0.3:
            level = CapabilityLevel.CAN_HANDLE
            confidence = min(0.7, match_ratio + 0.3)
        elif match_ratio > 0.1:
            level = CapabilityLevel.UNCERTAIN
            confidence = 0.4
        else:
            level = CapabilityLevel.CANNOT_HANDLE
            confidence = 0.6

        return CapabilityResponse(
            agent_name=info.name,
            level=level,
            confidence=confidence,
            reasoning=f"Keyword match ratio: {match_ratio:.2f}",
            estimated_steps=info.node_count if level != CapabilityLevel.CANNOT_HANDLE else None,
        )

    async def receive_message(self, message: "AgentMessage") -> "AgentMessage":
        """
        Handle a message from the orchestrator or another agent.

        Args:
            message: The incoming message

        Returns:
            Response message
        """
        from framework.runner.protocol import MessageType

        info = self.info()

        # Handle capability check
        if message.type == MessageType.CAPABILITY_CHECK:
            capability = await self.can_handle(message.content)
            return message.reply(
                from_agent=info.name,
                content={
                    "level": capability.level.value,
                    "confidence": capability.confidence,
                    "reasoning": capability.reasoning,
                    "estimated_steps": capability.estimated_steps,
                },
                type=MessageType.CAPABILITY_RESPONSE,
            )

        # Handle request - run the agent
        if message.type == MessageType.REQUEST:
            result = await self.run(message.content)
            return message.reply(
                from_agent=info.name,
                content={
                    "success": result.success,
                    "output": result.output,
                    "path": result.path,
                    "error": result.error,
                },
                type=MessageType.RESPONSE,
            )

        # Handle handoff - another agent is passing work
        if message.type == MessageType.HANDOFF:
            # Extract context from handoff and run
            context = message.content.get("context", {})
            context["_handoff_from"] = message.from_agent
            context["_handoff_reason"] = message.content.get("reason", "")
            result = await self.run(context)
            return message.reply(
                from_agent=info.name,
                content={
                    "success": result.success,
                    "output": result.output,
                    "handoff_handled": True,
                },
                type=MessageType.RESPONSE,
            )

        # Unknown message type
        return message.reply(
            from_agent=info.name,
            content={"error": f"Unknown message type: {message.type}"},
            type=MessageType.RESPONSE,
        )

    @classmethod
    async def setup_as_secondary(
        cls,
        agent_path: str | Path,
        runtime: AgentRuntime,
        graph_id: str | None = None,
    ) -> str:
        """Load an agent and register it as a secondary graph on *runtime*.

        Uses :meth:`AgentRunner.load` to parse the agent, then calls
        :meth:`AgentRuntime.add_graph` with the extracted graph, goal,
        and entry points.

        Args:
            agent_path: Path to the agent directory
            runtime: The running AgentRuntime to attach to
            graph_id: Optional graph identifier (defaults to directory name)

        Returns:
            The graph_id used for registration
        """
        agent_path = Path(agent_path)
        runner = cls.load(agent_path)
        gid = graph_id or agent_path.name

        # Build entry points
        entry_points: dict[str, EntryPointSpec] = {}
        if runner.graph.entry_node:
            entry_points["default"] = EntryPointSpec(
                id="default",
                name="Default",
                entry_node=runner.graph.entry_node,
                trigger_type="manual",
                isolation_level="shared",
            )
        for aep in runner.graph.async_entry_points:
            entry_points[aep.id] = EntryPointSpec(
                id=aep.id,
                name=aep.name,
                entry_node=aep.entry_node,
                trigger_type=aep.trigger_type,
                trigger_config=aep.trigger_config,
                isolation_level=aep.isolation_level,
                priority=aep.priority,
                max_concurrent=aep.max_concurrent,
            )

        await runtime.add_graph(
            graph_id=gid,
            graph=runner.graph,
            goal=runner.goal,
            entry_points=entry_points,
        )
        return gid

    def cleanup(self) -> None:
        """Clean up resources (synchronous)."""
        # Clean up MCP client connections
        self._tool_registry.cleanup()

        if self._temp_dir:
            self._temp_dir.cleanup()
            self._temp_dir = None

    async def cleanup_async(self) -> None:
        """Clean up resources (asynchronous)."""
        # Stop agent runtime if running
        if self._agent_runtime is not None and self._agent_runtime.is_running:
            await self._agent_runtime.stop()

        # Run synchronous cleanup
        self.cleanup()

    async def __aenter__(self) -> "AgentRunner":
        """Context manager entry."""
        self._setup()
        if self._agent_runtime is not None:
            await self._agent_runtime.start()
        return self

    async def __aexit__(self, *args) -> None:
        """Context manager exit."""
        await self.cleanup_async()

    def __del__(self) -> None:
        """Destructor - cleanup temp dir."""
        self.cleanup()
