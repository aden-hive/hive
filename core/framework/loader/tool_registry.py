"""Tool discovery and registration for agent runner."""

import asyncio
import contextvars
import importlib.util
import inspect
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framework.llm.provider import Tool, ToolResult, ToolUse

logger = logging.getLogger(__name__)

_INPUT_LOG_MAX_LEN = 500

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
    CONTEXT_PARAMS = frozenset({"agent_id", "data_dir", "profile"})

    # Credential directory used for change detection
    _CREDENTIAL_DIR = Path("~/.hive/credentials/credentials").expanduser()

    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}
        self._mcp_clients: list[Any] = []  # List of MCPClient instances
        self._mcp_client_servers: dict[int, str] = {}  # client id -> server name
        self._mcp_managed_clients: set[int] = set()  # client ids acquired from the manager
        self._session_context: dict[str, Any] = {}  # Auto-injected context for tools
        self._provider_index: dict[str, set[str]] = {}  # provider -> tool names
        # MCP resync tracking
        self._mcp_config_path: Path | None = None  # Path used for initial load
        self._mcp_tool_names: set[str] = set()  # Tool names registered from MCP
        self._mcp_cred_snapshot: set[str] = set()  # Credential filenames at MCP load time
        self._mcp_aden_key_snapshot: str | None = None  # ADEN_API_KEY value at MCP load time
        self._mcp_server_tools: dict[str, set[str]] = {}  # server name -> tool names
        # Agent dir for re-loading registry MCP after credential resync.
        self._mcp_registry_agent_path: Path | None = None

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
            # MCP client returns dict with _images when image content is present
            if isinstance(result, dict) and "_images" in result:
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=result.get("_text", ""),
                    image_content=result["_images"],
                )
            return ToolResult(
                tool_use_id=tool_use_id,
                content=json.dumps(result) if not isinstance(result, str) else result,
                is_error=False,
            )

        registry_ref = self

        def executor(tool_use: ToolUse) -> ToolResult:
            # Check if credential files changed (lightweight dir listing).
            # If new OAuth tokens appeared, restarts MCP servers to pick them up.
            registry_ref.resync_mcp_servers_if_needed()

            if tool_use.name not in registry_ref._tools:
                return ToolResult(
                    tool_use_id=tool_use.id,
                    content=json.dumps({"error": f"Unknown tool: {tool_use.name}"}),
                    is_error=True,
                )

            registered = registry_ref._tools[tool_use.name]
            try:
                result = registered.executor(tool_use.input)

                # Async tool: wrap the awaitable so the caller can await it
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):

                    async def _await_and_wrap():
                        try:
                            r = await result
                            return _wrap_result(tool_use.id, r)
                        except Exception as exc:
                            inputs_str = json.dumps(tool_use.input, default=str)
                            if len(inputs_str) > _INPUT_LOG_MAX_LEN:
                                inputs_str = inputs_str[:_INPUT_LOG_MAX_LEN] + "...(truncated)"
                            logger.error(
                                "Async tool '%s' failed (tool_use_id=%s): %s\nInputs: %s",
                                tool_use.name,
                                tool_use.id,
                                exc,
                                inputs_str,
                                exc_info=True,
                            )
                            return ToolResult(
                                tool_use_id=tool_use.id,
                                content=json.dumps({"error": str(exc)}),
                                is_error=True,
                            )

                    return _await_and_wrap()

                return _wrap_result(tool_use.id, result)
            except Exception as e:
                inputs_str = json.dumps(tool_use.input, default=str)
                if len(inputs_str) > _INPUT_LOG_MAX_LEN:
                    inputs_str = inputs_str[:_INPUT_LOG_MAX_LEN] + "...(truncated)"
                logger.error(
                    "Tool '%s' execution failed for tool_use_id=%s: %s\nInputs: %s",
                    tool_use.name,
                    tool_use.id,
                    e,
                    inputs_str,
                    exc_info=True,
                )
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

    def get_server_tool_names(self, server_name: str) -> set[str]:
        """Return tool names registered from a specific MCP server."""
        return set(self._mcp_server_tools.get(server_name, set()))

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

    @staticmethod
    def resolve_mcp_stdio_config(server_config: dict[str, Any], base_dir: Path) -> dict[str, Any]:
        """Resolve cwd and script paths for MCP stdio config (Windows compatibility).

        Use this when building MCPServerConfig from a config file (e.g. in
        list_agent_tools, discover_mcp_tools) so hive-tools and other servers
        work on Windows. Call with base_dir = directory containing the config.
        """
        registry = ToolRegistry()
        return registry._resolve_mcp_server_config(server_config, base_dir)

    def _resolve_mcp_server_config(
        self, server_config: dict[str, Any], base_dir: Path
    ) -> dict[str, Any]:
        """Resolve cwd and script paths for MCP stdio servers (Windows compatibility).

        On Windows, passing cwd to subprocess can cause WinError 267. We use cwd=None
        and absolute script paths when the server runs a .py script from the tools dir.
        If the resolved cwd doesn't exist (e.g. config from ~/.hive/agents/), fall back
        to Path.cwd() / "tools".
        """
        config = dict(server_config)
        if config.get("transport") != "stdio":
            return config

        cwd = config.get("cwd")
        args = list(config.get("args", []))
        if not cwd and not args:
            return config

        # Resolve cwd relative to base_dir
        resolved_cwd: Path | None = None
        if cwd:
            if Path(cwd).is_absolute():
                resolved_cwd = Path(cwd)
            else:
                resolved_cwd = (base_dir / cwd).resolve()

        # Find .py script in args (e.g. coder_tools_server.py, files_server.py)
        script_name = None
        for i, arg in enumerate(args):
            if isinstance(arg, str) and arg.endswith(".py"):
                script_name = arg
                script_idx = i
                break

        if resolved_cwd is None:
            return config

        # If resolved cwd doesn't exist or (when we have a script) doesn't contain it,
        # try fallback
        tools_fallback = Path.cwd() / "tools"
        need_fallback = not resolved_cwd.is_dir()
        if script_name and not need_fallback:
            need_fallback = not (resolved_cwd / script_name).exists()
        if need_fallback:
            fallback_ok = tools_fallback.is_dir()
            if script_name:
                fallback_ok = fallback_ok and (tools_fallback / script_name).exists()
            else:
                # No script (e.g. GCU); just need tools dir to exist
                pass
            if fallback_ok:
                resolved_cwd = tools_fallback
                logger.debug(
                    "MCP server '%s': using fallback tools dir %s",
                    config.get("name", "?"),
                    resolved_cwd,
                )
            else:
                config["cwd"] = str(resolved_cwd)
                return config

        if not script_name:
            # No .py script (e.g. GCU uses -m gcu.server); just set cwd
            config["cwd"] = str(resolved_cwd)
            return config

        # For coder_tools_server, inject --project-root so writes go to the expected workspace
        if script_name and "coder_tools" in script_name:
            project_root = str(resolved_cwd.parent.resolve())
            args = list(args)
            if "--project-root" not in args:
                args.extend(["--project-root", project_root])
            config["args"] = args

        if os.name == "nt":
            # Windows: cwd=None avoids WinError 267; use absolute script path
            config["cwd"] = None
            abs_script = str((resolved_cwd / script_name).resolve())
            args = list(config["args"])
            args[script_idx] = abs_script
            config["args"] = args
        else:
            config["cwd"] = str(resolved_cwd)
        return config

    def load_mcp_config(self, config_path: Path) -> None:
        """
        Load and register MCP servers from a config file.

        Resolves relative ``cwd`` paths against the config file's parent
        directory so callers never need to handle path resolution themselves.

        Args:
            config_path: Path to an ``mcp_servers.json`` file.
        """
        # Remember config path for potential resync later
        self._mcp_config_path = Path(config_path)

        try:
            with open(config_path, encoding="utf-8") as f:
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

        resolved_server_list = [
            self._resolve_mcp_server_config(server_config, base_dir)
            for server_config in server_list
        ]
        # Ordered first-wins for duplicate tool names across servers; keep tools.py tools.
        self.load_registry_servers(
            resolved_server_list,
            log_summary=False,
            preserve_existing_tools=True,
            log_collisions=False,
        )

        # Snapshot credential files and ADEN_API_KEY so we can detect mid-session changes
        self._mcp_cred_snapshot = self._snapshot_credentials()
        self._mcp_aden_key_snapshot = os.environ.get("ADEN_API_KEY")

    def _register_mcp_server_with_retry(
        self,
        server_config: dict[str, Any],
        *,
        preserve_existing_tools: bool = True,
        tool_cap: int | None = None,
        log_collisions: bool = False,
    ) -> tuple[bool, int, str | None]:
        """Register a single MCP server with one retry for transient failures."""
        name = server_config.get("name", "unknown")
        last_error: str | None = None

        for attempt in range(2):
            try:
                count = self.register_mcp_server(
                    server_config,
                    preserve_existing_tools=preserve_existing_tools,
                    tool_cap=tool_cap,
                    log_collisions=log_collisions,
                )
                if count > 0:
                    return True, count, None
                last_error = "registered 0 tools"
            except Exception as exc:
                last_error = str(exc)

            if attempt == 0:
                logger.warning(
                    "MCP server '%s' failed to register, retrying in 2s: %s",
                    name,
                    last_error,
                )
                import time

                time.sleep(2)
            else:
                logger.warning("MCP server '%s' failed after retry: %s", name, last_error)

        return False, 0, last_error

    def load_registry_servers(
        self,
        server_list: list[dict[str, Any]],
        *,
        log_summary: bool = True,
        preserve_existing_tools: bool = True,
        max_tools: int | None = None,
        log_collisions: bool = False,
    ) -> list[dict[str, Any]]:
        """Register MCP servers from a resolved config list (registry and/or static).

        ``preserve_existing_tools`` enforces first-wins tool names (FR-100): later
        servers skip names already taken— including tools from ``mcp_servers.json``
        or ``tools.py`` when those were loaded first.

        ``max_tools`` caps how many *new* tool names are registered across this batch
        (collisions do not consume the cap). When ``log_collisions`` is True, skipped
        duplicate names emit a warning (FR-101).
        """
        results: list[dict[str, Any]] = []
        tools_added_batch = 0

        for server_config in server_list:
            remaining: int | None = None
            if max_tools is not None:
                remaining = max_tools - tools_added_batch
                if remaining <= 0:
                    break

            name = server_config.get("name", "unknown")
            success, tools_loaded, error = self._register_mcp_server_with_retry(
                server_config,
                preserve_existing_tools=preserve_existing_tools,
                tool_cap=remaining,
                log_collisions=log_collisions,
            )
            tools_added_batch += tools_loaded
            result = {
                "server": name,
                "status": "loaded" if success else "skipped",
                "tools_loaded": tools_loaded,
                "skipped_reason": None if success else (error or "unknown error"),
            }
            results.append(result)

            if log_summary:
                logger.info(
                    "MCP registry server resolution",
                    extra={
                        "event": "mcp_registry_server_resolution",
                        "server": result["server"],
                        "status": result["status"],
                        "tools_loaded": result["tools_loaded"],
                        "skipped_reason": result["skipped_reason"],
                    },
                )

        return results

    def register_mcp_server(
        self,
        server_config: dict[str, Any],
        use_connection_manager: bool = True,
        *,
        preserve_existing_tools: bool = True,
        tool_cap: int | None = None,
        log_collisions: bool = False,
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
            use_connection_manager: When True, reuse a shared client keyed by server name
            preserve_existing_tools: If True, do not replace tools already in the registry.
            tool_cap: Max tools to newly register from this server (None = unlimited).
            log_collisions: If True, log when this server skips a tool name already taken.

        Returns:
            Number of tools registered from this server
        """
        try:
            from framework.loader.mcp_client import MCPClient, MCPServerConfig
            from framework.loader.mcp_connection_manager import MCPConnectionManager

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
                socket_path=server_config.get("socket_path"),
                description=server_config.get("description", ""),
            )

            # Create and connect client
            if use_connection_manager:
                client = MCPConnectionManager.get_instance().acquire(config)
            else:
                client = MCPClient(config)
                client.connect()

            # Store client for cleanup
            self._mcp_clients.append(client)
            client_id = id(client)
            self._mcp_client_servers[client_id] = config.name
            if use_connection_manager:
                self._mcp_managed_clients.add(client_id)

            # Register each tool
            server_name = server_config["name"]
            if server_name not in self._mcp_server_tools:
                self._mcp_server_tools[server_name] = set()
            count = 0
            for mcp_tool in client.list_tools():
                if tool_cap is not None and count >= tool_cap:
                    break

                if preserve_existing_tools and mcp_tool.name in self._tools:
                    if log_collisions:
                        origin_server = (
                            self._find_mcp_origin_server_for_tool(mcp_tool.name) or "<existing>"
                        )
                        logger.warning(
                            "MCP tool '%s' from '%s' shadowed by '%s' (loaded first)",
                            mcp_tool.name,
                            server_name,
                            origin_server,
                        )
                    # Skip registration; do not update MCP tool bookkeeping for this server.
                    continue

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
                            # Strip context params from LLM inputs — the framework
                            # values are authoritative (prevents the LLM from passing
                            # e.g. data_dir="/data" and overriding the real path).
                            clean_inputs = {
                                k: v
                                for k, v in inputs.items()
                                if k not in registry_ref.CONTEXT_PARAMS
                            }
                            merged_inputs = {**clean_inputs, **filtered_context}
                            result = client_ref.call_tool(tool_name, merged_inputs)
                            # MCP client already extracts content (returns str
                            # or {"_text": ..., "_images": ...} for image results).
                            # Handle legacy list format from HTTP transport.
                            if isinstance(result, list) and len(result) > 0:
                                if isinstance(result[0], dict) and "text" in result[0]:
                                    return result[0]["text"]
                                return result[0]
                            return result
                        except Exception as e:
                            inputs_str = json.dumps(inputs, default=str)
                            if len(inputs_str) > _INPUT_LOG_MAX_LEN:
                                inputs_str = inputs_str[:_INPUT_LOG_MAX_LEN] + "...(truncated)"
                            logger.error(
                                "MCP tool '%s' execution failed: %s\nInputs: %s",
                                tool_name,
                                e,
                                inputs_str,
                                exc_info=True,
                            )
                            return {"error": str(e)}

                    return executor

                tool_params = set(mcp_tool.input_schema.get("properties", {}).keys())
                self.register(
                    mcp_tool.name,
                    tool,
                    make_mcp_executor(client, mcp_tool.name, self, tool_params),
                )
                self._mcp_tool_names.add(mcp_tool.name)
                self._mcp_server_tools[server_name].add(mcp_tool.name)
                count += 1

            logger.info(
                "MCP Registry Load",
                extra={
                    "server": config.name,
                    "status": "success",
                    "tools_loaded": count,
                    "skipped_reason": None,
                },
            )
            return count

        except Exception as e:
            logger.error(
                "MCP Registry Load",
                extra={
                    "server": server_config.get("name", "unknown"),
                    "status": "failed",
                    "tools_loaded": 0,
                    "skipped_reason": str(e),
                },
            )
            if "Connection closed" in str(e) and os.name == "nt":
                logger.debug(
                    "On Windows, check that the MCP subprocess starts (e.g. uv in PATH, "
                    "script path correct). Worker config uses base_dir = mcp_servers.json parent."
                )
            return 0

    def _find_mcp_origin_server_for_tool(self, tool_name: str) -> str | None:
        for server_name, tool_names in self._mcp_server_tools.items():
            if tool_name in tool_names:
                return server_name
        return None

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

    # ------------------------------------------------------------------
    # MCP credential resync
    # ------------------------------------------------------------------

    def set_mcp_registry_agent_path(self, agent_path: Path | None) -> None:
        """Remember agent dir so registry MCP servers reload after credential resync."""
        self._mcp_registry_agent_path = None if agent_path is None else Path(agent_path)

    def reload_registry_mcp_servers_after_resync(self) -> None:
        """Re-run ``mcp_registry.json`` resolution and register servers (post-resync)."""
        if self._mcp_registry_agent_path is None:
            return
        from framework.loader.mcp_registry import MCPRegistry

        try:
            reg = MCPRegistry()
            reg.initialize()
            configs, selection_max_tools = reg.load_agent_selection(self._mcp_registry_agent_path)
        except Exception as exc:
            logger.warning(
                "Failed to reload MCP registry servers after resync for '%s': %s",
                self._mcp_registry_agent_path.name,
                exc,
            )
            return
        if not configs:
            return
        self.load_registry_servers(
            configs,
            log_summary=True,
            preserve_existing_tools=True,
            log_collisions=True,
            max_tools=selection_max_tools,
        )

    def _snapshot_credentials(self) -> set[str]:
        """Return the set of credential filenames currently on disk."""
        try:
            return set(self._CREDENTIAL_DIR.iterdir()) if self._CREDENTIAL_DIR.is_dir() else set()
        except OSError:
            return set()

    def resync_mcp_servers_if_needed(self) -> bool:
        """Restart MCP servers if credential files changed since last load.

        Compares the current credential directory listing against the snapshot
        taken when MCP servers were first loaded.  If new files appeared (e.g.
        user connected an OAuth account mid-session), disconnects all MCP
        clients and re-loads them so the new subprocess picks up the fresh
        credentials.

        Note: Individual credential TTL/refresh is handled by the MCP server
        process internally -- it resolves tokens from the credential store
        on every tool call, not at startup. This method only handles the case
        where entirely new credential files appear.

        Returns True if a resync was performed, False otherwise.
        """
        if not self._mcp_clients or self._mcp_config_path is None:
            return False

        current = self._snapshot_credentials()
        current_aden_key = os.environ.get("ADEN_API_KEY")
        files_changed = current != self._mcp_cred_snapshot
        aden_key_changed = current_aden_key != self._mcp_aden_key_snapshot

        if not files_changed and not aden_key_changed:
            return False

        reason = (
            "Credential files and ADEN_API_KEY changed"
            if files_changed and aden_key_changed
            else "ADEN_API_KEY changed"
            if aden_key_changed
            else "Credential files changed"
        )
        logger.info("%s — resyncing MCP servers", reason)

        # 1. Disconnect existing MCP clients
        self._cleanup_mcp_clients("during resync")

        # 2. Remove MCP-registered tools
        for name in self._mcp_tool_names:
            self._tools.pop(name, None)
        self._mcp_tool_names.clear()
        self._mcp_server_tools.clear()

        # 3. Re-load MCP servers (spawns fresh subprocesses with new credentials)
        self.load_mcp_config(self._mcp_config_path)
        if self._mcp_registry_agent_path is not None:
            self.reload_registry_mcp_servers_after_resync()

        logger.info("MCP server resync complete")
        return True

    def cleanup(self) -> None:
        """Clean up all MCP client connections."""
        self._cleanup_mcp_clients()

    def _cleanup_mcp_clients(self, context: str = "") -> None:
        """Disconnect or release all tracked MCP clients for this registry."""
        if context:
            context = f" {context}"

        for client in self._mcp_clients:
            client_id = id(client)
            server_name = self._mcp_client_servers.get(client_id, client.config.name)
            try:
                if client_id in self._mcp_managed_clients:
                    from framework.loader.mcp_connection_manager import MCPConnectionManager

                    MCPConnectionManager.get_instance().release(server_name)
                else:
                    client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting MCP client{context}: {e}")
        self._mcp_clients.clear()
        self._mcp_client_servers.clear()
        self._mcp_managed_clients.clear()

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
