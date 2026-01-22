"""Agent Runner - loads and runs exported agents."""

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from framework.graph import Goal
from framework.graph.edge import GraphSpec, EdgeSpec, EdgeCondition
from framework.graph.node import NodeSpec
from framework.graph.executor import GraphExecutor, ExecutionResult
from framework.llm.provider import LLMProvider, Tool, ToolResult, ToolUse
from framework.llm.litellm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.core import Runtime


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

    # Build GraphSpec
    graph = GraphSpec(
        id=graph_data.get("id", "agent-graph"),
        goal_id=graph_data.get("goal_id", ""),
        version=graph_data.get("version", "1.0.0"),
        entry_node=graph_data.get("entry_node", ""),
        entry_points=graph_data.get("entry_points", {}),  # Support pause/resume architecture
        terminal_nodes=graph_data.get("terminal_nodes", []),
        pause_nodes=graph_data.get("pause_nodes", []),  # Support pause/resume architecture
        nodes=nodes,
        edges=edges,
        max_steps=graph_data.get("max_steps", 100),
        max_retries_per_node=graph_data.get("max_retries_per_node", 3),
        description=graph_data.get("description", ""),
    )

    # Build Goal
    from framework.graph.goal import SuccessCriterion, Constraint

    success_criteria = []
    for sc_data in goal_data.get("success_criteria", []):
        success_criteria.append(SuccessCriterion(
            id=sc_data["id"],
            description=sc_data["description"],
            metric=sc_data.get("metric", ""),
            target=sc_data.get("target", ""),
            weight=sc_data.get("weight", 1.0),
        ))

    constraints = []
    for c_data in goal_data.get("constraints", []):
        constraints.append(Constraint(
            id=c_data["id"],
            description=c_data["description"],
            constraint_type=c_data.get("constraint_type", "hard"),
            category=c_data.get("category", "safety"),
            check=c_data.get("check", ""),
        ))

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

    def __init__(
        self,
        agent_path: Path,
        graph: GraphSpec,
        goal: Goal,
        mock_mode: bool = False,
        storage_path: Path | None = None,
        model: str = "claude-haiku-4-5-20251001",
    ):
        """
        Initialize the runner (use AgentRunner.load() instead).

        Args:
            agent_path: Path to agent folder
            graph: Loaded GraphSpec object
            goal: Loaded Goal object
            mock_mode: If True, use mock LLM responses
            storage_path: Path for runtime storage (defaults to temp)
            model: Model to use - any LiteLLM-compatible model name
                   (e.g., "claude-sonnet-4-20250514", "gpt-4o-mini", "gemini/gemini-pro")
        """
        self.agent_path = agent_path
        self.graph = graph
        self.goal = goal
        self.mock_mode = mock_mode
        self.model = model

        # Set up storage
        if storage_path:
            self._storage_path = storage_path
            self._temp_dir = None
        else:
            # Use persistent storage in ~/.hive by default
            home = Path.home()
            default_storage = home / ".hive" / "storage" / agent_path.name
            default_storage.mkdir(parents=True, exist_ok=True)
            self._storage_path = default_storage
            self._temp_dir = None

        # Initialize components
        self._tool_registry = ToolRegistry()
        self._runtime: Runtime | None = None
        self._llm: LLMProvider | None = None
        self._executor: GraphExecutor | None = None
        self._approval_callback: Callable | None = None

        # Auto-discover tools from tools.py
        tools_path = agent_path / "tools.py"
        if tools_path.exists():
            self._tool_registry.discover_from_module(tools_path)

        # Auto-discover MCP servers from mcp_servers.json
        mcp_config_path = agent_path / "mcp_servers.json"
        if mcp_config_path.exists():
            self._load_mcp_servers_from_config(mcp_config_path)

    @classmethod
    def load(
        cls,
        agent_path: str | Path,
        mock_mode: bool = False,
        storage_path: Path | None = None,
        model: str = "claude-haiku-4-5-20251001",
    ) -> "AgentRunner":
        """
        Load an agent from an export folder.

        Args:
            agent_path: Path to agent folder (containing agent.json)
            mock_mode: If True, use mock LLM responses
            storage_path: Path for runtime storage (defaults to temp)
            model: Anthropic model to use

        Returns:
            AgentRunner instance ready to run
        """
        agent_path = Path(agent_path)

        # Load agent.json
        agent_json_path = agent_path / "agent.json"
        if not agent_json_path.exists():
            raise FileNotFoundError(f"agent.json not found in {agent_path}")

        with open(agent_json_path) as f:
            graph, goal = load_agent_export(f.read())

        return cls(
            agent_path=agent_path,
            graph=graph,
            goal=goal,
            mock_mode=mock_mode,
            storage_path=storage_path,
            model=model,
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
        """
        Load and register MCP servers from a configuration file.

        Args:
            config_path: Path to mcp_servers.json file
        """
        try:
            with open(config_path) as f:
                config = json.load(f)

            servers = config.get("servers", [])
            for server_config in servers:
                try:
                    self._tool_registry.register_mcp_server(server_config)
                except Exception as e:
                    print(f"Warning: Failed to register MCP server '{server_config.get('name', 'unknown')}': {e}")
        except Exception as e:
            print(f"Warning: Failed to load MCP servers config from {config_path}: {e}")

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
        # Create runtime
        self._runtime = Runtime(storage_path=self._storage_path)

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

        # Create LLM provider (if not mock mode and API key available)
        if not self.mock_mode and os.environ.get("ANTHROPIC_API_KEY"):
            from framework.llm.anthropic import AnthropicProvider

            self._llm = AnthropicProvider(model=self.model)

        # Create executor
        self._executor = GraphExecutor(
            runtime=self._runtime,
            llm=self._llm,
            tools=list(self._tool_registry.get_tools().values()),
            tool_executor=self._tool_registry.get_executor(),
            approval_callback=self._approval_callback,
        )

    async def run(self, input_data: dict | None = None, session_state: dict | None = None) -> ExecutionResult:
        """
        Execute the agent with given input data.

        Args:
            input_data: Input data for the agent (e.g., {"lead_id": "123"})
            session_state: Optional session state to resume from

        Returns:
            ExecutionResult with output, path, and metrics
        """
        if self._executor is None:
            self._setup()

        return await self._executor.execute(
            graph=self.graph,
            goal=self.goal,
            input_data=input_data or {},
            session_state=session_state,
        )

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
                {"id": sc.id, "description": sc.description, "metric": sc.metric, "target": sc.target}
                for sc in self.goal.success_criteria
            ],
            constraints=[
                {"id": c.id, "description": c.description, "type": c.constraint_type}
                for c in self.goal.constraints
            ],
            required_tools=sorted(required_tools),
            has_tools_module=(self.agent_path / "tools.py").exists(),
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
        missing_credentials = []
        try:
            from aden_tools.credentials import CredentialManager

            cred_manager = CredentialManager()

            # Check tool credentials (Tier 2)
            missing_creds = cred_manager.get_missing_for_tools(info.required_tools)
            for cred_name, spec in missing_creds:
                missing_credentials.append(spec.env_var)
                affected_tools = [t for t in info.required_tools if t in spec.tools]
                tools_str = ", ".join(affected_tools)
                warning_msg = f"Missing {spec.env_var} for {tools_str}"
                if spec.help_url:
                    warning_msg += f"\n  Get it at: {spec.help_url}"
                warnings.append(warning_msg)

            # Check node type credentials (e.g., ANTHROPIC_API_KEY for LLM nodes)
            node_types = list(set(node.node_type for node in self.graph.nodes))
            missing_node_creds = cred_manager.get_missing_for_node_types(node_types)
            for cred_name, spec in missing_node_creds:
                if spec.env_var not in missing_credentials:  # Avoid duplicates
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
                node.node_type in ("llm_generate", "llm_tool_use")
                for node in self.graph.nodes
            )
            if has_llm_nodes and not os.environ.get("ANTHROPIC_API_KEY"):
                warnings.append("Agent has LLM nodes but ANTHROPIC_API_KEY not set")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            missing_tools=missing_tools,
            missing_credentials=missing_credentials,
        )

    async def can_handle(self, request: dict, llm: LLMProvider | None = None) -> "CapabilityResponse":
        """
        Ask the agent if it can handle this request.

        Uses LLM to evaluate the request against the agent's goal and capabilities.

        Args:
            request: The request to evaluate
            llm: LLM provider to use (uses self._llm if not provided)

        Returns:
            CapabilityResponse with level, confidence, and reasoning
        """
        from framework.runner.protocol import CapabilityResponse, CapabilityLevel

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
            json_match = re.search(r'\{[^{}]*\}', response.content, re.DOTALL)
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
        except Exception as e:
            # Fall back to keyword matching on error
            pass

        return self._keyword_capability_check(request)

    def _keyword_capability_check(self, request: dict) -> "CapabilityResponse":
        """Simple keyword-based capability check (fallback when no LLM)."""
        from framework.runner.protocol import CapabilityResponse, CapabilityLevel

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
        from framework.runner.protocol import AgentMessage, MessageType

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
        """Clean up resources."""
        # Clean up MCP client connections
        self._tool_registry.cleanup()

        if self._temp_dir:
            self._temp_dir.cleanup()
            self._temp_dir = None

    async def __aenter__(self) -> "AgentRunner":
        """Context manager entry."""
        self._setup()
        return self

    async def __aexit__(self, *args) -> None:
        """Context manager exit."""
        self.cleanup()

    def __del__(self) -> None:
        """Destructor - cleanup temp dir."""
        self.cleanup()
