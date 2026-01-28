"""
MCP server management tools.

Handles registration, discovery, and management of external MCP servers
that provide tools for agents.
"""

import json
from typing import Annotated

from framework.mcp.session import get_session, save_session


def register(mcp):
    """Register MCP server management tools on the MCP server."""

    @mcp.tool()
    def add_mcp_server(
        name: Annotated[str, "Unique name for the MCP server"],
        transport: Annotated[str, "Transport type: 'stdio' or 'http'"],
        command: Annotated[str, "Command to run (for stdio transport)"] = "",
        args: Annotated[str, "JSON array of command arguments (for stdio)"] = "[]",
        cwd: Annotated[str, "Working directory (for stdio)"] = "",
        env: Annotated[str, "JSON object of environment variables (for stdio)"] = "{}",
        url: Annotated[str, "Server URL (for http transport)"] = "",
        headers: Annotated[str, "JSON object of HTTP headers (for http)"] = "{}",
        description: Annotated[str, "Description of the MCP server"] = "",
    ) -> str:
        """
        Register an MCP server as a tool source for this agent.

        The MCP server will be saved in mcp_servers.json when the agent is exported,
        and tools from this server will be available to the agent at runtime.

        Example for stdio:
            add_mcp_server(
                name="tools",
                transport="stdio",
                command="python",
                args='["mcp_server.py", "--stdio"]',
                cwd="../tools"
            )

        Example for http:
            add_mcp_server(
                name="remote-tools",
                transport="http",
                url="http://localhost:4001"
            )
        """
        session = get_session()

        # Validate transport
        if transport not in ["stdio", "http"]:
            return json.dumps(
                {
                    "success": False,
                    "error": f"Invalid transport '{transport}'. Must be 'stdio' or 'http'",
                }
            )

        # Check for duplicate
        if any(s["name"] == name for s in session.mcp_servers):
            return json.dumps(
                {"success": False, "error": f"MCP server '{name}' already registered"}
            )

        # Parse JSON inputs
        try:
            args_list = json.loads(args)
            env_dict = json.loads(env)
            headers_dict = json.loads(headers)
        except json.JSONDecodeError as e:
            return json.dumps({"success": False, "error": f"Invalid JSON: {e}"})

        # Validate required fields
        errors = []
        if transport == "stdio" and not command:
            errors.append("command is required for stdio transport")
        if transport == "http" and not url:
            errors.append("url is required for http transport")

        if errors:
            return json.dumps({"success": False, "errors": errors})

        # Build server config
        server_config = {
            "name": name,
            "transport": transport,
            "description": description,
        }

        if transport == "stdio":
            server_config["command"] = command
            server_config["args"] = args_list
            if cwd:
                server_config["cwd"] = cwd
            if env_dict:
                server_config["env"] = env_dict
        else:  # http
            server_config["url"] = url
            if headers_dict:
                server_config["headers"] = headers_dict

        # Try to connect and discover tools
        try:
            from framework.runner.mcp_client import MCPClient, MCPServerConfig

            mcp_config = MCPServerConfig(
                name=name,
                transport=transport,
                command=command if transport == "stdio" else None,
                args=args_list if transport == "stdio" else [],
                env=env_dict,
                cwd=cwd if cwd else None,
                url=url if transport == "http" else None,
                headers=headers_dict,
                description=description,
            )

            with MCPClient(mcp_config) as client:
                tools = client.list_tools()
                tool_names = [t.name for t in tools]

                # Add to session
                session.mcp_servers.append(server_config)
                save_session(session)

                return json.dumps(
                    {
                        "success": True,
                        "server": server_config,
                        "tools_discovered": len(tool_names),
                        "tools": tool_names,
                        "total_mcp_servers": len(session.mcp_servers),
                        "note": (
                            f"MCP server '{name}' registered with {len(tool_names)} tools. "
                            "These tools can now be used in llm_tool_use nodes."
                        ),
                    },
                    indent=2,
                )

        except Exception as e:
            return json.dumps(
                {
                    "success": False,
                    "error": f"Failed to connect to MCP server: {str(e)}",
                    "suggestion": (
                        "Check that the command/url is correct and the server is accessible"
                    ),
                }
            )

    @mcp.tool()
    def list_mcp_servers() -> str:
        """List all registered MCP servers for this agent."""
        session = get_session()

        if not session.mcp_servers:
            return json.dumps(
                {
                    "mcp_servers": [],
                    "total": 0,
                    "note": "No MCP servers registered. Use add_mcp_server to add tool sources.",
                }
            )

        return json.dumps(
            {
                "mcp_servers": session.mcp_servers,
                "total": len(session.mcp_servers),
            },
            indent=2,
        )

    @mcp.tool()
    def list_mcp_tools(
        server_name: Annotated[str, "Name of the MCP server to list tools from"] = "",
    ) -> str:
        """
        List tools available from registered MCP servers.

        If server_name is provided, lists tools from that specific server.
        Otherwise, lists all tools from all registered servers.
        """
        session = get_session()

        if not session.mcp_servers:
            return json.dumps({"success": False, "error": "No MCP servers registered"})

        # Filter servers if name provided
        servers_to_query = session.mcp_servers
        if server_name:
            servers_to_query = [s for s in session.mcp_servers if s["name"] == server_name]
            if not servers_to_query:
                return json.dumps(
                    {"success": False, "error": f"MCP server '{server_name}' not found"}
                )

        all_tools = {}

        for server_config in servers_to_query:
            try:
                from framework.runner.mcp_client import MCPClient, MCPServerConfig

                mcp_config = MCPServerConfig(
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

                with MCPClient(mcp_config) as client:
                    tools = client.list_tools()

                    all_tools[server_config["name"]] = [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": list(t.input_schema.get("properties", {}).keys()),
                        }
                        for t in tools
                    ]

            except Exception as e:
                all_tools[server_config["name"]] = {"error": f"Failed to connect: {str(e)}"}

        total_tools = sum(
            len(tools) if isinstance(tools, list) else 0 for tools in all_tools.values()
        )

        return json.dumps(
            {
                "success": True,
                "tools_by_server": all_tools,
                "total_tools": total_tools,
                "note": (
                    "Use these tool names in the 'tools' parameter when adding llm_tool_use nodes"
                ),
            },
            indent=2,
        )

    @mcp.tool()
    def remove_mcp_server(
        name: Annotated[str, "Name of the MCP server to remove"],
    ) -> str:
        """Remove a registered MCP server."""
        session = get_session()

        for i, server in enumerate(session.mcp_servers):
            if server["name"] == name:
                session.mcp_servers.pop(i)
                save_session(session)
                return json.dumps(
                    {
                        "success": True,
                        "removed": name,
                        "remaining_servers": len(session.mcp_servers),
                    }
                )

        return json.dumps({"success": False, "error": f"MCP server '{name}' not found"})
