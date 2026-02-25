"""Tool discovery and registration for agent runner."""

import asyncio
import contextvars
import importlib.util
import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framework.llm.provider import Tool, ToolResult, ToolUse

logger = logging.getLogger(__name__)

# Per-execution context overrides.  Each asyncio task (and thus each
# concurrent graph execution) gets its own copy, so there are no races
# when multiple ExecutionStreams run in parallel.
_execution_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "_execution_context", default=None
)


@dataclass
class RegisteredTool:
    """A tool with its executor function."""

    tool: Tool
    executor: Callable[[dict], Any]


class ToolRegistry:
    """
    Manages tool discovery and registration.

    Tool Discovery Order:
    1. Built-in tools (if any)
    2. tools.py in agent folder
    3. MCP servers
    4. Manually registered tools
    """

    # Framework-internal context keys injected into tool calls.
    # Stripped from LLM-facing schemas (the LLM doesn't know these values)
    # and auto-injected at call time for tools that accept them.
    CONTEXT_PARAMS = frozenset({"workspace_id", "agent_id", "session_id", "data_dir"})

    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}
        self._mcp_clients: list[Any] = []  # List of MCPClient instances
        self._session_context: dict[str, Any] = {}  # Auto-injected context for tools
        self._provider_index: dict[str, set[str]] = {}  # provider -> tool names

    def register(
        self,
        name: str,
        tool: Tool,
        executor: Callable[[dict], Any],
    ) -> None:
        """
        Register a single tool with its executor.

        Args:
            name: Tool name (must match tool.name)
            tool: Tool definition
            executor: Function that takes tool input dict and returns result
        """
        self._tools[name] = RegisteredTool(tool=tool, executor=executor)

    def register_function(
        self,
        func: Callable,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """
        Register a function as a tool, auto-generating the Tool definition.

        Args:
            func: Function to register
            name: Tool name (defaults to function name)
            description: Tool description (defaults to docstring)
        """
        tool_name = name or func.__name__
        tool_desc = description or func.__doc__ or f"Execute {tool_name}"

        # Generate parameters from function signature
        sig = inspect.signature(func)
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            param_type = "string"  # Default
            if param.annotation != inspect.Parameter.empty:
                if param.annotation is int:
                    param_type = "integer"
                elif param.annotation is float:
                    param_type = "number"
                elif param.annotation is bool:
                    param_type = "boolean"
                elif param.annotation is dict:
                    param_type = "object"
                elif param.annotation is list:
                    param_type = "array"

            properties[param_name] = {"type": param_type}

            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        tool = Tool(
            name=tool_name,
            description=tool_desc,
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
        )

        def executor(inputs: dict) -> Any:
            return func(**inputs)

        self.register(tool_name, tool, executor)

    def discover_from_module(self, module_path: Path) -> int:
        """
        Load tools from a Python module file.

        Looks for:
        - TOOLS: dict[str, Tool] - tool definitions
        - tool_executor(tool_use: ToolUse) -> ToolResult - unified executor
        - Functions decorated with @tool

        Args:
            module_path: Path to tools.py file

        Returns:
            Number of tools discovered
        """
        if not module_path.exists():
            return 0

        # Load the module dynamically
        spec = importlib.util.spec_from_file_location("agent_tools", module_path)
        if spec is None or spec.loader is None:
            return 0

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        count = 0

        # Check for TOOLS dict
        if hasattr(module, "TOOLS"):
            tools_dict = module.TOOLS
            executor_func = getattr(module, "tool_executor", None)

            for name, tool in tools_dict.items():
                if executor_func:
                    # Use unified executor
                    def make_executor(tool_name: str):
                        def executor(inputs: dict) -> Any:
                            tool_use = ToolUse(
                                id=f"call_{tool_name}",
                                name=tool_name,
                                input=inputs,
                            )
                            result = executor_func(tool_use)
                            if isinstance(result, ToolResult):
                                # ToolResult.content is expected to be JSON, but tools may
                                # sometimes return invalid JSON. Guard against crashes here
                                # and surface a structured error instead.
                                if not result.content:
                                    return {}
                                try:
                                    return json.loads(result.content)
                                except json.JSONDecodeError as e:
                                    logger.warning(
                                        "Tool '%s' returned invalid JSON: %s",
                                        tool_name,
                                        str(e),
                                    )
                                    return {
                                        "error": (
                                            f"Invalid JSON response from tool '{tool_name}': "
                                            f"{str(e)}"
                                        ),
                                        "raw_content": result.content,
                                    }
                            return result

                        return executor

                    self.register(name, tool, make_executor(name))
                else:
                    # Register tool without executor (will use mock)
                    self.register(name, tool, lambda inputs: {"mock": True, "inputs": inputs})
                count += 1

        # Check for @tool decorated functions
        for name in dir(module):
            obj = getattr(module, name)
            if callable(obj) and hasattr(obj, "_tool_metadata"):
                metadata = obj._tool_metadata
                self.register_function(
                    obj,
                    name=metadata.get("name", name),
                    description=metadata.get("description"),
                )
                count += 1

        return count

    def get_tools(self) -> dict[str, Tool]:
        """Get all registered Tool objects."""
        return {name: rt.tool for name, rt in self._tools.items()}

    def get_executor(self) -> Callable[[ToolUse], ToolResult]:
        """
        Get unified tool executor function.

        Returns a function that dispatches to the appropriate tool executor.
        Handles both sync and async tool implementations — async results are
        wrapped so that ``EventLoopNode._execute_tool`` can await them.
        """

        def _wrap_result(tool_use_id: str, result: Any) -> ToolResult:
            if isinstance(result, ToolResult):
                return result
            return ToolResult(
                tool_use_id=tool_use_id,
                content=json.dumps(result) if not isinstance(result, str) else result,
                is_error=False,
            )

        def executor(tool_use: ToolUse) -> ToolResult:
            if tool_use.name not in self._tools:
                return ToolResult(
                    tool_use_id=tool_use.id,
                    content=json.dumps({"error": f"Unknown tool: {tool_use.name}"}),
                    is_error=True,
                )

            registered = self._tools[tool_use.name]
            try:
                result = registered.executor(tool_use.input)

                # Async tool: wrap the awaitable so the caller can await it
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):

                    async def _await_and_wrap():
                        try:
                            r = await result
                            return _wrap_result(tool_use.id, r)
                        except Exception as exc:
                            return ToolResult(
                                tool_use_id=tool_use.id,
                                content=json.dumps({"error": str(exc)}),
                                is_error=True,
                            )

                    return _await_and_wrap()

                return _wrap_result(tool_use.id, result)
            except Exception as e:
                return ToolResult(
                    tool_use_id=tool_use.id,
                    content=json.dumps({"error": str(e)}),
                    is_error=True,
                )

        return executor

    def get_registered_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def set_session_context(self, **context) -> None:
        """
        Set session context to auto-inject into tool calls.

        Args:
            **context: Key-value pairs to inject (e.g., workspace_id, agent_id, session_id)
        """
        self._session_context.update(context)

    @staticmethod
    def set_execution_context(**context) -> contextvars.Token:
        """Set per-execution context overrides (concurrency-safe via contextvars).

        Values set here take precedence over session context.  Each asyncio
        task gets its own copy, so concurrent executions don't interfere.

        Returns a token that must be passed to :meth:`reset_execution_context`
        to restore the previous state.
        """
        current = _execution_context.get() or {}
        return _execution_context.set({**current, **context})

    @staticmethod
    def reset_execution_context(token: contextvars.Token) -> None:
        """Restore execution context to its previous state."""
        _execution_context.reset(token)

    def load_mcp_config(self, config_path: Path) -> None:
        """
        Load and register MCP servers from a config file.

        Resolves relative ``cwd`` paths against the config file's parent
        directory so callers never need to handle path resolution themselves.

        Args:
            config_path: Path to an ``mcp_servers.json`` file.
        """
        try:
            with open(config_path) as f:
                config = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load MCP config from {config_path}: {e}")
            return

        base_dir = config_path.parent

        # Support both formats:
        #   {"servers": [{"name": "x", ...}]}        (list format)
        #   {"server-name": {"transport": ...}, ...}  (dict format)
        server_list = config.get("servers", [])
        if not server_list and "servers" not in config:
            # Treat top-level keys as server names
            server_list = [{"name": name, **cfg} for name, cfg in config.items()]

        for server_config in server_list:
            cwd = server_config.get("cwd")
            if cwd and not Path(cwd).is_absolute():
                server_config["cwd"] = str((base_dir / cwd).resolve())
            try:
                self.register_mcp_server(server_config)
            except Exception as e:
                name = server_config.get("name", "unknown")
                logger.warning(f"Failed to register MCP server '{name}': {e}")

    def register_mcp_server(
        self,
        server_config: dict[str, Any],
    ) -> int:
        """
        Register an MCP server and discover its tools.

        Args:
            server_config: MCP server configuration dict with keys:
                - name: Server name (required)
                - transport: "stdio" or "http" (required)
                - command: Command to run (for stdio)
                - args: Command arguments (for stdio)
                - env: Environment variables (for stdio)
                - cwd: Working directory (for stdio)
                - url: Server URL (for http)
                - headers: HTTP headers (for http)
                - description: Server description (optional)

        Returns:
            Number of tools registered from this server
        """
        try:
            from framework.runner.mcp_client import MCPClient, MCPServerConfig

            # Build config object
            config = MCPServerConfig(
                name=server_config["name"],
                transport=server_config["transport"],
                command=server_config.get("command"),
                args=server_config.get("args", []),
                env=server_config.get("env", {}),
                cwd=server_config.get("cwd"),
                url=server_config.get("url"),
                headers=server_config.get("headers", {}),
                description=server_config.get("description", ""),
            )

            # Create and connect client
            client = MCPClient(config)
            client.connect()

            # Store client for cleanup
            self._mcp_clients.append(client)

            # Register each tool
            count = 0
            for mcp_tool in client.list_tools():
                # Convert MCP tool to framework Tool (strips context params from LLM schema)
                tool = self._convert_mcp_tool_to_framework_tool(mcp_tool)

                # Create executor that calls the MCP server
                def make_mcp_executor(
                    client_ref: MCPClient,
                    tool_name: str,
                    registry_ref,
                    tool_params: set[str],
                ):
                    def executor(inputs: dict) -> Any:
                        try:
                            # Build base context: session < execution (execution wins)
                            base_context = dict(registry_ref._session_context)
                            exec_ctx = _execution_context.get()
                            if exec_ctx:
                                base_context.update(exec_ctx)

                            # Only inject context params the tool accepts
                            filtered_context = {
                                k: v for k, v in base_context.items() if k in tool_params
                            }
                            merged_inputs = {**filtered_context, **inputs}
                            result = client_ref.call_tool(tool_name, merged_inputs)
                            # MCP tools return content array, extract the result
                            if isinstance(result, list) and len(result) > 0:
                                if isinstance(result[0], dict) and "text" in result[0]:
                                    return result[0]["text"]
                                return result[0]
                            return result
                        except Exception as e:
                            logger.error(f"MCP tool '{tool_name}' execution failed: {e}")
                            return {"error": str(e)}

                    return executor

                tool_params = set(mcp_tool.input_schema.get("properties", {}).keys())
                self.register(
                    mcp_tool.name,
                    tool,
                    make_mcp_executor(client, mcp_tool.name, self, tool_params),
                )
                count += 1

            logger.info(f"Registered {count} tools from MCP server '{config.name}'")
            return count

        except Exception as e:
            logger.error(f"Failed to register MCP server: {e}")
            return 0

    def _convert_mcp_tool_to_framework_tool(self, mcp_tool: Any) -> Tool:
        """
        Convert an MCP tool to a framework Tool.

        Args:
            mcp_tool: MCPTool object

        Returns:
            Framework Tool object
        """
        # Extract parameters from MCP input schema
        input_schema = mcp_tool.input_schema
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])

        # Strip framework-internal context params from LLM-facing schema.
        # The LLM can't know these values; they're auto-injected at call time.
        properties = {k: v for k, v in properties.items() if k not in self.CONTEXT_PARAMS}
        required = [r for r in required if r not in self.CONTEXT_PARAMS]

        # Convert to framework Tool format
        tool = Tool(
            name=mcp_tool.name,
            description=mcp_tool.description,
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
        )

        return tool

    # ------------------------------------------------------------------
    # Provider-based tool filtering
    # ------------------------------------------------------------------

    def build_provider_index(self) -> None:
        """Build provider -> tool-name mapping from CREDENTIAL_SPECS.

        Populates ``_provider_index`` so :meth:`get_by_provider` works.
        Safe to call even if ``aden_tools`` is not installed (silently no-ops).
        """
        try:
            from aden_tools.credentials import CREDENTIAL_SPECS
        except ImportError:
            logger.debug("aden_tools not available, skipping provider index")
            return

        self._provider_index.clear()
        for spec in CREDENTIAL_SPECS.values():
            provider = spec.aden_provider_name
            if provider:
                if provider not in self._provider_index:
                    self._provider_index[provider] = set()
                self._provider_index[provider].update(spec.tools)

    def get_by_provider(self, provider: str) -> dict[str, Tool]:
        """Return registered tools that belong to *provider*.

        Lazily builds the provider index on first call.
        """
        if not self._provider_index:
            self.build_provider_index()
        tool_names = self._provider_index.get(provider, set())
        return {name: rt.tool for name, rt in self._tools.items() if name in tool_names}

    def get_tool_names_by_provider(self, provider: str) -> list[str]:
        """Return sorted registered tool names for *provider*."""
        if not self._provider_index:
            self.build_provider_index()
        tool_names = self._provider_index.get(provider, set())
        return sorted(name for name in self._tools if name in tool_names)

    def get_all_provider_tool_names(self) -> list[str]:
        """Return sorted names of all registered tools that belong to any provider."""
        if not self._provider_index:
            self.build_provider_index()
        all_names: set[str] = set()
        for names in self._provider_index.values():
            all_names.update(names)
        return sorted(name for name in self._tools if name in all_names)

    def cleanup(self) -> None:
        """Clean up all MCP client connections."""
        for client in self._mcp_clients:
            try:
                client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting MCP client: {e}")
        self._mcp_clients.clear()

    def __del__(self):
        """Destructor to ensure cleanup."""
        self.cleanup()


def tool(
    description: str | None = None,
    name: str | None = None,
) -> Callable:
    """
    Decorator to mark a function as a tool.

    Usage:
        @tool(description="Fetch lead from GTM table")
        def gtm_fetch_lead(lead_id: str) -> dict:
            return {"lead_data": {...}}
    """

    def decorator(func: Callable) -> Callable:
        func._tool_metadata = {
            "name": name or func.__name__,
            "description": description or func.__doc__,
        }
        return func

    return decorator
