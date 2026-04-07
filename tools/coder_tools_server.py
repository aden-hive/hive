#!/usr/bin/env python3
"""
Coder Tools MCP Server — OpenCode-inspired coding tools.

Provides rich file I/O, fuzzy-match editing, git snapshots, and shell execution
for the queen agent. Modeled after opencode's tool architecture.

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
import textwrap
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_TOOLS_SRC = Path(__file__).resolve().parent / "src"
if _TOOLS_SRC.is_dir():
    tools_src = str(_TOOLS_SRC)
    if tools_src not in sys.path:
        sys.path.insert(0, tools_src)


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

# Import command sanitizer — shared module in aden_tools
from aden_tools.tools.file_system_toolkits.command_sanitizer import (  # noqa: E402
    CommandBlockedError,
    validate_command,
)

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
    """Resolve path relative to PROJECT_ROOT. Raises ValueError if outside.

    Also allows access to ~/.hive/ directory for agent session data files.
    """
    # Normalize slashes for cross-platform (e.g. exports/hi_agent from LLM)
    path = path.replace("/", os.sep)

    # Expand ~ to home directory
    if path.startswith("~"):
        path = os.path.expanduser(path)

    if os.path.isabs(path):
        resolved = os.path.abspath(path)

        # Allow access to ~/.hive/ for agent session data
        hive_dir = os.path.expanduser("~/.hive")
        try:
            if os.path.commonpath([resolved, hive_dir]) == hive_dir:
                return resolved  # Path is under ~/.hive, allow it
        except ValueError:
            pass

        try:
            common = os.path.commonpath([resolved, PROJECT_ROOT])
        except ValueError:
            common = ""
        if common != PROJECT_ROOT:
            # LLM may emit wrong-root paths (/mnt/data, /workspace, etc.).
            # Strip known prefixes and treat the remainder as relative to PROJECT_ROOT.
            path_norm = path.replace("\\", "/")
            for prefix in (
                "/mnt/data/",
                "/mnt/data",
                "/workspace/",
                "/workspace",
                "/repo/",
                "/repo",
            ):
                p = prefix.rstrip("/") + "/"
                prefix_stripped = prefix.rstrip("/")
                if path_norm.startswith(p) or (
                    path_norm.startswith(prefix_stripped) and len(path_norm) > len(prefix)
                ):
                    suffix = path_norm[len(prefix_stripped) :].lstrip("/")
                    if suffix:
                        path = suffix.replace("/", os.sep)
                        resolved = os.path.abspath(os.path.join(PROJECT_ROOT, path))
                        break
            else:
                # Try extracting exports/ or core/ subpath from the absolute path
                parts = path.split(os.sep)
                if "exports" in parts:
                    idx = parts.index("exports")
                    path = os.sep.join(parts[idx:])
                    resolved = os.path.abspath(os.path.join(PROJECT_ROOT, path))
                elif "core" in parts:
                    idx = parts.index("core")
                    path = os.sep.join(parts[idx:])
                    resolved = os.path.abspath(os.path.join(PROJECT_ROOT, path))
                else:
                    raise ValueError(f"Access denied: '{path}' is outside the project root.")
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
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30, encoding="utf-8", stdin=subprocess.DEVNULL
    )
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
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
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


def _translate_command_for_windows(command: str) -> str:
    """Translate common Unix commands to Windows equivalents."""
    if os.name != "nt":
        return command
    cmd = command.strip()

    # mkdir -p: Unix creates parents; Windows mkdir already does; -p becomes a dir name
    if cmd.startswith("mkdir -p ") or cmd.startswith("mkdir -p\t"):
        rest = cmd[9:].lstrip().replace("/", os.sep)
        return "mkdir " + rest

    # ls / pwd: cmd.exe uses dir and cd
    # Order matters: replace longer patterns first
    for unix, win in [
        ("ls -la", "dir /a"),
        ("ls -al", "dir /a"),
        ("ls -l", "dir"),
        ("ls -a", "dir /a"),
        ("ls ", "dir "),
        ("pwd", "cd"),
    ]:
        cmd = cmd.replace(unix, win)
    # Standalone "ls" at end (e.g. "cd x && ls")
    if cmd.endswith(" ls"):
        cmd = cmd[:-3] + " dir"
    elif cmd == "ls":
        cmd = "dir"

    return cmd


@mcp.tool()
def run_command(command: str, cwd: str = "", timeout: int = 120) -> str:
    """Execute a shell command in the project context.

    PYTHONPATH is automatically set to include core/ and exports/.
    Output is truncated at 30K chars with a notice.
    Commands still execute with shell=True, so the sanitizer blocks
    explicit nested shell executables but cannot remove shell parsing.

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
        command = _translate_command_for_windows(command)
        # Validate command against safety blocklist before execution
        try:
            validate_command(command)
        except CommandBlockedError as e:
            return f"Error: {e}"
        start = time.monotonic()
        result = subprocess.run(
            command,
            shell=True,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    [
                        os.path.join(PROJECT_ROOT, "core"),
                        os.path.join(PROJECT_ROOT, "exports"),
                        os.path.join(PROJECT_ROOT, "core", "framework", "agents"),
                    ]
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
                stdin=subprocess.DEVNULL,
                encoding="utf-8",
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
def list_agent_tools(
    server_config_path: str = "",
    output_schema: str = "summary",
    group: str = "all",
    credentials: str = "all",
    service: str = "",
) -> str:
    """Discover tools available for agent building, grouped by provider.

    Connects to each MCP server, lists tools, then disconnects. Use this
    BEFORE designing an agent to know exactly which tools exist. Only use
    tools from this list in node definitions — never guess or fabricate.

    Progressive disclosure workflow (start narrow, drill in):
        list_agent_tools()                                        # provider summary
        list_agent_tools(group="google", output_schema="summary") # service breakdown
        list_agent_tools(group="google", service="gmail")           # tool names for just gmail
        list_agent_tools(group="google", service="gmail", output_schema="full")  # full detail

    Args:
        server_config_path: Path to mcp_servers.json. Default: tools/mcp_servers.json
            (the standard hive-tools server). Can also point to an agent's config
            to see what tools that specific agent has access to.
        output_schema: Controls verbosity of the response.
            "summary" (default) — provider list with tool counts + credential status. Very compact.
                When group is specified, shows service-level breakdown within that provider.
            "names" — tool names only (no descriptions), grouped by provider.
            "simple" — names + truncated descriptions.
            "full" — names + descriptions + server + input_schema.
        group: "all" (default) returns all providers. A provider like "google"
            returns only that provider's tools. Legacy prefix filters (e.g. "gmail")
            are still supported.
        credentials: Filter by credential availability.
            "all" (default) — show every tool regardless of credential status.
            "available" — only tools whose credentials are already configured.
            "unavailable" — only tools that still need credential setup.
        service: Filter to a specific service within a provider (e.g. service="gmail"
            when group="google"). Matches tools whose name starts with "<service>_".

    Returns:
        JSON with tools grouped by provider.
    """
    if output_schema not in ("summary", "names", "simple", "full"):
        return json.dumps(
            {
                "error": (
                    f"Invalid output_schema: {output_schema!r}. "
                    "Use 'summary', 'names', 'simple', or 'full'."
                )
            }
        )
    if credentials not in ("all", "available", "unavailable"):
        return json.dumps(
            {
                "error": (
                    f"Invalid credentials: {credentials!r}. "
                    "Use 'all', 'available', or 'unavailable'."
                )
            }
        )

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
        from pathlib import Path

        from framework.runner.mcp_client import MCPClient, MCPServerConfig
        from framework.loader.tool_registry import ToolRegistry
    except ImportError:
        return json.dumps({"error": "Cannot import MCPClient"})

    all_tools: list[dict] = []
    errors = []
    config_dir = Path(config_path).parent

    for server_name, server_conf in servers_config.items():
        resolved = ToolRegistry.resolve_mcp_stdio_config(
            {"name": server_name, **server_conf}, config_dir
        )
        try:
            config = MCPServerConfig(
                name=server_name,
                transport=resolved.get("transport", "stdio"),
                command=resolved.get("command"),
                args=resolved.get("args", []),
                env=resolved.get("env", {}),
                cwd=resolved.get("cwd"),
                url=resolved.get("url"),
                headers=resolved.get("headers", {}),
            )
            client = MCPClient(config)
            client.connect()
            for tool in client.list_tools():
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

    def _normalize_provider_name(raw: str | None, fallback: str) -> str:
        """Normalize provider names to stable top-level buckets."""
        text = (raw or fallback or "unknown").strip().lower()
        text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        if not text:
            return "unknown"
        head = text.split("_", 1)[0]
        # Collapse Google families (google_docs/google_cloud/google-custom-search -> google)
        if head == "google":
            return "google"
        return head

    def _build_provider_metadata() -> tuple[
        dict[str, dict[str, dict[str, dict]]], dict[str, set[str]]
    ]:
        """Build tool->provider->credential metadata index from CredentialSpecs."""
        try:
            from aden_tools.credentials import CREDENTIAL_SPECS
        except ImportError:
            return {}, {}

        tool_provider_auth: dict[str, dict[str, dict[str, dict]]] = {}
        tool_providers: dict[str, set[str]] = {}

        for cred_name, spec in CREDENTIAL_SPECS.items():
            provider_hint = spec.aden_provider_name or spec.credential_group or spec.credential_id
            provider = _normalize_provider_name(provider_hint, fallback=cred_name)
            auth_entry = {
                "env_var": spec.env_var,
                "required": spec.required,
                "description": spec.description,
                "help_url": spec.help_url,
                "credential_id": spec.credential_id,
                "credential_key": spec.credential_key,
            }
            for tool_name in spec.tools:
                tool_providers.setdefault(tool_name, set()).add(provider)
                provider_map = tool_provider_auth.setdefault(tool_name, {})
                credential_map = provider_map.setdefault(provider, {})
                credential_map[cred_name] = auth_entry

        return tool_provider_auth, tool_providers

    tool_provider_auth, tool_providers = _build_provider_metadata()

    def _get_available_credential_names() -> set[str]:
        """Return set of credential spec keys whose env_var is set in the environment."""
        try:
            from framework.credentials.validation import ensure_credential_key_env

            ensure_credential_key_env()
        except Exception:
            pass
        try:
            from aden_tools.credentials import CREDENTIAL_SPECS
        except ImportError:
            return set()
        return {
            cred_name
            for cred_name, spec in CREDENTIAL_SPECS.items()
            if spec.env_var and os.environ.get(spec.env_var)
        }

    def _tool_credentials_available(tool_name: str, available_creds: set[str]) -> bool:
        """True if all credentials required by tool_name are available (or tool needs none)."""
        required = set()
        for provider_creds in tool_provider_auth.get(tool_name, {}).values():
            required.update(provider_creds.keys())
        if not required:
            return True  # no credentials needed
        return required.issubset(available_creds)

    def _group_by_provider(tools: list[dict]) -> dict[str, dict]:
        """Group tools by provider, including auth metadata and providerless tools."""
        groups: dict[str, dict] = {}

        for t in sorted(tools, key=lambda x: (x["name"], x["server"])):
            providers = sorted(tool_providers.get(t["name"], []))
            if not providers:
                providers = ["no_provider"]

            if output_schema == "names":
                # Store just the name string — will be collapsed to flat list below
                tool_payload: dict | str = t["name"]
            else:
                desc = t["description"]
                if output_schema == "simple" and desc and len(desc) > 200:
                    desc = desc[:200].rsplit(" ", 1)[0] + "..."
                tool_payload = {
                    "name": t["name"],
                    "description": desc,
                }
                if output_schema == "full":
                    tool_payload["server"] = t["server"]
                    tool_payload["input_schema"] = t["input_schema"]

            for provider in providers:
                bucket = groups.setdefault(
                    provider,
                    {
                        "authorization": {},
                        "tools": [],
                    },
                )
                bucket["tools"].append(tool_payload)

                # Only accumulate full auth metadata for simple/full schemas.
                # summary/names use compact representations.
                if output_schema not in ("summary", "names"):
                    provider_auth = tool_provider_auth.get(t["name"], {}).get(provider, {})
                    for cred_name, auth in provider_auth.items():
                        bucket["authorization"][cred_name] = auth

        for provider, bucket in groups.items():
            if output_schema == "names":
                # Collapse to compact structure: flat sorted name list + credential keys only
                tool_names = sorted(set(bucket["tools"]))
                cred_keys: set[str] = set()
                for tn in tool_names:
                    for prov_creds in tool_provider_auth.get(tn, {}).values():
                        cred_keys.update(prov_creds.keys())
                groups[provider] = {
                    "tool_count": len(tool_names),
                    "credentials_required": sorted(cred_keys),
                    "tool_names": tool_names,
                }
            else:
                bucket["tools"] = sorted(bucket["tools"], key=lambda x: x["name"])
                bucket["authorization"] = dict(sorted(bucket["authorization"].items()))

        return dict(sorted(groups.items()))

    # Compute credential availability once (used for filtering and summary)
    available_creds: set[str] = (
        _get_available_credential_names()
        if credentials != "all" or output_schema == "summary"
        else set()
    )

    # Apply credentials filter before grouping (filter tool list)
    filtered_tools = all_tools
    if credentials != "all":
        filtered_tools = [
            t
            for t in all_tools
            if (credentials == "available")
            == _tool_credentials_available(t["name"], available_creds)
        ]

    provider_groups = _group_by_provider(filtered_tools)

    # Filter to a specific provider (preferred) or legacy prefix (fallback)
    if group != "all":
        if group in provider_groups:
            provider_groups = {group: provider_groups[group]}
        else:
            prefixed_tools = []
            for t in filtered_tools:
                parts = t["name"].split("_", 1)
                prefix = parts[0] if len(parts) > 1 else "general"
                if prefix == group:
                    prefixed_tools.append(t)
            provider_groups = _group_by_provider(prefixed_tools)

    # Apply service filter (tool name prefix within a provider, e.g. service="gmail")
    if service:
        service_prefix = service.rstrip("_") + "_"
        service_filtered: list[dict] = []
        for t in filtered_tools:
            # Only include tools from the already-filtered provider set
            tool_name = t["name"]
            in_provider = any(
                tool_name
                in p.get(
                    "tool_names", [tool_entry.get("name") for tool_entry in p.get("tools", [])]
                )
                for p in provider_groups.values()
            )
            if in_provider and tool_name.startswith(service_prefix):
                service_filtered.append(t)
        provider_groups = _group_by_provider(service_filtered)

    def _infer_service(tool_name: str) -> str:
        """Infer service name from tool name prefix (e.g. 'gmail' from 'gmail_send_message')."""
        return tool_name.split("_", 1)[0]

    # Summary mode: compact overview with counts + credential status
    if output_schema == "summary":
        if group == "all":
            # Provider-level summary (default first call)
            full_groups = _group_by_provider(all_tools) if credentials != "all" else provider_groups
            summary_providers: dict = {}
            for prov, bucket in full_groups.items():
                cred_names = bucket.get(
                    "credentials_required", sorted(bucket.get("authorization", {}).keys())
                )
                creds_ok = all(c in available_creds for c in cred_names) if cred_names else True
                summary_providers[prov] = {
                    "tool_count": len(bucket.get("tool_names", bucket.get("tools", []))),
                    "credentials_required": cred_names,
                    "credentials_available": creds_ok,
                }
            result: dict = {
                "total_tools": sum(v["tool_count"] for v in summary_providers.values()),
                "providers": summary_providers,
                "hint": (
                    "Use list_agent_tools(group='<provider>', "
                    "output_schema='summary') for service breakdown, "
                    "list_agent_tools(group='<provider>', service='<service>') for tool names. "
                    "Filter by credentials='available' to see only ready-to-use tools."
                ),
            }
        else:
            # Service-level breakdown within a specific provider
            # Re-build from all filtered tools for this provider (ignore service filter for summary)
            provider_tool_names: list[str] = []
            for bucket in provider_groups.values():
                provider_tool_names.extend(
                    bucket.get("tool_names", [e.get("name") for e in bucket.get("tools", [])])
                )

            services: dict = {}
            for tn in sorted(set(provider_tool_names)):
                svc = _infer_service(tn)
                if svc not in services:
                    svc_creds: set[str] = set()
                    for prov_creds in tool_provider_auth.get(tn, {}).values():
                        svc_creds.update(prov_creds.keys())
                    services[svc] = {"tool_count": 0, "credentials_required": sorted(svc_creds)}
                services[svc]["tool_count"] += 1
                # Accumulate credentials for other tools in this service
                for prov_creds in tool_provider_auth.get(tn, {}).values():
                    existing = set(services[svc]["credentials_required"])
                    existing.update(prov_creds.keys())
                    services[svc]["credentials_required"] = sorted(existing)

            result = {
                "provider": group,
                "total_tools": len(provider_tool_names),
                "services": services,
                "hint": (
                    f"Use list_agent_tools(group='{group}', service='<service>') "
                    "for tool names within a service."
                ),
            }
        if errors:
            result["errors"] = errors
        return json.dumps(result, indent=2, default=str)

    if output_schema == "names":
        # Compact result: no duplication, no all_tool_names list
        total = sum(p["tool_count"] for p in provider_groups.values())
        result = {
            "total": total,
            "tools_by_provider": provider_groups,
        }
    else:
        all_names = sorted({t["name"] for p in provider_groups.values() for t in p["tools"]})
        result = {
            "total": len(all_names),
            "tools_by_provider": provider_groups,
            "tools_by_category": provider_groups,  # backward-compat alias
            "all_tool_names": all_names,
        }
    if errors:
        result["errors"] = errors

    return json.dumps(result, indent=2, default=str)


# ── Meta-agent: Agent tool validation ─────────────────────────────────────


def _validate_agent_tools_impl(agent_path: str) -> dict:
    """Validate that all tools declared in an agent's nodes exist in its MCP servers.

    Returns a dict with validation result: pass/fail, missing tools per node, available tools.
    """
    try:
        resolved = _resolve_path(agent_path)
    except ValueError:
        return {"error": "Access denied: path is outside the project root."}

    # Restrict to allowed directories to prevent arbitrary code execution
    # via importlib.import_module() below.
    try:
        from framework.server.app import validate_agent_path
    except ImportError:
        return {"error": "Cannot validate agent path: framework package not available"}

    try:
        resolved = str(validate_agent_path(resolved))
    except ValueError:
        return {
            "error": "agent_path must be inside an allowed directory "
            "(exports/, examples/, or ~/.hive/agents/)"
        }

    if not os.path.isdir(resolved):
        return {"error": f"Agent directory not found: {agent_path}"}

    agent_dir = resolved  # Keep path; 'resolved' is reused for MCP config in loop

    # --- Discover available tools from agent's MCP servers ---
    mcp_config_path = os.path.join(agent_dir, "mcp_servers.json")
    if not os.path.isfile(mcp_config_path):
        return {"error": f"No mcp_servers.json found in {agent_path}"}

    try:
        from pathlib import Path

        from framework.runner.mcp_client import MCPClient, MCPServerConfig
        from framework.loader.tool_registry import ToolRegistry
    except ImportError:
        return {"error": "Cannot import MCPClient"}

    available_tools: set[str] = set()
    discovery_errors = []
    config_dir = Path(mcp_config_path).parent

    try:
        with open(mcp_config_path, encoding="utf-8") as f:
            servers_config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"Failed to read mcp_servers.json: {e}"}

    for server_name, server_conf in servers_config.items():
        resolved = ToolRegistry.resolve_mcp_stdio_config(
            {"name": server_name, **server_conf}, config_dir
        )
        try:
            config = MCPServerConfig(
                name=server_name,
                transport=resolved.get("transport", "stdio"),
                command=resolved.get("command"),
                args=resolved.get("args", []),
                env=resolved.get("env", {}),
                cwd=resolved.get("cwd"),
                url=resolved.get("url"),
                headers=resolved.get("headers", {}),
            )
            client = MCPClient(config)
            client.connect()
            for tool in client.list_tools():
                available_tools.add(tool.name)
            client.disconnect()
        except Exception as e:
            discovery_errors.append({"server": server_name, "error": str(e)})

    # --- Load agent nodes and extract declared tools ---
    agent_json_file = os.path.join(agent_dir, "agent.json")
    agent_py = os.path.join(agent_dir, "agent.py")

    nodes = None
    if os.path.isfile(agent_json_file):
        # Declarative JSON agent
        try:
            with open(agent_json_file, encoding="utf-8") as f:
                data = json.load(f)
            # Build lightweight node stubs with .tools and .id/.name
            class _NodeStub:
                def __init__(self, d):
                    self.id = d.get("id", "?")
                    self.name = d.get("name", self.id)
                    t = d.get("tools", {})
                    if isinstance(t, dict):
                        self.tools = t.get("allowed", [])
                    elif isinstance(t, list):
                        self.tools = t
                    else:
                        self.tools = []
            nodes = [_NodeStub(n) for n in data.get("nodes", [])]
        except Exception as e:
            return {"error": f"Failed to parse agent.json: {e}"}
    elif os.path.isfile(agent_py):
        # Legacy Python agent
        import importlib
        import importlib.util
        import sys

        package_name = os.path.basename(agent_dir)
        parent_dir = os.path.dirname(os.path.abspath(agent_dir))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        try:
            agent_module = importlib.import_module(package_name)
        except Exception as e:
            return {"error": f"Failed to import agent: {e}"}
        nodes = getattr(agent_module, "nodes", None)
    else:
        return {"error": f"No agent.json or agent.py found in {agent_path}"}

    if not nodes:
        return {"error": "Agent has no nodes defined"}

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
            f"in nodes do not exist. Run list_agent_tools() to see available tools "
            f"and fix the node definitions."
        )
    else:
        result["message"] = "PASS: All declared tools exist in the agent's MCP servers."

    if discovery_errors:
        result["discovery_errors"] = discovery_errors

    return result


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
    return json.dumps(_validate_agent_tools_impl(agent_path), indent=2)


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

            # Must have agent.json (declarative) or agent.py (legacy)
            has_json = os.path.isfile(os.path.join(agent_dir, "agent.json"))
            has_py = os.path.isfile(os.path.join(agent_dir, "agent.py"))
            if not has_json and not has_py:
                continue

            info = {
                "name": entry,
                "path": os.path.relpath(agent_dir, PROJECT_ROOT),
                "source": source,
                "format": "json" if has_json else "python",
                "has_mcp_config": os.path.isfile(os.path.join(agent_dir, "mcp_servers.json")),
            }

            # Read description from agent.json or __init__.py
            if has_json:
                try:
                    with open(os.path.join(agent_dir, "agent.json"), encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict) and data.get("description"):
                        info["description"] = data["description"]
                except Exception:
                    pass
            else:
                init_path = os.path.join(agent_dir, "__init__.py")
                if os.path.isfile(init_path):
                    try:
                        with open(init_path, encoding="utf-8") as f:
                            content = f.read(2000)
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


def _run_agent_tests_impl(
    agent_name: str,
    test_types: str = "all",
    fail_fast: bool = False,
) -> dict:
    """Run pytest on an agent's test suite with structured result parsing.

    Returns a dict with summary counts, per-test results, and failure details.
    """
    agent_path = Path(PROJECT_ROOT) / "exports" / agent_name
    if not agent_path.is_dir():
        # Fall back to framework agents
        agent_path = Path(PROJECT_ROOT) / "core" / "framework" / "agents" / agent_name
    tests_dir = agent_path / "tests"

    if not agent_path.is_dir():
        return {
            "error": f"Agent not found: {agent_name}",
            "hint": "Use list_agents() to see available agents.",
        }

    if not tests_dir.exists():
        return {
            "skipped": True,
            "summary": "No tests directory (OK for declarative agents)",
        }

    # Parse test types
    types_list = [t.strip() for t in test_types.split(",")]

    # Guard: pytest must be available as a subprocess command.
    import shutil

    if shutil.which("pytest") is None:
        return {
            "error": (
                "pytest is not installed or not on PATH. "
                "Hive's test runner requires pytest at runtime. "
                "Install it with: pip install 'framework[testing]' "
                "or: uv pip install 'framework[testing]'"
            ),
        }

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

    # Set PYTHONPATH (use pathsep for Windows)
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    core_path = os.path.join(PROJECT_ROOT, "core")
    exports_path = os.path.join(PROJECT_ROOT, "exports")
    fw_agents_path = os.path.join(PROJECT_ROOT, "core", "framework", "agents")
    path_parts = [core_path, exports_path, fw_agents_path, PROJECT_ROOT]
    if pythonpath:
        path_parts.append(pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(path_parts)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        return {
            "error": "Tests timed out after 120 seconds. A test may be hanging "
            "(e.g. a client-facing node waiting for stdin). Use mock mode "
            "or add timeouts to async tests.",
            "command": " ".join(cmd),
        }
    except Exception as e:
        return {
            "error": f"Failed to run pytest: {e}",
            "command": " ".join(cmd),
        }

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

    return {
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
    }


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
    return json.dumps(_run_agent_tests_impl(agent_name, test_types, fail_fast), indent=2)


# ── Meta-agent: Unified agent validation ───────────────────────────────────


@mcp.tool()
def validate_agent_package(agent_name: str) -> str:
    """Run structural validation checks on a built agent package in one call.

    Executes 5 steps and reports all results (does not stop on first failure):
      1. Class validation — checks graph structure and entry_points contract
      2. Node completeness — every NodeSpec in nodes/ must be in the nodes list,
         and GCU nodes must be referenced in a parent's sub_agents
      3. Graph validation — loads the agent graph without credential checks
      4. Tool validation — checks declared tools exist in MCP servers
      5. Tests — runs the agent's pytest suite

    Note: Credential validation is intentionally skipped here (building phase).
    Credentials are validated at run time by run_agent_with_input() preflight.

    Args:
        agent_name: Agent package name (e.g. 'my_agent'). Must exist in exports/.

    Returns:
        JSON with per-step results and overall pass/fail summary
    """
    agent_path = f"exports/{agent_name}"
    steps: dict[str, dict] = {}

    # Set up env for subprocess calls
    env = os.environ.copy()
    core_path = os.path.join(PROJECT_ROOT, "core")
    exports_path = os.path.join(PROJECT_ROOT, "exports")
    fw_agents_path = os.path.join(PROJECT_ROOT, "core", "framework", "agents")
    pythonpath = env.get("PYTHONPATH", "")
    path_parts = [core_path, exports_path, fw_agents_path, PROJECT_ROOT]
    if pythonpath:
        path_parts.append(pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(path_parts)

    # Detect agent format
    _is_json = os.path.isfile(os.path.join(PROJECT_ROOT, agent_path, "agent.json"))

    if _is_json:
        # JSON agents: validate via load_agent_config (schema + round-trip)
        try:
            _json_script = textwrap.dedent("""\
                import json, pathlib
                from framework.loader.agent_loader import load_agent_config
                data = json.loads(
                    pathlib.Path('exports/{agent_name}/agent.json').read_text()
                )
                g, goal = load_agent_config(data)
                # Check GCU sub_agent references
                sub_refs = set()
                for n in g.nodes:
                    for sa in getattr(n, 'sub_agents', []) or []:
                        sub_refs.add(sa)
                errors = []
                for n in g.nodes:
                    if n.node_type == 'gcu' and n.id not in sub_refs:
                        errors.append(
                            f"GCU node '{{n.id}}' not in any node's sub_agents"
                        )
                print(json.dumps({{
                    'valid': len(errors) == 0,
                    'nodes': len(g.nodes),
                    'edges': len(g.edges),
                    'entry': g.entry_node,
                    'errors': errors,
                }}))
            """).format(agent_name=agent_name)
            proc = subprocess.run(
                ["uv", "run", "python", "-c", _json_script],
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
                cwd=PROJECT_ROOT,
                stdin=subprocess.DEVNULL,
            )
            if proc.returncode == 0:
                result = json.loads(proc.stdout.strip())
                steps["schema_validation"] = {
                    "passed": result["valid"],
                    "output": (
                        f"{result['nodes']} nodes, {result['edges']} edges, "
                        f"entry={result['entry']}"
                    ),
                }
                if result.get("errors"):
                    steps["schema_validation"]["errors"] = result["errors"]
            else:
                steps["schema_validation"] = {
                    "passed": False,
                    "error": proc.stderr.strip()[:2000],
                }
        except Exception as e:
            steps["schema_validation"] = {"passed": False, "error": str(e)}
    else:
        # Legacy Python agents: module contract + class validation
        try:
            _contract_script = textwrap.dedent("""\
                import importlib, json
                mod = importlib.import_module('{agent_name}')
                missing = [
                    a for a in ('goal', 'nodes', 'edges')
                    if getattr(mod, a, None) is None
                ]
                print(json.dumps({{'valid': len(missing) == 0, 'missing': missing}}))
            """).format(agent_name=agent_name)
            proc = subprocess.run(
                ["uv", "run", "python", "-c", _contract_script],
                capture_output=True, text=True, timeout=30,
                env=env, cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL,
            )
            if proc.returncode == 0:
                result = json.loads(proc.stdout.strip())
                steps["module_contract"] = {
                    "passed": result["valid"],
                    "output": (
                        f"Missing: {result['missing']}"
                        if result.get("missing")
                        else "goal, nodes, edges exported correctly"
                    ),
                }
            else:
                steps["module_contract"] = {
                    "passed": False,
                    "error": proc.stderr.strip()[:1000],
                }
        except Exception as e:
            steps["module_contract"] = {"passed": False, "error": str(e)}

    # Step B: Graph validation (subprocess for import isolation)
    # Credentials are checked at run time (run_agent_with_input preflight),
    # not at build time.
    try:
        proc = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-c",
                f"from framework.loader.agent_loader import AgentLoader; "
                f'r = AgentLoader.load("exports/{agent_name}", '
                f"skip_credential_validation=True); "
                f'print("AgentLoader.load (graph-only): OK")',
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=PROJECT_ROOT,
            stdin=subprocess.DEVNULL,
        )
        passed = proc.returncode == 0
        steps["graph_validation"] = {
            "passed": passed,
            "output": (proc.stdout.strip() or proc.stderr.strip())[:2000],
        }
        if not passed:
            steps["graph_validation"]["error"] = proc.stderr.strip()[:2000]
    except Exception as e:
        steps["graph_validation"] = {"passed": False, "error": str(e)}

    # Step C: Tool validation (direct call)
    try:
        tool_result = _validate_agent_tools_impl(agent_path)
        if "error" in tool_result:
            steps["tool_validation"] = {"passed": False, "error": tool_result["error"]}
        else:
            steps["tool_validation"] = {
                "passed": tool_result.get("valid", False),
                "output": tool_result.get("message", ""),
            }
            if tool_result.get("missing_tools"):
                steps["tool_validation"]["missing_tools"] = tool_result["missing_tools"]
    except Exception as e:
        steps["tool_validation"] = {"passed": False, "error": str(e)}

    # Step D: Tests (direct call)
    try:
        test_result = _run_agent_tests_impl(agent_name)
        if test_result.get("skipped"):
            steps["tests"] = {"passed": True, "output": "No tests (skipped)"}
        elif "error" in test_result:
            steps["tests"] = {"passed": False, "error": test_result["error"]}
        else:
            all_passed = test_result.get("failed", 0) == 0 and test_result.get("errors", 0) == 0
            steps["tests"] = {
                "passed": all_passed,
                "summary": test_result.get("summary", "unknown"),
            }
            if not all_passed and test_result.get("failures"):
                steps["tests"]["failures"] = test_result["failures"]
    except Exception as e:
        steps["tests"] = {"passed": False, "error": str(e)}

    # Build summary
    failed_steps = [name for name, step in steps.items() if not step.get("passed")]
    total = len(steps)
    valid = len(failed_steps) == 0

    if valid:
        summary = f"PASS: All {total} steps passed"
    else:
        summary = f"FAIL: {len(failed_steps)} of {total} steps failed ({', '.join(failed_steps)})"

    return json.dumps(
        {
            "valid": valid,
            "agent_name": agent_name,
            "steps": steps,
            "summary": summary,
        },
        indent=2,
        default=str,
    )


# ── Meta-agent: Package initialization ─────────────────────────────────────


def _snake_to_camel(name: str) -> str:
    """Convert snake_case to CamelCase."""
    return "".join(word.capitalize() for word in name.split("_"))


def _node_var_name(node_id: str) -> str:
    """Convert node id to a Python variable name."""
    return node_id.replace("-", "_") + "_node"


@mcp.tool()
def initialize_and_build_agent(
    agent_name: str,
    nodes: str | None = None,
    _draft: dict | None = None,
) -> str:
    """Scaffold a new agent package with placeholder files.

    Creates exports/{agent_name}/ with all files needed for a runnable agent:
    config.py, nodes/__init__.py, agent.py, __init__.py, __main__.py,
    mcp_servers.json, tests/conftest.py.

    After initialization, customize the generated files:
    - System prompts and node logic in nodes/__init__.py
    - Goal and edges in agent.py
    - CLI options in __main__.py

    Args:
        agent_name: Name for the agent package. Must be snake_case (e.g. 'my_agent').
        nodes: Comma-separated node names (snake_case or kebab-case).
               If omitted, a single 'start' node is created.
               Example: 'intake,process,review'
        _draft: Internal. Draft graph metadata from planning phase, used to
                pre-populate descriptions, goals, and node metadata.

    Returns:
        JSON with files written and next steps.
    """
    import re

    if not re.match(r"^[a-z][a-z0-9_]*$", agent_name):
        return json.dumps(
            {
                "success": False,
                "error": (
                    f"Invalid agent_name '{agent_name}'. Must be snake_case: "
                    "lowercase letters, numbers, underscores, starting with a letter."
                ),
            }
        )

    node_list = [n.strip() for n in nodes.split(",") if n.strip()] if nodes else ["start"]

    # Build draft node lookup for pre-populating metadata from planning phase
    _draft_nodes: dict[str, dict] = {}
    if _draft and _draft.get("nodes"):
        for dn in _draft["nodes"]:
            _draft_nodes[dn.get("id", "")] = dn

    # Extract top-level draft metadata early so it's available for all templates
    _draft_desc = (_draft.get("description") or "") if _draft else ""

    entry_node = node_list[0]

    exports_dir = os.path.join(PROJECT_ROOT, "exports", agent_name)
    os.makedirs(exports_dir, exist_ok=True)

    files_written: dict[str, dict] = {}

    def _write(rel_path: str, content: str) -> None:
        full = os.path.join(exports_dir, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        files_written[rel_path] = {
            "path": f"exports/{agent_name}/{rel_path}",
            "size_bytes": os.path.getsize(full),
        }

    # ── Build declarative agent.json ──────────────────────────────────────
    #
    # Single JSON file replaces: config.py, nodes/__init__.py, agent.py,
    # __init__.py, __main__.py.  MCP servers are referenced by name from
    # the global registry.

    # -- Build node configs --
    json_nodes: list[dict] = []
    for node_id in node_list:
        is_first = node_id == entry_node
        dn = _draft_nodes.get(node_id, {})
        node_name = dn.get("name") or node_id.replace("_", " ").replace("-", " ").title()
        node_desc = dn.get("description") or "TODO: Describe what this node does."
        node_type = dn.get("node_type") or "event_loop"
        node_tools = dn.get("tools") or []
        node_input_keys = dn.get("input_keys") or []
        node_output_keys = dn.get("output_keys") or []
        node_sc = dn.get("success_criteria") or "TODO: Define success criteria."
        node_sub_agents = dn.get("sub_agents") or []

        node_cfg: dict = {"id": node_id, "name": node_name, "description": node_desc}
        if node_type != "event_loop":
            node_cfg["node_type"] = node_type
        if is_first:
            node_cfg["client_facing"] = True
        node_cfg["max_node_visits"] = 0
        if node_input_keys:
            node_cfg["input_keys"] = node_input_keys
        if node_output_keys:
            node_cfg["output_keys"] = node_output_keys
        if node_tools:
            node_cfg["tools"] = {"policy": "explicit", "allowed": node_tools}
        elif node_type == "gcu":
            node_cfg["tools"] = {"policy": "all"}
        else:
            node_cfg["tools"] = {"policy": "none"}
        if node_sub_agents:
            node_cfg["sub_agents"] = node_sub_agents
        node_cfg["success_criteria"] = node_sc
        node_cfg["system_prompt"] = "TODO: Add system prompt for this node.\n"
        json_nodes.append(node_cfg)

    # -- Build edges --
    _draft_edges = _draft.get("edges", []) if _draft else []
    json_edges: list[dict] = []
    if _draft_edges:
        for de in _draft_edges:
            edge: dict = {
                "from_node": de.get("source", ""),
                "to_node": de.get("target", ""),
            }
            cond = de.get("condition", "on_success").lower()
            if cond != "on_success":
                edge["condition"] = cond
            cexpr = de.get("condition_expr")
            if cexpr:
                edge["condition"] = "conditional"
                edge["condition_expr"] = cexpr
            json_edges.append(edge)
    else:
        for i in range(len(node_list) - 1):
            json_edges.append({
                "from_node": node_list[i],
                "to_node": node_list[i + 1],
            })

    # -- Build goal --
    _draft_goal = (
        (_draft.get("goal") or "TODO: Describe the agent's goal.")
        if _draft
        else "TODO: Describe the agent's goal."
    )
    _draft_sc = (_draft.get("success_criteria") or []) if _draft else []
    _draft_constraints = (_draft.get("constraints") or []) if _draft else []

    goal_cfg: dict = {"description": _draft_goal}
    if _draft_sc:
        goal_cfg["success_criteria"] = _draft_sc
    else:
        goal_cfg["success_criteria"] = ["TODO: Define success criterion."]
    if _draft_constraints:
        goal_cfg["constraints"] = _draft_constraints

    # -- Assemble full agent config --
    agent_cfg: dict = {
        "name": agent_name.replace("_", "-"),
        "version": "1.0.0",
        "description": _draft_desc or "TODO: Add agent description.",
        "goal": goal_cfg,
        "identity_prompt": "TODO: Add identity prompt.\n",
        "loop_config": {
            "max_iterations": 100,
            "max_tool_calls_per_turn": 30,
            "max_context_tokens": 32000,
        },
        "mcp_servers": [
            {"name": "hive-tools"},
            {"name": "gcu-tools"},
        ],
        "nodes": json_nodes,
        "edges": json_edges,
        "entry_node": entry_node,
        "terminal_nodes": [],
    }

    # -- Write agent.json --
    _write("agent.json", json.dumps(agent_cfg, indent=2, ensure_ascii=False) + "\n")

    # -- mcp_servers.json (kept for runner backward-compat) --
    mcp_config: dict = {
        "hive-tools": {
            "transport": "stdio",
            "command": "uv",
            "args": ["run", "python", "mcp_server.py", "--stdio"],
            "cwd": "../../tools",
            "description": "Hive tools MCP server",
        },
        "gcu-tools": {
            "transport": "stdio",
            "command": "uv",
            "args": ["run", "python", "-m", "gcu.server", "--stdio"],
            "cwd": "../../tools",
            "description": "GCU browser automation tools",
        },
    }
    _write("mcp_servers.json", json.dumps(mcp_config, indent=2))

    all_file_paths = [info["path"] for info in files_written.values()]

    return json.dumps(
        {
            "success": True,
            "agent_name": agent_name,
            "format": "declarative",
            "entry_node": entry_node,
            "nodes": node_list,
            "files_written": files_written,
            "file_count": len(files_written),
            "files": all_file_paths,
            "next_steps": [
                (
                    f"The agent is defined in exports/{agent_name}/agent.json. "
                    "Use edit_file to customize TODO placeholders: system prompts, "
                    "tools, input/output keys, goal, and identity_prompt."
                ),
                (
                    "No Python files to maintain. The runner loads agent.json "
                    "directly via load_agent_config()."
                ),
                (
                    "Template variables: add a 'variables:' section and use "
                    "{{variable_name}} in system prompts for config injection."
                ),
                f'Run validate_agent_package("{agent_name}") to verify structure',
            ],
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
        before_write=None,  # Git snapshot causes stdio deadlock on Windows; undo_changes limited
        project_root=PROJECT_ROOT,
    )

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        logger.info(f"Starting HTTP server on {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
