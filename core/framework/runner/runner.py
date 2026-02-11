"""Agent Runner - loads and runs exported agents."""

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.config import get_hive_config, get_preferred_model
from framework.graph import Goal
from framework.graph.edge import (
    DEFAULT_MAX_TOKENS,
    AsyncEntryPointSpec,
    EdgeCondition,
    EdgeSpec,
    GraphSpec,
)
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.graph.node import NodeSpec
from framework.llm.provider import LLMProvider, Tool
from framework.runner.tool_registry import ToolRegistry

# Multi-entry-point runtime imports
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.core import Runtime
from framework.runtime.execution_stream import EntryPointSpec
from framework.runtime.runtime_log_store import RuntimeLogStore
from framework.runtime.runtime_logger import RuntimeLogger

if TYPE_CHECKING:
    from framework.runner.protocol import AgentMessage, CapabilityResponse


logger = logging.getLogger(__name__)


def _ensure_credential_key_env() -> None:
    """Load HIVE_CREDENTIAL_KEY from shell config if not already in environment.

    The setup-credentials skill writes the encryption key to ~/.zshrc or ~/.bashrc.
    If the user hasn't sourced their config in the current shell, this reads it
    directly so the runner (and any MCP subprocesses it spawns) can unlock the
    encrypted credential store.

    Only HIVE_CREDENTIAL_KEY is loaded this way — all other secrets (API keys, etc.)
    come from the credential store itself.
    """
    if os.environ.get("HIVE_CREDENTIAL_KEY"):
        return

    try:
        from aden_tools.credentials.shell_config import check_env_var_in_shell_config

        found, value = check_env_var_in_shell_config("HIVE_CREDENTIAL_KEY")
        if found and value:
            os.environ["HIVE_CREDENTIAL_KEY"] = value
            logger.debug("Loaded HIVE_CREDENTIAL_KEY from shell config")
    except ImportError:
        pass


CLAUDE_CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"


def get_claude_code_token() -> str | None:
    """
    Get the OAuth token from Claude Code subscription.

    Reads from ~/.claude/.credentials.json which is created by the
    Claude Code CLI when users authenticate with their subscription.

    Returns:
        The access token if available, None otherwise.
    """
    if not CLAUDE_CREDENTIALS_FILE.exists():
        return None
    try:
        with open(CLAUDE_CREDENTIALS_FILE) as f:
            creds = json.load(f)
        return creds.get("claudeAiOauth", {}).get("accessToken")
    except (json.JSONDecodeError, OSError):
        return None


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
        enable_tui: bool = False,
        intro_message: str = "",
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
            enable_tui: If True, forces use of AgentRuntime with EventBus
            intro_message: Optional greeting shown to user on TUI load
        """
        self.agent_path = agent_path
        self.graph = graph
        self.goal = goal
        self.mock_mode = mock_mode
        self.model = model or self._resolve_default_model()
        self.enable_tui = enable_tui
        self.intro_message = intro_message

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
        self._runtime: Runtime | None = None
        self._llm: LLMProvider | None = None
        self._executor: GraphExecutor | None = None
        self._approval_callback: Callable | None = None

        # Multi-entry-point support (AgentRuntime)
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

        Raises CredentialError with actionable guidance if any are missing.
        Uses graph node specs + CREDENTIAL_SPECS — no tool registry needed.
        """
        required_tools: set[str] = set()
        for node in self.graph.nodes:
            if node.tools:
                required_tools.update(node.tools)
        node_types: set[str] = {node.node_type for node in self.graph.nodes}

        try:
            from aden_tools.credentials import CREDENTIAL_SPECS

            from framework.credentials import CredentialStore
            from framework.credentials.storage import (
                CompositeStorage,
                EncryptedFileStorage,
                EnvVarStorage,
            )
        except ImportError:
            return  # aden_tools not installed, skip check

        # Build credential store (same logic as validate())
        env_mapping = {
            (spec.credential_id or name): spec.env_var for name, spec in CREDENTIAL_SPECS.items()
        }
        storages: list = [EnvVarStorage(env_mapping=env_mapping)]
        if os.environ.get("HIVE_CREDENTIAL_KEY"):
            storages.insert(0, EncryptedFileStorage())
        if len(storages) == 1:
            storage = storages[0]
        else:
            storage = CompositeStorage(primary=storages[0], fallbacks=storages[1:])
        store = CredentialStore(storage=storage)

        # Build reverse mappings
        tool_to_cred: dict[str, str] = {}
        node_type_to_cred: dict[str, str] = {}
        for cred_name, spec in CREDENTIAL_SPECS.items():
            for tool_name in spec.tools:
                tool_to_cred[tool_name] = cred_name
            for nt in spec.node_types:
                node_type_to_cred[nt] = cred_name

        missing: list[str] = []
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
                affected = sorted(t for t in required_tools if t in spec.tools)
                entry = f"  {spec.env_var} for {', '.join(affected)}"
                if spec.help_url:
                    entry += f"\n    Get it at: {spec.help_url}"
                missing.append(entry)

        # Check node type credentials (e.g., ANTHROPIC_API_KEY for LLM nodes)
        for nt in sorted(node_types):
            cred_name = node_type_to_cred.get(nt)
            if cred_name is None or cred_name in checked:
                continue
            checked.add(cred_name)
            spec = CREDENTIAL_SPECS[cred_name]
            cred_id = spec.credential_id or cred_name
            if spec.required and not store.is_available(cred_id):
                affected_types = sorted(t for t in node_types if t in spec.node_types)
                entry = f"  {spec.env_var} for {', '.join(affected_types)} nodes"
                if spec.help_url:
                    entry += f"\n    Get it at: {spec.help_url}"
                missing.append(entry)

        if missing:
            from framework.credentials.models import CredentialError

            lines = ["Missing required credentials:\n"]
            lines.extend(missing)
            lines.append("\nTo fix: run /hive-credentials in Claude Code.")
            raise CredentialError("\n".join(lines))

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
        enable_tui: bool = False,
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
            enable_tui: If True, forces use of AgentRuntime with EventBus

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
            graph = GraphSpec(
                id=f"{agent_path.name}-graph",
                goal_id=goal.id,
                version="1.0.0",
                entry_node=getattr(agent_module, "entry_node", nodes[0].id),
                entry_points=getattr(agent_module, "entry_points", {}),
                terminal_nodes=getattr(agent_module, "terminal_nodes", []),
                pause_nodes=getattr(agent_module, "pause_nodes", []),
                nodes=nodes,
                edges=edges,
                max_tokens=max_tokens,
            )

            return cls(
                agent_path=agent_path,
                graph=graph,
                goal=goal,
                mock_mode=mock_mode,
                storage_path=storage_path,
                model=model,
                enable_tui=enable_tui,
                intro_message=intro_message,
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
            enable_tui=enable_tui,
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
        # If executor already exists, update it
        if self._executor is not None:
            self._executor.approval_callback = callback

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

            api_key = None
            if use_claude_code:
                # Get OAuth token from Claude Code subscription
                api_key = get_claude_code_token()
                if not api_key:
                    print("Warning: Claude Code subscription configured but no token found.")
                    print("Run 'claude' to authenticate, then try again.")

            if api_key:
                # Use Claude Code subscription token
                self._llm = LiteLLMProvider(model=self.model, api_key=api_key)
            else:
                # Fall back to environment variable
                api_key_env = self._get_api_key_env_var(self.model)
                if api_key_env and os.environ.get(api_key_env):
                    self._llm = LiteLLMProvider(model=self.model)
                else:
                    # Fall back to credential store
                    api_key = self._get_api_key_from_credential_store()
                    if api_key:
                        self._llm = LiteLLMProvider(model=self.model, api_key=api_key)
                        # Set env var so downstream code (e.g. cleanup LLM in
                        # node._extract_json) can also find it
                        if api_key_env:
                            os.environ[api_key_env] = api_key
                    elif api_key_env:
                        print(f"Warning: {api_key_env} not set. LLM calls will fail.")
                        print(f"Set it with: export {api_key_env}=your-api-key")

        # Get tools for executor/runtime
        tools = list(self._tool_registry.get_tools().values())
        tool_executor = self._tool_registry.get_executor()

        if self._uses_async_entry_points or self.enable_tui:
            # Multi-entry-point mode or TUI mode: use AgentRuntime
            self._setup_agent_runtime(tools, tool_executor)
        else:
            # Single-entry-point mode: use legacy GraphExecutor
            self._setup_legacy_executor(tools, tool_executor)

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
            return "GOOGLE_API_KEY"
        elif model_lower.startswith("mistral/"):
            return "MISTRAL_API_KEY"
        elif model_lower.startswith("groq/"):
            return "GROQ_API_KEY"
        elif model_lower.startswith("ollama/"):
            return None  # Ollama doesn't need an API key (local)
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

    def _setup_legacy_executor(self, tools: list, tool_executor: Callable | None) -> None:
        """Set up legacy single-entry-point execution using GraphExecutor."""
        # Create runtime
        self._runtime = Runtime(storage_path=self._storage_path)

        # Create runtime logger
        log_store = RuntimeLogStore(base_path=self._storage_path / "runtime_logs")
        runtime_logger = RuntimeLogger(store=log_store, agent_id=self.graph.id)

        # Create executor
        self._executor = GraphExecutor(
            runtime=self._runtime,
            llm=self._llm,
            tools=tools,
            tool_executor=tool_executor,
            approval_callback=self._approval_callback,
            runtime_logger=runtime_logger,
            loop_config=self.graph.loop_config,
        )

    def _setup_agent_runtime(self, tools: list, tool_executor: Callable | None) -> None:
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

        # If TUI enabled but no entry points (single-entry agent), create default
        if not entry_points and self.enable_tui and self.graph.entry_node:
            logger.info("Creating default entry point for TUI")
            entry_points.append(
                EntryPointSpec(
                    id="default",
                    name="Default",
                    entry_node=self.graph.entry_node,
                    trigger_type="manual",
                    isolation_level="shared",
                )
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

        if self._uses_async_entry_points or self.enable_tui:
            # Multi-entry-point mode: use AgentRuntime
            return await self._run_with_agent_runtime(
                input_data=input_data or {},
                entry_point_id=entry_point_id,
            )
        else:
            # Legacy single-entry-point mode
            return await self._run_with_executor(
                input_data=input_data or {},
                session_state=session_state,
            )

    async def _run_with_executor(
        self,
        input_data: dict,
        session_state: dict | None = None,
    ) -> ExecutionResult:
        """Run using legacy GraphExecutor (single entry point)."""
        if self._executor is None:
            self._setup()

        return await self._executor.execute(
            graph=self.graph,
            goal=self.goal,
            input_data=input_data,
            session_state=session_state,
        )

    async def _run_with_agent_runtime(
        self,
        input_data: dict,
        entry_point_id: str | None = None,
    ) -> ExecutionResult:
        """Run using AgentRuntime (multi-entry-point)."""
        if self._agent_runtime is None:
            self._setup()

        # Start runtime if not running
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

        # Determine entry point
        if entry_point_id is None:
            # Use first entry point or "default" if no entry points defined
            entry_points = self._agent_runtime.get_entry_points()
            if entry_points:
                entry_point_id = entry_points[0].id
            else:
                entry_point_id = "default"

        # Trigger and wait for result
        result = await self._agent_runtime.trigger_and_wait(
            entry_point_id=entry_point_id,
            input_data=input_data,
        )

        # Return result or create error result
        if result is not None:
            return result
        else:
            return ExecutionResult(
                success=False,
                error="Execution timed out or failed to complete",
            )

    # === Multi-Entry-Point API (for agents with async_entry_points) ===

    async def start(self) -> None:
        """
        Start the agent runtime (for multi-entry-point agents).

        This starts all registered entry points and allows concurrent execution.
        For single-entry-point agents, this is a no-op.
        """
        if not self._uses_async_entry_points:
            return

        if self._agent_runtime is None:
            self._setup()

        await self._agent_runtime.start()

    async def stop(self) -> None:
        """
        Stop the agent runtime (for multi-entry-point agents).

        For single-entry-point agents, this is a no-op.
        """
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

        For multi-entry-point agents only. Returns execution ID for tracking.

        Args:
            entry_point_id: Which entry point to trigger
            input_data: Input data for the execution
            correlation_id: Optional ID to correlate related executions

        Returns:
            Execution ID for tracking

        Raises:
            RuntimeError: If agent doesn't use async entry points
        """
        if not self._uses_async_entry_points:
            raise RuntimeError(
                "trigger() is only available for multi-entry-point agents. "
                "Use run() for single-entry-point agents."
            )

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

        For multi-entry-point agents only.

        Returns:
            Dict with overall_progress, criteria_status, constraint_violations, etc.

        Raises:
            RuntimeError: If agent doesn't use async entry points
        """
        if not self._uses_async_entry_points:
            raise RuntimeError(
                "get_goal_progress() is only available for multi-entry-point agents."
            )

        if self._agent_runtime is None:
            self._setup()

        return await self._agent_runtime.get_goal_progress()

    def get_entry_points(self) -> list[EntryPointSpec]:
        """
        Get all registered entry points (for multi-entry-point agents).

        Returns:
            List of EntryPointSpec objects
        """
        if not self._uses_async_entry_points:
            return []

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
        # Uses CredentialStore (encrypted files + env var fallback)
        missing_credentials = []
        try:
            from aden_tools.credentials import CREDENTIAL_SPECS

            from framework.credentials import CredentialStore
            from framework.credentials.storage import (
                CompositeStorage,
                EncryptedFileStorage,
                EnvVarStorage,
            )

            # Build env mapping for credential lookup
            env_mapping = {
                (spec.credential_id or name): spec.env_var
                for name, spec in CREDENTIAL_SPECS.items()
            }

            # Only use EncryptedFileStorage if the encryption key is configured;
            # otherwise just check env vars (avoids generating a throwaway key)
            storages: list = [EnvVarStorage(env_mapping=env_mapping)]
            if os.environ.get("HIVE_CREDENTIAL_KEY"):
                storages.insert(0, EncryptedFileStorage())

            if len(storages) == 1:
                storage = storages[0]
            else:
                storage = CompositeStorage(
                    primary=storages[0],
                    fallbacks=storages[1:],
                )
            store = CredentialStore(storage=storage)

            # Build reverse mappings
            tool_to_cred: dict[str, str] = {}
            node_type_to_cred: dict[str, str] = {}
            for cred_name, spec in CREDENTIAL_SPECS.items():
                for tool_name in spec.tools:
                    tool_to_cred[tool_name] = cred_name
                for nt in spec.node_types:
                    node_type_to_cred[nt] = cred_name

            # Check tool credentials
            checked: set[str] = set()
            for tool_name in info.required_tools:
                cred_name = tool_to_cred.get(tool_name)
                if cred_name is None or cred_name in checked:
                    continue
                checked.add(cred_name)
                spec = CREDENTIAL_SPECS[cred_name]
                cred_id = spec.credential_id or cred_name
                if spec.required and not store.is_available(cred_id):
                    missing_credentials.append(spec.env_var)
                    affected_tools = [t for t in info.required_tools if t in spec.tools]
                    tools_str = ", ".join(affected_tools)
                    warning_msg = f"Missing {spec.env_var} for {tools_str}"
                    if spec.help_url:
                        warning_msg += f"\n  Get it at: {spec.help_url}"
                    warnings.append(warning_msg)

            # Check node type credentials (e.g., ANTHROPIC_API_KEY for LLM nodes)
            node_types = list({node.node_type for node in self.graph.nodes})
            for nt in node_types:
                cred_name = node_type_to_cred.get(nt)
                if cred_name is None or cred_name in checked:
                    continue
                checked.add(cred_name)
                spec = CREDENTIAL_SPECS[cred_name]
                cred_id = spec.credential_id or cred_name
                if spec.required and not store.is_available(cred_id):
                    missing_credentials.append(spec.env_var)
                    affected_types = [t for t in node_types if t in spec.node_types]
                    types_str = ", ".join(affected_types)
                    warning_msg = f"Missing {spec.env_var} for {types_str} nodes"
                    if spec.help_url:
                        warning_msg += f"\n  Get it at: {spec.help_url}"
                    warnings.append(warning_msg)
        except ImportError:
            # aden_tools not installed - fall back to direct check
            has_llm_nodes = any(
                node.node_type in ("llm_generate", "llm_tool_use") for node in self.graph.nodes
            )
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
            response = eval_llm.complete(
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

    def cleanup(self) -> None:
        """Clean up resources (synchronous)."""
        # Clean up MCP client connections
        self._tool_registry.cleanup()

        if self._temp_dir:
            self._temp_dir.cleanup()
            self._temp_dir = None

    async def cleanup_async(self) -> None:
        """Clean up resources (asynchronous - for multi-entry-point agents)."""
        # Stop agent runtime if running
        if self._agent_runtime is not None and self._agent_runtime.is_running:
            await self._agent_runtime.stop()

        # Run synchronous cleanup
        self.cleanup()

    async def __aenter__(self) -> "AgentRunner":
        """Context manager entry."""
        self._setup()
        # Start runtime for multi-entry-point agents
        if self._uses_async_entry_points and self._agent_runtime is not None:
            await self._agent_runtime.start()
        return self

    async def __aexit__(self, *args) -> None:
        """Context manager exit."""
        await self.cleanup_async()

    def __del__(self) -> None:
        """Destructor - cleanup temp dir."""
        self.cleanup()
