"""MCP Inspector launcher for debugging MCP servers."""

import os
import subprocess
import sys
from pathlib import Path


def check_node_version() -> bool:
    """Check if Node.js version meets minimum requirement (22.7.5)."""
    try:
        result = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, check=True
        )
        version_str = result.stdout.strip().lstrip("v")
        major, minor, patch = map(int, version_str.split(".")[:3])

        if (major, minor, patch) >= (22, 7, 5):
            return True

        print(f"Node.js {version_str} found, but >=22.7.5 required for MCP Inspector")
        print("Install Node 22+ from https://nodejs.org/")
        return False

    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        print("Node.js not found. Install Node 22+ from https://nodejs.org/")
        return False


def launch_inspector(
    config_path: str | None = None, port: int = 6274, server: str | None = None
) -> int:
    """
    Launch MCP Inspector using npx.

    Args:
        config_path: Path to .mcp.json config file (defaults to core/.mcp.json)
        port: Port for inspector UI (default: 6274)
        server: Specific server name to inspect (if None, will prompt to choose)

    Returns:
        Exit code (0 for success)
    """
    import json
    import tempfile

    # Check Node version
    if not check_node_version():
        return 1

    # Use default config if not specified
    if not config_path:
        # Try to find core/.mcp.json relative to project root
        project_root = Path.cwd()
        default_config = project_root / "core" / ".mcp.json"

        if not default_config.exists():
            print(f"Config file not found: {default_config}")
            print("Specify a config file with --config")
            return 1

        config_path = str(default_config)

    config_file = Path(config_path).resolve()

    if not config_file.exists():
        print(f"Config file not found: {config_file}")
        return 1

    # Read and resolve relative paths in config
    try:
        with open(config_file) as f:
            config = json.load(f)

        # Resolve relative cwd paths to absolute paths
        config_dir = config_file.parent
        project_root = config_dir.parent if config_dir.name == "core" else config_dir

        servers = config.get("mcpServers", {})
        for server_config in servers.values():
            if "cwd" in server_config:
                cwd = server_config["cwd"]
                # If relative path, resolve from project root
                if not Path(cwd).is_absolute():
                    abs_cwd = (project_root / cwd).resolve()
                    server_config["cwd"] = str(abs_cwd)
                else:
                    abs_cwd = Path(cwd)

                # If command is just "python", try to find venv in cwd
                if server_config.get("command") == "python":
                    venv_python = abs_cwd / ".venv" / "bin" / "python"
                    if venv_python.exists():
                        server_config["command"] = str(venv_python)
                    else:
                        # Fallback: try project root venv
                        root_venv_python = project_root / ".venv" / "bin" / "python"
                        if root_venv_python.exists():
                            server_config["command"] = str(root_venv_python)

                # Resolve relative script paths in args to absolute paths
                if "args" in server_config:
                    resolved_args = []
                    for arg in server_config["args"]:
                        # If arg looks like a Python script (ends with .py) and is relative
                        if arg.endswith(".py") and not Path(arg).is_absolute():
                            script_path = abs_cwd / arg
                            if script_path.exists():
                                resolved_args.append(str(script_path))
                            else:
                                resolved_args.append(arg)
                        else:
                            resolved_args.append(arg)
                    server_config["args"] = resolved_args

                # Set PYTHONPATH to include workspace packages
                if "env" not in server_config:
                    server_config["env"] = {}

                # Add core and tools to PYTHONPATH for workspace dependencies
                pythonpath_parts = [
                    str(project_root / "core"),
                    str(project_root / "tools" / "src"),
                ]
                existing_pythonpath = server_config["env"].get("PYTHONPATH", "")
                if existing_pythonpath:
                    pythonpath_parts.append(existing_pythonpath)

                server_config["env"]["PYTHONPATH"] = ":".join(pythonpath_parts)

        # Write resolved config to temp file (needed for all branches)
        temp_config = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix="mcp-config-"
        )
        json.dump(config, temp_config, indent=2)
        temp_config_path = temp_config.name
        temp_config.close()

        # If no server specified and multiple servers exist, prompt user
        if not server and len(servers) > 1:
            print(f"Multiple servers found: {', '.join(servers.keys())}")
            print("Which server would you like to inspect?")
            for i, name in enumerate(servers.keys(), 1):
                print(f"  {i}. {name}")
            print()

            try:
                choice = input("Enter number or name: ").strip()

                if choice.isdigit():
                    idx = int(choice) - 1
                    server_list = list(servers.keys())
                    if 0 <= idx < len(server_list):
                        server = server_list[idx]
                    else:
                        print("Invalid choice")
                        return 1
                else:
                    if choice in servers:
                        server = choice
                    else:
                        print(f"Server '{choice}' not found")
                        return 1

            except (EOFError, KeyboardInterrupt):
                print("\nCancelled")
                return 1

        elif not server and len(servers) == 1:
            # Only one server, use it automatically
            server = list(servers.keys())[0]

        # Validate that we have a server selected
        if not server:
            print("No server selected")
            return 1

    except Exception as e:
        print(f"Error processing config: {e}")
        return 1

    print(f"Launching MCP Inspector for '{server}' at http://localhost:{port}")
    print(f"Using config: {config_file}")
    print()

    try:
        # Launch inspector with npx
        env = {**os.environ, "PORT": str(port)}
        subprocess.run(
            [
                "npx",
                "@modelcontextprotocol/inspector",
                "--config",
                temp_config_path,
                "--server",
                server,
            ],
            env=env,
            check=True,
        )
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Inspector failed with exit code {e.returncode}")
        return e.returncode
    except KeyboardInterrupt:
        print("\nInspector stopped")
        return 0
    except Exception as e:
        print(f"Error launching inspector: {e}")
        return 1
    finally:
        # Clean up temp file
        try:
            Path(temp_config_path).unlink()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(launch_inspector())
