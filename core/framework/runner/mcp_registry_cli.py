"""CLI commands for MCP server registry contributor tooling (init, validate, test)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from framework.runner.mcp_client import MCPClient, MCPServerConfig


def register_mcp_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``hive mcp`` subcommand group."""
    mcp_parser = subparsers.add_parser("mcp", help="MCP server registry tools")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", required=True)

    # hive mcp validate <path>
    validate_parser = mcp_sub.add_parser("validate", help="Validate an MCP server manifest")
    validate_parser.add_argument("path", help="Path to manifest.json or directory containing it")
    validate_parser.set_defaults(func=cmd_validate)

    # hive mcp init
    init_parser = mcp_sub.add_parser("init", help="Scaffold a new MCP server manifest")
    init_parser.add_argument(
        "--server-url",
        default=None,
        help="URL of running server to introspect for tools",
    )
    init_parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory to write manifest.json and README.md",
    )
    init_parser.set_defaults(func=cmd_init)

    # hive mcp test
    test_parser = mcp_sub.add_parser("test", help="Test an MCP server against its manifest")

    test_parser.add_argument("path", help="Path to manifest.json or directory containing it")
    test_parser.set_defaults(func=cmd_test)


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate an MCP server manifest against the schema."""
    from framework.runner.mcp_manifest_schema import validate_manifest

    path = Path(args.path)
    if path.is_dir():
        path = path / "manifest.json"

    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        return 1

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {path}: {e}", file=sys.stderr)
        return 1

    errors = validate_manifest(data)
    if not errors:
        print(f"PASS  {path} is valid")
        return 0

    print(f"Validating {path}...\n")
    print(f"FAIL  {len(errors)} error(s) found:\n")
    for i, error in enumerate(errors, 1):
        print(f"  {i}. {error}")
    return 1


def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold a new MCP server manifest."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Prompt for required fields
    name = input("Server name (lowercase-hyphenated, e.g. jira-cloud): ")
    display_name = input("Display name (e.g. Jira Cloud MCP Server): ")
    description = input("Description: ")
    default_transport = input("Default transport (stdio/http/unix): ")
    pip_package = input("Pip package name: ")

    # Discover tools from a running server if --server-url was provided
    tools: list[dict] = []
    if args.server_url:
        try:
            resp = httpx.post(
                args.server_url,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            result = resp.json().get("result", {})
            for tool in result.get("tools", []):
                tools.append(
                    {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                    }
                )
        except Exception as e:
            print(f"Warning: could not introspect server at {args.server_url}: {e}")
            print("Continuing with empty tools list...")

    # Build manifest with sensible defaults
    manifest = {
        "name": name,
        "display_name": display_name,
        "version": "0.1.0",
        "description": description,
        "author": {"name": "TODO", "github": "TODO"},
        "maintainer": {"github": "TODO"},
        "repository": "TODO",
        "license": "MIT",
        "status": "community",
        "transport": {"supported": [default_transport], "default": default_transport},
        "install": {"pip": pip_package, "docker": None, "npm": None},
        "tools": tools or [{"name": "example_tool", "description": "TODO: describe this tool"}],
    }

    # Add transport config block for the chosen transport
    if default_transport == "stdio":
        manifest["stdio"] = {"command": "uvx", "args": [pip_package]}
    elif default_transport == "http":
        manifest["http"] = {
            "default_port": 4010,
            "health_path": "/health",
            "command": "uvx",
            "args": [pip_package, "--http", "--port", "{port}"],
        }
    elif default_transport == "unix":
        manifest["unix"] = {
            "socket_template": f"/tmp/mcp-{name}.sock",
            "command": "uvx",
            "args": [pip_package, "--unix", "{socket_path}"],
        }

    # Write manifest.json
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Created {manifest_path}")

    # Write starter README.md
    readme_path = output_dir / "README.md"
    readme_path.write_text(
        f"# {display_name}\n\n"
        f"{description}\n\n"
        f"## Install\n\n"
        f"```bash\npip install {pip_package}\n```\n\n"
        f"## Contributing\n\n"
        f"See the [Hive MCP Registry contributing guide]"
        f"(https://github.com/aden-hive/hive-mcp-registry/blob/main/CONTRIBUTING.md).\n",
        encoding="utf-8",
    )
    print(f"Created {readme_path}")

    return 0


def cmd_test(args: argparse.Namespace) -> int:
    """Test an MCP server against its manifest."""
    from framework.runner.mcp_manifest_schema import validate_manifest

    # Read and validate manifest
    path = Path(args.path)
    if path.is_dir():
        path = path / "manifest.json"

    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        return 1

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    errors = validate_manifest(data)
    if errors:
        print(f"FAIL  Manifest has {len(errors)} validation error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1

    # Build server config from manifest
    transport = data["transport"]["default"]
    transport_config = data.get(transport, {})

    config = MCPServerConfig(
        name=data["name"],
        transport=transport,
        command=transport_config.get("command"),
        args=transport_config.get("args", []),
        url=f"http://localhost:{transport_config['default_port']}"
        if transport == "http" and "default_port" in transport_config
        else None,
        socket_path=transport_config.get("socket_template") if transport == "unix" else None,
    )

    # Connect and test
    client = MCPClient(config)
    try:
        client.connect()
        server_tools = client.list_tools()
        server_tool_names = {t.name for t in server_tools}
        manifest_tool_names = {t["name"] for t in data["tools"]}

        missing = manifest_tool_names - server_tool_names
        extra = server_tool_names - manifest_tool_names
        matched = manifest_tool_names & server_tool_names

        print(f"\nTool comparison for {data['name']}:")
        for name in sorted(matched):
            print(f"  PASS  {name}")
        for name in sorted(extra):
            print(f"  WARN  {name} (on server, not in manifest)")
        for name in sorted(missing):
            print(f"  FAIL  {name} (in manifest, not on server)")

        # Health check for HTTP transport
        if transport == "http" and transport_config.get("health_path"):
            port = transport_config.get("default_port", 4010)
            health_url = f"http://localhost:{port}{transport_config['health_path']}"
            try:
                resp = httpx.get(health_url)
                if resp.status_code == 200:
                    print(f"  PASS  health check ({health_url})")
                else:
                    print(f"  FAIL  health check returned {resp.status_code}")
            except Exception as e:
                print(f"  FAIL  health check error: {e}")

        if missing:
            print(f"\nFAIL  {len(missing)} tool(s) missing from server")
            return 1

        print(f"\nPASS  All {len(matched)} manifest tool(s) found on server")
        return 0

    except Exception as e:
        print(f"Error: could not test server: {e}", file=sys.stderr)
        return 1
    finally:
        client.disconnect()
