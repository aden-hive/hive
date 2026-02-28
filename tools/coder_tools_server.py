#!/usr/bin/env python3
"""
Coder Tools MCP Server — OpenCode-inspired coding tools.

Provides rich file I/O, fuzzy-match editing, git snapshots, and shell execution
for the hive_coder agent. Modeled after opencode's tool architecture.

All paths scoped to a configurable project root for safety.

Usage:
    python coder_tools_server.py --stdio --project-root /path/to/project
    python coder_tools_server.py --port 4002 --project-root /path/to/project
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def setup_logger():
    if not logger.handlers:
        stream = sys.stderr if "--stdio" in sys.argv else sys.stdout
        handler = logging.StreamHandler(stream)
        formatter = logging.Formatter("[coder-tools] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


setup_logger()

if "--stdio" in sys.argv:
    import rich.console

    _original_console_init = rich.console.Console.__init__

    def _patched_console_init(self, *args, **kwargs):
        kwargs["file"] = sys.stderr
        _original_console_init(self, *args, **kwargs)

    rich.console.Console.__init__ = _patched_console_init


from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("coder-tools")

PROJECT_ROOT: str = ""
SNAPSHOT_DIR: str = ""


# ── Path resolution ───────────────────────────────────────────────────────


def _find_project_root() -> str:
    current = os.path.dirname(os.path.abspath(__file__))
    while current != os.path.dirname(current):
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        current = os.path.dirname(current)
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_path(path: str) -> str:
    """Resolve path relative to PROJECT_ROOT. Raises ValueError if outside."""
    if os.path.isabs(path):
        resolved = os.path.abspath(path)
    else:
        resolved = os.path.abspath(os.path.join(PROJECT_ROOT, path))
    try:
        common = os.path.commonpath([resolved, PROJECT_ROOT])
    except ValueError as err:
        raise ValueError(f"Access denied: '{path}' is outside the project root.") from err
    if common != PROJECT_ROOT:
        raise ValueError(f"Access denied: '{path}' is outside the project root.")
    return resolved


# ── Git snapshot system (ported from opencode's shadow git) ───────────────


def _snapshot_git(*args: str) -> str:
    """Run a git command with the snapshot GIT_DIR and PROJECT_ROOT worktree."""
    cmd = ["git", "--git-dir", SNAPSHOT_DIR, "--work-tree", PROJECT_ROOT, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


def _ensure_snapshot_repo():
    """Initialize the shadow git repo if needed."""
    if not SNAPSHOT_DIR:
        return
    if not os.path.isdir(SNAPSHOT_DIR):
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        subprocess.run(
            ["git", "init", "--bare", SNAPSHOT_DIR],
            capture_output=True,
            timeout=10,
        )
        _snapshot_git("config", "core.autocrlf", "false")


def _take_snapshot() -> str:
    """Take a git snapshot and return the tree hash. Silent on failure."""
    if not SNAPSHOT_DIR:
        return ""
    try:
        _ensure_snapshot_repo()
        _snapshot_git("add", ".")
        return _snapshot_git("write-tree")
    except Exception:
        return ""


# ── Tool: run_command ─────────────────────────────────────────────────────

MAX_COMMAND_OUTPUT = 30_000  # chars before truncation


@mcp.tool()
def run_command(command: str, cwd: str = "", timeout: int = 120) -> str:
    """Execute a shell command in the project context.

    PYTHONPATH is automatically set to include core/ and exports/.
    Output is truncated at 30K chars with a notice.

    Args:
        command: Shell command to execute
        cwd: Working directory (relative to project root)
        timeout: Timeout in seconds (default: 120, max: 300)

    Returns:
        Combined stdout/stderr with exit code
    """
    timeout = min(timeout, 300)
    work_dir = _resolve_path(cwd) if cwd else PROJECT_ROOT

    try:
        start = time.monotonic()
        result = subprocess.run(
            command,
            shell=True,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={
                **os.environ,
                "PYTHONPATH": (
                    f"{PROJECT_ROOT}/core:{PROJECT_ROOT}/exports"
                    f":{PROJECT_ROOT}/core/framework/agents"
                ),
            },
        )
        elapsed = time.monotonic() - start

        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")

        output = "\n".join(parts)

        if len(output) > MAX_COMMAND_OUTPUT:
            output = (
                output[:MAX_COMMAND_OUTPUT]
                + f"\n\n... (output truncated at {MAX_COMMAND_OUTPUT:,} chars)"
            )

        code = result.returncode
        output += f"\n\n[exit code: {code}, {elapsed:.1f}s]"
        return output
    except subprocess.TimeoutExpired:
        return (
            f"Error: Command timed out after {timeout}s. "
            "Consider breaking it into smaller operations."
        )
    except Exception as e:
        return f"Error executing command: {e}"


# ── Tool: undo_changes (git-based undo) ──────────────────────────────────


@mcp.tool()
def undo_changes(path: str = "") -> str:
    """Undo file changes by restoring from the last git snapshot.

    Uses a shadow git repository to track changes. If path is empty,
    restores ALL changed files. If path is specified, restores only that file.

    Args:
        path: Specific file to restore (empty = restore all changes)

    Returns:
        List of restored files, or error
    """
    if not SNAPSHOT_DIR:
        return "Error: Snapshot system not available (no project root detected)"

    try:
        _ensure_snapshot_repo()

        if path:
            resolved = _resolve_path(path)
            rel = os.path.relpath(resolved, PROJECT_ROOT)
            subprocess.run(
                [
                    "git",
                    "--git-dir",
                    SNAPSHOT_DIR,
                    "--work-tree",
                    PROJECT_ROOT,
                    "checkout",
                    "HEAD",
                    "--",
                    rel,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return f"Restored: {path}"
        else:
            # Get list of changed files
            diff_out = _snapshot_git("diff", "--name-only")
            if not diff_out.strip():
                return "No changes to undo."

            _snapshot_git("checkout", ".")
            changed = diff_out.strip().split("\n")
            return f"Restored {len(changed)} file(s):\n" + "\n".join(f"  {f}" for f in changed)
    except Exception as e:
        return f"Error restoring files: {e}"


# ── Meta-agent: Tool discovery ────────────────────────────────────────────


@mcp.tool()
def discover_mcp_tools(server_config_path: str = "") -> str:
    """Discover available MCP tools by connecting to servers defined in a config file.

    Connects to each MCP server, lists all tools with full schemas, then
    disconnects. Use this to see what tools are available before designing
    an agent — never rely on static documentation.

    Args:
        server_config_path: Path to mcp_servers.json (relative to project root).
            Default: the hive-tools server config at tools/mcp_servers.json.
            Can also point to any agent's mcp_servers.json.

    Returns:
        JSON listing of all tools with names, descriptions, and input schemas
    """
    # Resolve config path
    if not server_config_path:
        # Default: look for the main hive-tools mcp_servers.json
        candidates = [
            os.path.join(PROJECT_ROOT, "tools", "mcp_servers.json"),
            os.path.join(PROJECT_ROOT, "mcp_servers.json"),
        ]
        config_path = None
        for c in candidates:
            if os.path.isfile(c):
                config_path = c
                break
        if not config_path:
            return "Error: No mcp_servers.json found. Provide server_config_path."
    else:
        config_path = _resolve_path(server_config_path)
        if not os.path.isfile(config_path):
            return f"Error: Config file not found: {server_config_path}"

    try:
        with open(config_path, encoding="utf-8") as f:
            servers_config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return f"Error reading config: {e}"

    # Import MCPClient (deferred — needs PYTHONPATH to include core/)
    try:
        from framework.runner.mcp_client import MCPClient, MCPServerConfig
    except ImportError:
        return "Error: Cannot import MCPClient. Ensure PYTHONPATH includes the core/ directory."

    all_tools = []
    errors = []
    config_dir = os.path.dirname(config_path)

    for server_name, server_conf in servers_config.items():
        # Resolve cwd relative to config file location
        cwd = server_conf.get("cwd", "")
        if cwd and not os.path.isabs(cwd):
            cwd = os.path.abspath(os.path.join(config_dir, cwd))

        try:
            config = MCPServerConfig(
                name=server_name,
                transport=server_conf.get("transport", "stdio"),
                command=server_conf.get("command"),
                args=server_conf.get("args", []),
                env=server_conf.get("env", {}),
                cwd=cwd or None,
                url=server_conf.get("url"),
                headers=server_conf.get("headers", {}),
            )
            client = MCPClient(config)
            client.connect()
            tools = client.list_tools()

            for tool in tools:
                all_tools.append(
                    {
                        "server": server_name,
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.input_schema,
                    }
                )

            client.disconnect()
        except Exception as e:
            errors.append({"server": server_name, "error": str(e)})

    result = {
        "tools": all_tools,
        "total": len(all_tools),
        "servers_queried": len(servers_config),
    }
    if errors:
        result["errors"] = errors

    return json.dumps(result, indent=2, default=str)


# ── Meta-agent: Agent tool catalog ────────────────────────────────────────


@mcp.tool()
def list_agent_tools(server_config_path: str = "") -> str:
    """List all tools available for agent building from the hive-tools MCP server.

    Returns tool names grouped by category. Use this BEFORE designing an agent
    to know exactly which tools exist. Only use tools from this list in node
    definitions — never guess or fabricate tool names.

    Args:
        server_config_path: Path to mcp_servers.json. Default: tools/mcp_servers.json
            (the standard hive-tools server). Can also point to an agent's config
            to see what tools that specific agent has access to.

    Returns:
        JSON with tool names grouped by prefix (e.g. gmail_*, slack_*, etc.)
    """
    # Resolve config path
    if not server_config_path:
        candidates = [
            os.path.join(PROJECT_ROOT, "tools", "mcp_servers.json"),
            os.path.join(PROJECT_ROOT, "mcp_servers.json"),
        ]
        config_path = None
        for c in candidates:
            if os.path.isfile(c):
                config_path = c
                break
        if not config_path:
            return json.dumps({"error": "No mcp_servers.json found"})
    else:
        config_path = _resolve_path(server_config_path)
        if not os.path.isfile(config_path):
            return json.dumps({"error": f"Config not found: {server_config_path}"})

    try:
        with open(config_path, encoding="utf-8") as f:
            servers_config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return json.dumps({"error": f"Failed to read config: {e}"})

    try:
        from framework.runner.mcp_client import MCPClient, MCPServerConfig
    except ImportError:
        return json.dumps({"error": "Cannot import MCPClient"})

    all_tools: list[dict] = []
    errors = []
    config_dir = os.path.dirname(config_path)

    for server_name, server_conf in servers_config.items():
        cwd = server_conf.get("cwd", "")
        if cwd and not os.path.isabs(cwd):
            cwd = os.path.abspath(os.path.join(config_dir, cwd))
        try:
            config = MCPServerConfig(
                name=server_name,
                transport=server_conf.get("transport", "stdio"),
                command=server_conf.get("command"),
                args=server_conf.get("args", []),
                env=server_conf.get("env", {}),
                cwd=cwd or None,
                url=server_conf.get("url"),
                headers=server_conf.get("headers", {}),
            )
            client = MCPClient(config)
            client.connect()
            for tool in client.list_tools():
                all_tools.append({"name": tool.name, "description": tool.description})
            client.disconnect()
        except Exception as e:
            errors.append({"server": server_name, "error": str(e)})

    # Group by prefix (e.g., gmail_, slack_, stripe_)
    groups: dict[str, list[str]] = {}
    for t in sorted(all_tools, key=lambda x: x["name"]):
        parts = t["name"].split("_", 1)
        prefix = parts[0] if len(parts) > 1 else "general"
        groups.setdefault(prefix, []).append(t["name"])

    result: dict = {
        "total": len(all_tools),
        "tools_by_category": groups,
        "all_tool_names": sorted(t["name"] for t in all_tools),
    }
    if errors:
        result["errors"] = errors

    return json.dumps(result, indent=2)


# ── Meta-agent: Agent tool validation ─────────────────────────────────────


@mcp.tool()
def validate_agent_tools(agent_path: str) -> str:
    """Validate that all tools declared in an agent's nodes exist in its MCP servers.

    Connects to the agent's configured MCP servers, discovers available tools,
    then checks every node's declared tools against what actually exists.
    Use this after building an agent to catch hallucinated or misspelled tool names.

    Args:
        agent_path: Path to agent directory (e.g. "exports/my_agent")

    Returns:
        JSON with validation result: pass/fail, missing tools per node, available tools
    """
    resolved = _resolve_path(agent_path)
    if not os.path.isdir(resolved):
        return json.dumps({"error": f"Agent directory not found: {agent_path}"})

    # --- Discover available tools from agent's MCP servers ---
    mcp_config_path = os.path.join(resolved, "mcp_servers.json")
    if not os.path.isfile(mcp_config_path):
        return json.dumps({"error": f"No mcp_servers.json found in {agent_path}"})

    try:
        from framework.runner.mcp_client import MCPClient, MCPServerConfig
    except ImportError:
        return json.dumps({"error": "Cannot import MCPClient"})

    available_tools: set[str] = set()
    discovery_errors = []
    config_dir = os.path.dirname(mcp_config_path)

    try:
        with open(mcp_config_path, encoding="utf-8") as f:
            servers_config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return json.dumps({"error": f"Failed to read mcp_servers.json: {e}"})

    for server_name, server_conf in servers_config.items():
        cwd = server_conf.get("cwd", "")
        if cwd and not os.path.isabs(cwd):
            cwd = os.path.abspath(os.path.join(config_dir, cwd))
        try:
            config = MCPServerConfig(
                name=server_name,
                transport=server_conf.get("transport", "stdio"),
                command=server_conf.get("command"),
                args=server_conf.get("args", []),
                env=server_conf.get("env", {}),
                cwd=cwd or None,
                url=server_conf.get("url"),
                headers=server_conf.get("headers", {}),
            )
            client = MCPClient(config)
            client.connect()
            for tool in client.list_tools():
                available_tools.add(tool.name)
            client.disconnect()
        except Exception as e:
            discovery_errors.append({"server": server_name, "error": str(e)})

    # --- Load agent nodes and extract declared tools ---
    agent_py = os.path.join(resolved, "agent.py")
    if not os.path.isfile(agent_py):
        return json.dumps({"error": f"No agent.py found in {agent_path}"})

    import importlib
    import importlib.util
    import sys

    package_name = os.path.basename(resolved)
    parent_dir = os.path.dirname(os.path.abspath(resolved))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    try:
        agent_module = importlib.import_module(package_name)
    except Exception as e:
        return json.dumps({"error": f"Failed to import agent: {e}"})

    nodes = getattr(agent_module, "nodes", None)
    if not nodes:
        return json.dumps({"error": "Agent module has no 'nodes' attribute"})

    # --- Validate declared vs available ---
    missing_by_node: dict[str, list[str]] = {}
    for node in nodes:
        node_tools = getattr(node, "tools", None) or []
        missing = [t for t in node_tools if t not in available_tools]
        if missing:
            node_name = getattr(node, "name", None) or getattr(node, "id", "unknown")
            node_id = getattr(node, "id", "unknown")
            missing_by_node[f"{node_name} (id={node_id})"] = sorted(missing)

    result: dict = {
        "valid": len(missing_by_node) == 0,
        "agent": agent_path,
        "available_tool_count": len(available_tools),
    }

    if missing_by_node:
        result["missing_tools"] = missing_by_node
        result["message"] = (
            f"FAIL: {sum(len(v) for v in missing_by_node.values())} tool(s) declared "
            f"in nodes do not exist. Run discover_mcp_tools() to see available tools "
            f"and fix the node definitions."
        )
    else:
        result["message"] = "PASS: All declared tools exist in the agent's MCP servers."

    if discovery_errors:
        result["discovery_errors"] = discovery_errors

    return json.dumps(result, indent=2)


# ── Meta-agent: Agent inventory ───────────────────────────────────────────


@mcp.tool()
def list_agents() -> str:
    """List all Hive agent packages with runtime session info.

    Scans exports/ for user agents and core/framework/agents/ for framework
    agents. Checks ~/.hive/agents/ for runtime data (session counts).

    Returns:
        JSON list of agents with names, descriptions, source, and session counts
    """
    hive_agents_dir = Path.home() / ".hive" / "agents"
    agents = []
    skip = {"__pycache__", "__init__.py", ".git"}

    # Agent sources: (directory, source_label)
    scan_dirs = [
        (os.path.join(PROJECT_ROOT, "core", "framework", "agents"), "framework"),
        (os.path.join(PROJECT_ROOT, "exports"), "user"),
        (os.path.join(PROJECT_ROOT, "examples", "templates"), "example"),
    ]

    for scan_dir, source in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue

        for entry in sorted(os.listdir(scan_dir)):
            if entry in skip or entry.startswith("."):
                continue
            agent_dir = os.path.join(scan_dir, entry)
            if not os.path.isdir(agent_dir):
                continue

            # Must have agent.py to be considered an agent package
            if not os.path.isfile(os.path.join(agent_dir, "agent.py")):
                continue

            info = {
                "name": entry,
                "path": os.path.relpath(agent_dir, PROJECT_ROOT),
                "source": source,
                "has_nodes": os.path.isdir(os.path.join(agent_dir, "nodes")),
                "has_tests": os.path.isdir(os.path.join(agent_dir, "tests")),
                "has_mcp_config": os.path.isfile(os.path.join(agent_dir, "mcp_servers.json")),
            }

            # Read description from __init__.py docstring
            init_path = os.path.join(agent_dir, "__init__.py")
            if os.path.isfile(init_path):
                try:
                    with open(init_path, encoding="utf-8") as f:
                        content = f.read(2000)
                    # Extract module docstring
                    for quote in ['"""', "'''"]:
                        start = content.find(quote)
                        if start != -1:
                            end = content.find(quote, start + 3)
                            if end != -1:
                                info["description"] = (
                                    content[start + 3 : end].strip().split("\n")[0]
                                )
                                break
                except OSError:
                    pass

            # Check runtime data
            runtime_dir = hive_agents_dir / entry
            if runtime_dir.is_dir():
                sessions_dir = runtime_dir / "sessions"
                if sessions_dir.is_dir():
                    session_count = sum(
                        1
                        for d in sessions_dir.iterdir()
                        if d.is_dir() and d.name.startswith("session_")
                    )
                    info["session_count"] = session_count
                else:
                    info["session_count"] = 0
            else:
                info["session_count"] = 0

            agents.append(info)

    return json.dumps({"agents": agents, "total": len(agents)}, indent=2)


# ── Meta-agent: Session & checkpoint inspection ───────────────────────────

_MAX_TRUNCATE_LEN = 500


def _resolve_hive_agent_path(agent_name: str) -> Path:
    """Resolve agent_name to ~/.hive/agents/{agent_name}/."""
    return Path.home() / ".hive" / "agents" / agent_name


def _read_session_json(path: Path) -> dict | None:
    """Read a JSON file, returning None on failure."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _scan_agent_sessions(agent_dir: Path) -> list[tuple[str, Path]]:
    """Find session directories with state.json, sorted most-recent-first."""
    sessions: list[tuple[str, Path]] = []
    sessions_dir = agent_dir / "sessions"
    if not sessions_dir.exists():
        return sessions
    for session_dir in sessions_dir.iterdir():
        if session_dir.is_dir() and session_dir.name.startswith("session_"):
            state_path = session_dir / "state.json"
            if state_path.exists():
                sessions.append((session_dir.name, state_path))
    sessions.sort(key=lambda t: t[0], reverse=True)
    return sessions


def _truncate_value(value: object, max_len: int = _MAX_TRUNCATE_LEN) -> object:
    """Truncate a value's JSON representation if too long."""
    s = json.dumps(value, default=str)
    if len(s) <= max_len:
        return value
    return {"_truncated": True, "_preview": s[:max_len] + "...", "_length": len(s)}


@mcp.tool()
def list_agent_sessions(
    agent_name: str,
    status: str = "",
    limit: int = 20,
) -> str:
    """List sessions for an agent, with optional status filter.

    Use this to see what sessions exist for a built agent, find
    failed sessions for debugging, or check execution history.

    Args:
        agent_name: Agent package name (e.g. 'deep_research_agent')
        status: Filter by status: 'active', 'paused', 'completed',
            'failed', 'cancelled'. Empty for all.
        limit: Maximum results (default 20)

    Returns:
        JSON with session summaries sorted most-recent-first
    """
    agent_dir = _resolve_hive_agent_path(agent_name)
    all_sessions = _scan_agent_sessions(agent_dir)

    if not all_sessions:
        return json.dumps(
            {
                "agent_name": agent_name,
                "sessions": [],
                "total": 0,
                "hint": (
                    f"No sessions found at {agent_dir}/sessions/. Has this agent been run yet?"
                ),
            }
        )

    summaries = []
    for session_id, state_path in all_sessions:
        data = _read_session_json(state_path)
        if data is None:
            continue

        session_status = data.get("status", "")
        if status and session_status != status:
            continue

        timestamps = data.get("timestamps", {})
        progress = data.get("progress", {})
        checkpoint_dir = state_path.parent / "checkpoints"

        summaries.append(
            {
                "session_id": session_id,
                "status": session_status,
                "goal_id": data.get("goal_id", ""),
                "started_at": timestamps.get("started_at", ""),
                "updated_at": timestamps.get("updated_at", ""),
                "completed_at": timestamps.get("completed_at"),
                "current_node": progress.get("current_node"),
                "steps_executed": progress.get("steps_executed", 0),
                "execution_quality": progress.get("execution_quality", ""),
                "has_checkpoints": (
                    checkpoint_dir.exists() and any(checkpoint_dir.glob("cp_*.json"))
                ),
            }
        )

    total = len(summaries)
    page = summaries[:limit]
    return json.dumps(
        {
            "agent_name": agent_name,
            "sessions": page,
            "total": total,
        },
        indent=2,
    )


@mcp.tool()
def get_agent_session_state(agent_name: str, session_id: str) -> str:
    """Load full session state (excluding memory to prevent context bloat).

    Returns status, progress, result, metrics, and checkpoint info.
    Use get_agent_session_memory to read memory contents separately.

    Args:
        agent_name: Agent package name (e.g. 'deep_research_agent')
        session_id: Session ID (e.g. 'session_20260208_143022_abc12345')

    Returns:
        JSON with full session state
    """
    agent_dir = _resolve_hive_agent_path(agent_name)
    state_path = agent_dir / "sessions" / session_id / "state.json"
    data = _read_session_json(state_path)
    if data is None:
        return json.dumps({"error": f"Session not found: {session_id}"})

    # Exclude memory values but show keys
    memory = data.get("memory", {})
    data["memory_keys"] = list(memory.keys()) if isinstance(memory, dict) else []
    data["memory_size"] = len(memory) if isinstance(memory, dict) else 0
    data.pop("memory", None)

    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_agent_session_memory(
    agent_name: str,
    session_id: str,
    key: str = "",
) -> str:
    """Read memory contents from a session.

    Memory stores intermediate results passed between nodes. Use this
    to inspect what data was produced during execution.

    Args:
        agent_name: Agent package name
        session_id: Session ID
        key: Specific memory key to retrieve. Empty for all keys.

    Returns:
        JSON with memory contents
    """
    agent_dir = _resolve_hive_agent_path(agent_name)
    state_path = agent_dir / "sessions" / session_id / "state.json"
    data = _read_session_json(state_path)
    if data is None:
        return json.dumps({"error": f"Session not found: {session_id}"})

    memory = data.get("memory", {})
    if not isinstance(memory, dict):
        memory = {}

    if key:
        if key not in memory:
            return json.dumps(
                {
                    "error": f"Memory key not found: '{key}'",
                    "available_keys": list(memory.keys()),
                }
            )
        return json.dumps(
            {
                "session_id": session_id,
                "key": key,
                "value": memory[key],
                "value_type": type(memory[key]).__name__,
            },
            indent=2,
            default=str,
        )

    return json.dumps(
        {
            "session_id": session_id,
            "memory": memory,
            "total_keys": len(memory),
        },
        indent=2,
        default=str,
    )


@mcp.tool()
def list_agent_checkpoints(
    agent_name: str,
    session_id: str,
) -> str:
    """List checkpoints for a session.

    Checkpoints capture execution state at node boundaries. Use this
    to find recovery points or understand execution flow.

    Args:
        agent_name: Agent package name
        session_id: Session ID

    Returns:
        JSON with checkpoint summaries
    """
    agent_dir = _resolve_hive_agent_path(agent_name)
    session_dir = agent_dir / "sessions" / session_id
    checkpoint_dir = session_dir / "checkpoints"

    if not session_dir.exists():
        return json.dumps({"error": f"Session not found: {session_id}"})

    if not checkpoint_dir.exists():
        return json.dumps(
            {
                "session_id": session_id,
                "checkpoints": [],
                "total": 0,
            }
        )

    # Try index.json first
    index_data = _read_session_json(checkpoint_dir / "index.json")
    if index_data and "checkpoints" in index_data:
        checkpoints = index_data["checkpoints"]
    else:
        # Fallback: scan individual checkpoint files
        checkpoints = []
        for cp_file in sorted(checkpoint_dir.glob("cp_*.json")):
            cp_data = _read_session_json(cp_file)
            if cp_data:
                checkpoints.append(
                    {
                        "checkpoint_id": cp_data.get("checkpoint_id", cp_file.stem),
                        "checkpoint_type": cp_data.get("checkpoint_type", ""),
                        "created_at": cp_data.get("created_at", ""),
                        "current_node": cp_data.get("current_node"),
                        "next_node": cp_data.get("next_node"),
                        "is_clean": cp_data.get("is_clean", True),
                        "description": cp_data.get("description", ""),
                    }
                )

    latest_id = None
    if index_data:
        latest_id = index_data.get("latest_checkpoint_id")
    elif checkpoints:
        latest_id = checkpoints[-1].get("checkpoint_id")

    return json.dumps(
        {
            "session_id": session_id,
            "checkpoints": checkpoints,
            "total": len(checkpoints),
            "latest_checkpoint_id": latest_id,
        },
        indent=2,
    )


@mcp.tool()
def get_agent_checkpoint(
    agent_name: str,
    session_id: str,
    checkpoint_id: str = "",
) -> str:
    """Load a specific checkpoint's full state.

    Returns shared memory snapshot, execution path, outputs, and metrics.
    If checkpoint_id is empty, loads the latest checkpoint.

    Args:
        agent_name: Agent package name
        session_id: Session ID
        checkpoint_id: Specific checkpoint ID, or empty for latest

    Returns:
        JSON with full checkpoint data
    """
    agent_dir = _resolve_hive_agent_path(agent_name)
    checkpoint_dir = agent_dir / "sessions" / session_id / "checkpoints"

    if not checkpoint_dir.exists():
        return json.dumps({"error": f"No checkpoints for session: {session_id}"})

    if not checkpoint_id:
        index_data = _read_session_json(checkpoint_dir / "index.json")
        if index_data and index_data.get("latest_checkpoint_id"):
            checkpoint_id = index_data["latest_checkpoint_id"]
        else:
            cp_files = sorted(checkpoint_dir.glob("cp_*.json"))
            if not cp_files:
                return json.dumps({"error": f"No checkpoints for session: {session_id}"})
            checkpoint_id = cp_files[-1].stem

    cp_path = checkpoint_dir / f"{checkpoint_id}.json"
    data = _read_session_json(cp_path)
    if data is None:
        return json.dumps({"error": f"Checkpoint not found: {checkpoint_id}"})

    return json.dumps(data, indent=2, default=str)


# ── Meta-agent: Test execution ────────────────────────────────────────────


@mcp.tool()
def run_agent_tests(
    agent_name: str,
    test_types: str = "all",
    fail_fast: bool = False,
) -> str:
    """Run pytest on an agent's test suite with structured result parsing.

    Automatically sets PYTHONPATH so framework and agent packages are
    importable. Parses pytest output into structured pass/fail results.

    Args:
        agent_name: Agent package name (e.g. 'deep_research_agent')
        test_types: Comma-separated test types: 'constraint', 'success',
            'edge_case', 'all' (default: 'all')
        fail_fast: Stop on first failure (default: False)

    Returns:
        JSON with summary counts, per-test results, and failure details
    """
    agent_path = Path(PROJECT_ROOT) / "exports" / agent_name
    if not agent_path.is_dir():
        # Fall back to framework agents
        agent_path = Path(PROJECT_ROOT) / "core" / "framework" / "agents" / agent_name
    tests_dir = agent_path / "tests"

    if not agent_path.is_dir():
        return json.dumps(
            {
                "error": f"Agent not found: {agent_name}",
                "hint": "Use list_agents() to see available agents.",
            }
        )

    if not tests_dir.exists():
        return json.dumps(
            {
                "error": f"No tests directory: exports/{agent_name}/tests/",
                "hint": "Create test files in the tests/ directory first.",
            }
        )

    # Parse test types
    types_list = [t.strip() for t in test_types.split(",")]

    # Build pytest command
    cmd = ["pytest"]

    if "all" in types_list:
        cmd.append(str(tests_dir))
    else:
        type_to_file = {
            "constraint": "test_constraints.py",
            "success": "test_success_criteria.py",
            "edge_case": "test_edge_cases.py",
        }
        for t in types_list:
            if t in type_to_file:
                test_file = tests_dir / type_to_file[t]
                if test_file.exists():
                    cmd.append(str(test_file))

    cmd.append("-v")
    if fail_fast:
        cmd.append("-x")
    cmd.append("--tb=short")

    # Set PYTHONPATH
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    core_path = os.path.join(PROJECT_ROOT, "core")
    exports_path = os.path.join(PROJECT_ROOT, "exports")
    fw_agents_path = os.path.join(PROJECT_ROOT, "core", "framework", "agents")
    env["PYTHONPATH"] = f"{core_path}:{exports_path}:{fw_agents_path}:{PROJECT_ROOT}:{pythonpath}"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {
                "error": "Tests timed out after 120 seconds. A test may be hanging "
                "(e.g. a client-facing node waiting for stdin). Use mock mode "
                "or add timeouts to async tests.",
                "command": " ".join(cmd),
            }
        )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to run pytest: {e}",
                "command": " ".join(cmd),
            }
        )

    output = result.stdout + "\n" + result.stderr

    # Parse summary line (e.g. "5 passed, 2 failed in 1.23s")
    summary_match = re.search(r"=+ ([\d\w,\s]+) in [\d.]+s =+", output)
    summary_text = summary_match.group(1) if summary_match else "unknown"

    passed = failed = skipped = errors = 0
    for label, pattern in [
        ("passed", r"(\d+) passed"),
        ("failed", r"(\d+) failed"),
        ("skipped", r"(\d+) skipped"),
        ("errors", r"(\d+) error"),
    ]:
        m = re.search(pattern, summary_text)
        if m:
            if label == "passed":
                passed = int(m.group(1))
            elif label == "failed":
                failed = int(m.group(1))
            elif label == "skipped":
                skipped = int(m.group(1))
            elif label == "errors":
                errors = int(m.group(1))

    total = passed + failed + skipped + errors

    # Extract per-test results
    test_results = []
    test_pattern = re.compile(r"([\w/]+\.py)::(\w+)\s+(PASSED|FAILED|SKIPPED|ERROR)")
    for m in test_pattern.finditer(output):
        test_results.append(
            {
                "file": m.group(1),
                "test_name": m.group(2),
                "status": m.group(3).lower(),
            }
        )

    # Extract failure details
    failures = []
    failure_section = re.search(
        r"=+ FAILURES =+(.+?)(?:=+ (?:short test summary|ERRORS|warnings) =+|$)",
        output,
        re.DOTALL,
    )
    if failure_section:
        failure_text = failure_section.group(1)
        failure_blocks = re.split(r"_+ (test_\w+) _+", failure_text)
        for i in range(1, len(failure_blocks), 2):
            if i + 1 < len(failure_blocks):
                detail = failure_blocks[i + 1].strip()
                if len(detail) > 2000:
                    detail = detail[:2000] + "\n... (truncated)"
                failures.append(
                    {
                        "test_name": failure_blocks[i],
                        "detail": detail,
                    }
                )

    return json.dumps(
        {
            "agent_name": agent_name,
            "summary": summary_text,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "errors": errors,
            "total": total,
            "test_results": test_results,
            "failures": failures,
            "exit_code": result.returncode,
        },
        indent=2,
    )


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    global PROJECT_ROOT, SNAPSHOT_DIR

    from aden_tools.file_ops import register_file_tools

    parser = argparse.ArgumentParser(description="Coder Tools MCP Server")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--port", type=int, default=int(os.getenv("CODER_TOOLS_PORT", "4002")))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args()

    PROJECT_ROOT = os.path.abspath(args.project_root) if args.project_root else _find_project_root()
    SNAPSHOT_DIR = os.path.join(
        os.path.expanduser("~"),
        ".hive",
        "snapshots",
        os.path.basename(PROJECT_ROOT),
    )
    logger.info(f"Project root: {PROJECT_ROOT}")
    logger.info(f"Snapshot dir: {SNAPSHOT_DIR}")

    register_file_tools(
        mcp,
        resolve_path=_resolve_path,
        before_write=_take_snapshot,
        project_root=PROJECT_ROOT,
    )

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        logger.info(f"Starting HTTP server on {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
