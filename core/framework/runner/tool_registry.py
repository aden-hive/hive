"""Tool discovery and registration for agent runner."""

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

    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}
        self._mcp_clients: list[Any] = []  # List of MCPClient instances
        self._session_context: dict[str, Any] = {}  # Auto-injected context for tools

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

    def discover_from_module(self, module_path: Path) -> dict[str, Any]:
        """
        Load tools from a Python module file.

        Looks for:
        - TOOLS: dict[str, Tool] - tool definitions
        - tool_executor(tool_use: ToolUse) -> ToolResult - unified executor
        - Functions decorated with @tool

        Args:
            module_path: Path to tools.py file

        Returns:
            dict: {
                'success': bool,
                'tools_registered': int,
                'module': str,
                'errors': list[str] (if any)
            }
        """
        result = {
            'success': False,
            'tools_registered': 0,
            'module': str(module_path),
            'errors': []
        }
        
        if not module_path.exists():
            error_msg = f"Module file not found: {module_path}"
            logger.error(error_msg)
            result['errors'].append(error_msg)
            return result

        try:
            # Load the module dynamically
            spec = importlib.util.spec_from_file_location("agent_tools", module_path)
            if spec is None or spec.loader is None:
                error_msg = f"Failed to create module spec for {module_path}"
                logger.error(error_msg)
                result['errors'].append(error_msg)
                return result

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            logger.info(f"Discovering tools in module: {module_path}")

            count = 0
            errors = []

            # Check for TOOLS dict
            if hasattr(module, "TOOLS"):
                try:
                    tools_dict = module.TOOLS
                    executor_func = getattr(module, "tool_executor", None)
                    
                    if not isinstance(tools_dict, dict):
                        error_msg = "TOOLS must be a dictionary"
                        logger.error(error_msg)
                        errors.append(error_msg)
                    else:
                        logger.info(f"Found TOOLS dict with {len(tools_dict)} tools")
                        
                        for name, tool in tools_dict.items():
                            try:
                                if not isinstance(name, str):
                                    error_msg = f"Tool name must be a string, got {type(name).__name__}"
                                    errors.append(error_msg)
                                    continue
                                    
                                if not isinstance(tool, Tool):
                                    error_msg = f"Tool {name} is not an instance of Tool, got {type(tool).__name__}"
                                    errors.append(error_msg)
                                    continue
                                    
                                if executor_func:
                                    # Use unified executor
                                    def make_executor(tool_name: str):
                                        def executor(inputs: dict) -> Any:
                                            try:
                                                tool_use = ToolUse(
                                                    id=f"call_{tool_name}",
                                                    name=tool_name,
                                                    input=inputs,
                                                )
                                                logger.debug(f"Executing tool '{tool_name}' with inputs: {inputs}")
                                                result = executor_func(tool_use)
                                                
                                                if isinstance(result, ToolResult):
                                                    return json.loads(result.content) if result.content else {}
                                                return result
                                            except Exception as e:
                                                import traceback
                                                error_msg = f"Error in unified executor for tool '{tool_name}': {str(e)}"
                                                logger.error(f"{error_msg}\n{traceback.format_exc()}")
                                                return {"error": error_msg, "traceback": traceback.format_exc()}

                                        return executor

                                    self.register(name, tool, make_executor(name))
                                else:
                                    # Register tool without executor (will use mock)
                                    self.register(name, tool, lambda inputs: {"mock": True, "inputs": inputs})
                                    
                                count += 1
                                logger.debug(f"Registered tool: {name}")
                                
                            except Exception as e:
                                import traceback
                                error_msg = f"Failed to register tool '{name}': {str(e)}"
                                logger.error(f"{error_msg}\n{traceback.format_exc()}")
                                errors.append(error_msg)
                                
                except Exception as e:
                    import traceback
                    error_msg = f"Error processing TOOLS dict: {str(e)}"
                    logger.error(f"{error_msg}\n{traceback.format_exc()}")
                    errors.append(error_msg)

            # Check for @tool decorated functions
            for name in dir(module):
                try:
                    obj = getattr(module, name)
                    if callable(obj) and hasattr(obj, "_tool_metadata"):
                        metadata = obj._tool_metadata
                        tool_name = metadata.get("name", name)
                        
                        try:
                            self.register_function(
                                obj,
                                name=tool_name,
                                description=metadata.get("description"),
                            )
                            count += 1
                            logger.debug(f"Registered @tool function: {tool_name}")
                        except Exception as e:
                            import traceback
                            error_msg = f"Failed to register @tool function '{tool_name}': {str(e)}"
                            logger.error(f"{error_msg}\n{traceback.format_exc()}")
                            errors.append(error_msg)
                            
                except Exception as e:
                    import traceback
                    error_msg = f"Error processing module member '{name}': {str(e)}"
                    logger.error(f"{error_msg}\n{traceback.format_exc()}")
                    errors.append(error_msg)
            
            # Update result
            result.update({
                'success': len(errors) == 0,
                'tools_registered': count,
                'errors': errors if errors else None
            })
            
            logger.info(f"Discovered {count} tools in {module_path}" + 
                       (f" with {len(errors)} errors" if errors else ""))
            
            return result
            
        except Exception as e:
            import traceback
            error_msg = f"Failed to load module {module_path}: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            
            result.update({
                'errors': [error_msg, traceback.format_exc()]
            })
            
            return result

    def get_tools(self) -> dict[str, Tool]:
        """Get all registered Tool objects."""
        return {name: rt.tool for name, rt in self._tools.items()}

    def get_executor(self) -> Callable[[ToolUse], ToolResult]:
        """
        Get unified tool executor function.

        Returns a function that dispatches to the appropriate tool executor.
        """

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
                if isinstance(result, ToolResult):
                    return result
                return ToolResult(
                    tool_use_id=tool_use.id,
                    content=json.dumps(result) if not isinstance(result, str) else result,
                    is_error=False,
                )
            except Exception as e:
                import traceback
                import sys
                
                # Get the full traceback
                exc_type, exc_value, exc_traceback = sys.exc_info()
                tb_list = traceback.format_exception(exc_type, exc_value, exc_traceback)
                
                # Create detailed error information
                error_info = {
                    "error": str(e),
                    "type": exc_type.__name__,
                    "tool": tool_use.name,
                    "input": tool_use.input,
                    "traceback": ''.join(tb_list),
                    "context": {
                        "tool_registered": tool_use.name in self._tools,
                        "registered_tools": list(self._tools.keys()),
                    }
                }
                
                # Log the full error
                logger.error(
                    f"Error executing tool '{tool_use.name}': {str(e)}\n"
                    f"Input: {tool_use.input}\n"
                    f"Traceback: {''.join(tb_list)}"
                )
                
                return ToolResult(
                    tool_use_id=tool_use.id,
                    content=json.dumps(error_info, default=str),
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

    def register_mcp_server(
        self,
        server_config: dict[str, Any],
    ) -> dict[str, Any]:
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
            dict: {
                'success': bool,
                'tools_registered': int,
                'server_name': str,
                'error': str (if any)
            }
        """
        from framework.runner.mcp_client import MCPClient, MCPServerConfig
        
        result = {
            'success': False,
            'tools_registered': 0,
            'server_name': server_config.get('name', 'unknown'),
            'error': None
        }
        
        try:
            # Validate required fields
            if 'name' not in server_config:
                raise ValueError("Missing required field 'name' in server config")
            if 'transport' not in server_config:
                raise ValueError("Missing required field 'transport' in server config")
                
            # Create MCP client config
            config = MCPServerConfig(
                name=server_config['name'],
                transport=server_config['transport'],
                command=server_config.get('command'),
                args=server_config.get('args', []),
                env=server_config.get('env', {}),
                cwd=server_config.get('cwd'),
                url=server_config.get('url'),
                headers=server_config.get('headers', {}),
                description=server_config.get('description', '')
            )
            
            # Create and connect client
            client = MCPClient(config)
            client.connect()
            self._mcp_clients.append(client)
            
            # List tools from the server
            mcp_tools = client.list_tools()
            logger.info(f"Found {len(mcp_tools)} tools on MCP server '{config.name}'")
            # Register each tool
            count = 0
            registration_errors = []
            
            for mcp_tool in mcp_tools:
                try:
                    # Convert MCP tool to framework Tool
                    tool = self._convert_mcp_tool_to_framework_tool(mcp_tool) 
                    
                    # Skip if tool with same name already registered
                    if mcp_tool.name in self._tools:
                        logger.warning(f"Tool '{mcp_tool.name}' already registered, skipping")
                        continue

                    # Create executor that calls the MCP server
                    def make_mcp_executor(client_ref: MCPClient, tool_name: str, registry_ref):
                        def executor(inputs: dict) -> Any:
                            try:
                                # Inject session context for tools that need it
                                merged_inputs = {**registry_ref._session_context, **inputs}
                                
                                # Log tool execution
                                logger.debug(f"Executing MCP tool '{tool_name}' with inputs: {merged_inputs}")
                                
                                result = client_ref.call_tool(tool_name, merged_inputs) 
                                
                                # Log successful execution
                                logger.debug(f"MCP tool '{tool_name}' execution successful")
                                
                                # MCP tools return content array, extract the result
                                if isinstance(result, list) and len(result) > 0:
                                    if isinstance(result[0], dict) and "text" in result[0]:
                                        return result[0]["text"]
                                    return result[0]
                                return result
                            except Exception as e:
                                import traceback
                                import sys
                                
                                # Get the full traceback
                                exc_type, exc_value, exc_traceback = sys.exc_info()
                                tb_list = traceback.format_exception(exc_type, exc_value, exc_traceback)
                                
                                # Create detailed error information
                                error_info = {
                                    "error": str(e),
                                    "type": exc_type.__name__,
                                    "tool": tool_name,
                                    "input": inputs,
                                    "traceback": ''.join(tb_list),
                                    "context": {
                                        "mcp_client_connected": client_ref.is_connected() if hasattr(client_ref, 'is_connected') else False,
                                        "input_keys": list(inputs.keys()) if inputs else [],
                                    }
                                }
                                
                                # Log the full error
                                logger.error(
                                    f"MCP tool '{tool_name}' execution failed: {str(e)}\n"
                                    f"Input: {inputs}\n"
                                    f"Traceback: {''.join(tb_list)}"
                                )
                                
                                return {"error": error_info}

                        return executor

                    # Register the tool with its executor
                    self.register(
                        mcp_tool.name,
                        tool,
                        make_mcp_executor(client, mcp_tool.name, self),
                    )
                    count += 1
                    
                except Exception as e:
                    import traceback
                    error_msg = f"Failed to register MCP tool '{getattr(mcp_tool, 'name', 'unknown')}': {str(e)}"
                    logger.error(f"{error_msg}\n{traceback.format_exc()}")
                    registration_errors.append(error_msg)
            
            # Update result with success
            result.update({
                'success': len(registration_errors) == 0,
                'tools_registered': count,
                'error': '\n'.join(registration_errors) if registration_errors else None
            })
            
            logger.info(f"Registered {count} tools from MCP server '{config.name}'" + 
                       (f" with {len(registration_errors)} errors" if registration_errors else ""))
            
            return result
            
        except Exception as e:
            import traceback
            error_msg = f"Failed to register MCP server: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            
            result.update({
                'error': error_msg,
                'traceback': traceback.format_exc()
            })
            return result
            
    def _convert_mcp_tool_to_framework_tool(self, mcp_tool: Any) -> Tool:
        """
        Convert an MCP tool to a framework Tool.
        
        Args:
            mcp_tool: MCPTool object
            
        Returns:
            Framework Tool object
        """
        # Extract parameters from MCP input schema
        input_schema = getattr(mcp_tool, 'input_schema', {})
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])

        # Convert to framework Tool format
        tool = Tool(
            name=getattr(mcp_tool, 'name', 'unnamed_tool'),
            description=getattr(mcp_tool, 'description', ''),
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
        )

        return tool

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
