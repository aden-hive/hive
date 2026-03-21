"""CLI commands for MCP server registry management.

Commands:
    hive mcp install <name>           Install a server from the registry
    hive mcp add                      Register a local/running MCP server
    hive mcp remove <name>            Remove an installed server
    hive mcp enable <name>            Enable a server
    hive mcp disable <name>           Disable a server
    hive mcp list                     List installed servers
    hive mcp info <name>              Show server details
    hive mcp config <name>            Set env/header overrides
    hive mcp search <query>           Search the registry index
    hive mcp health [name]            Check server health
    hive mcp update                   Refresh index and update installed servers
    hive mcp update <name>            Update a single installed server
    hive mcp init                     Scaffold a new MCP server manifest
    hive mcp validate <path>          Validate an MCP server manifest
    hive mcp test <path>              Test an MCP server against its manifest
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# ── Shared helpers ──────────────────────────────────────────────────


def _get_registry(base_path: Path | None = None):
    """Initialize and return an MCPRegistry instance."""
    from framework.runner.mcp_registry import MCPRegistry

    registry = MCPRegistry(base_path=base_path)
    registry.initialize()
    return registry


def _ensure_index_available(registry) -> bool:
    """Ensure the registry index is cached locally.

    If no index exists or the cache is stale, fetches a fresh copy.
    Returns True if a usable index exists, False otherwise.

    Semantics:
    - Stale cache + refresh fails -> warn and continue with stale cache (True)
    - No cache + refresh fails -> hard fail (False)
    """
    import httpx

    cache_exists = (registry._cache_dir / "registry_index.json").exists()

    if registry.is_index_stale():
        print("Updating registry index...", file=sys.stderr)
        try:
            count = registry.update_index()
            print(f"Registry index updated ({count} servers available).", file=sys.stderr)
            return True
        except (httpx.HTTPError, OSError) as exc:
            if cache_exists:
                print(
                    f"Warning: failed to update registry index: {exc}\nUsing cached index.",
                    file=sys.stderr,
                )
                return True
            print(
                f"Error: no registry index available and refresh failed: {exc}\n"
                "Check your network connection and try: hive mcp update",
                file=sys.stderr,
            )
            return False

    return cache_exists


_SECURITY_NOTICE = (
    "Registry servers run code on your machine. Only install servers you trust.\n"
    "Learn more: https://github.com/aden-hive/hive-mcp-registry"
)
_NOTICE_SENTINEL = ".security_notice_shown"


def _print_security_notice_if_first_use(registry_base: Path) -> None:
    """Print a one-time security notice on first registry install.

    Only prints the notice. Call _mark_security_notice_shown() after
    a successful install to persist the sentinel.
    """
    sentinel = registry_base / _NOTICE_SENTINEL
    if sentinel.exists():
        return
    print(f"\n  {_SECURITY_NOTICE}\n", file=sys.stderr)


def _mark_security_notice_shown(registry_base: Path) -> None:
    """Persist the security notice sentinel after a successful install."""
    sentinel = registry_base / _NOTICE_SENTINEL
    try:
        sentinel.touch()
    except OSError:
        pass


def _prompt_for_missing_credentials(
    registry,
    name: str,
    manifest: dict,
) -> None:
    """Prompt for required credentials not already set in env or overrides."""
    credentials = manifest.get("credentials", [])
    if not credentials:
        return

    server = registry.get_server(name)
    existing_overrides = server.get("overrides", {}).get("env", {}) if server else {}

    prompted = False
    for cred in credentials:
        if not isinstance(cred, dict):
            continue
        env_var = cred.get("env_var", "")
        if not env_var:
            continue
        required = cred.get("required", False)
        if not required:
            continue

        # Skip if already in environment or overrides
        if os.environ.get(env_var) or existing_overrides.get(env_var):
            continue

        if not prompted:
            print(f"\n{name} requires credentials:", file=sys.stderr)
            prompted = True

        description = cred.get("description", env_var)
        help_url = cred.get("help_url", "")
        help_hint = f" (get one at {help_url})" if help_url else ""

        try:
            value = input(f"  {description}{help_hint}\n  {env_var}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSkipped credential prompting.", file=sys.stderr)
            return

        if value:
            registry.set_override(name, env_var, value, override_type="env")


def _parse_key_value_pairs(values: list[str]) -> dict[str, str]:
    """Parse KEY=VAL pairs from CLI args. Raises ValueError on bad format."""
    result = {}
    for item in values:
        if "=" not in item:
            raise ValueError(
                f"Invalid format: '{item}'. Expected KEY=VALUE.\n"
                f"Example: --set JIRA_API_TOKEN=abc123"
            )
        key, _, value = item.partition("=")
        if not key:
            raise ValueError(f"Invalid format: '{item}'. Key cannot be empty.")
        result[key] = value
    return result


def _find_agents_using_server(registry, name: str) -> list[str]:
    """Scan agent directories for mcp_registry.json files that would load a server.

    Uses MCPRegistry.load_agent_selection() to resolve actual selection logic
    so results stay consistent with runtime behavior.
    """
    agent_dirs: list[Path] = []
    # parents: [0]=runner, [1]=framework, [2]=core, [3]=hive (project root)
    # NOTE: This path arithmetic assumes running from the source tree layout.
    # It will not resolve correctly if installed via pip into site-packages.
    project_root = Path(__file__).resolve().parents[3]
    core_dir = Path(__file__).resolve().parents[2]

    candidates = [
        project_root / "exports",
        core_dir / "exports",
        core_dir / "framework" / "agents",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            for child in candidate.iterdir():
                if child.is_dir():
                    agent_dirs.append(child)

    matches = []
    for agent_dir in agent_dirs:
        registry_json = agent_dir / "mcp_registry.json"
        if not registry_json.exists():
            continue
        try:
            configs = registry.load_agent_selection(agent_dir)
            resolved_names = {c["name"] for c in configs}
            if name in resolved_names:
                matches.append(str(agent_dir))
        except Exception:
            continue

    return matches


def _render_installed_table(entries: list[dict]) -> None:
    """Render installed servers as a formatted table."""
    if not entries:
        print("No servers installed.")
        print("Run 'hive mcp install <name>' or 'hive mcp add' to get started.")
        return

    # Column widths
    name_w = max(len(e["name"]) for e in entries)
    name_w = max(name_w, 4)
    transport_w = max(len(e.get("transport", "")) for e in entries)
    transport_w = max(transport_w, 9)

    header = (
        f"  {'NAME':<{name_w}}  "
        f"{'TRANSPORT':<{transport_w}}  "
        f"{'ENABLED':<7}  "
        f"{'HEALTH':<9}  "
        f"{'TOOLS':<5}  "
        f"{'TRUST':<10}  "
        f"{'SOURCE'}"
    )
    print(header)
    print("  " + "─" * (len(header) - 2))

    for entry in entries:
        enabled = "yes" if entry.get("enabled", True) else "no"
        health = entry.get("last_health_status") or "unknown"
        health_sym = {"healthy": "✓", "unhealthy": "✗"}.get(health, "●")
        source = entry.get("source", "")
        manifest = entry.get("manifest", {})
        tools_count = str(len(manifest.get("tools", [])))
        trust_tier = manifest.get("status", "")
        print(
            f"  {entry['name']:<{name_w}}  "
            f"{entry.get('transport', ''):<{transport_w}}  "
            f"{enabled:<7}  "
            f"{health_sym} {health:<7}  "
            f"{tools_count:<5}  "
            f"{trust_tier:<10}  "
            f"{source}"
        )


def _render_available_table(entries: list[dict]) -> None:
    """Render available registry servers as a formatted table."""
    if not entries:
        print("No servers in registry index.")
        print("Run 'hive mcp update' to refresh the index.")
        return

    name_w = max(len(e["name"]) for e in entries)
    name_w = max(name_w, 4)

    header = f"  {'NAME':<{name_w}}  {'VERSION':<9}  {'STATUS':<10}  DESCRIPTION"
    print(header)
    print("  " + "─" * (len(header) - 2))

    for entry in entries:
        version = entry.get("version", "")
        status = entry.get("status", "community")
        desc = entry.get("description", "")
        # Truncate long descriptions
        if len(desc) > 60:
            desc = desc[:57] + "..."
        print(f"  {entry['name']:<{name_w}}  {version:<9}  {status:<10}  {desc}")


def _mask_overrides(overrides: dict) -> dict:
    """Replace override values with '<set>' markers. Shared by all output paths."""
    masked: dict[str, dict[str, str]] = {}
    if overrides.get("env"):
        masked["env"] = dict.fromkeys(overrides["env"], "<set>")
    else:
        masked["env"] = {}
    if overrides.get("headers"):
        masked["headers"] = dict.fromkeys(overrides["headers"], "<set>")
    else:
        masked["headers"] = {}
    return masked


def _emit_json(data: Any) -> None:
    """Print data as formatted JSON."""
    print(json.dumps(data, indent=2, default=str))


# ── Command registration ───────────────────────────────────────────


def register_mcp_commands(subparsers) -> None:
    """Register the ``hive mcp`` subcommand group."""
    mcp_parser = subparsers.add_parser("mcp", help="Manage MCP servers")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", required=True)

    # ── install ──
    install_p = mcp_sub.add_parser("install", help="Install a server from the registry")
    install_p.add_argument("name", help="Server name in the registry")
    install_p.add_argument(
        "--version", dest="version", default=None, help="Pin to a specific version"
    )
    install_p.add_argument(
        "--transport", default=None, help="Override default transport (stdio, http, unix, sse)"
    )
    install_p.set_defaults(func=cmd_mcp_install)

    # ── add ──
    add_p = mcp_sub.add_parser("add", help="Register a local/running MCP server")
    add_p.add_argument("--name", required=False, help="Server name")
    add_p.add_argument(
        "--transport",
        choices=["stdio", "http", "unix", "sse"],
        default=None,
        help="Transport type",
    )
    add_p.add_argument("--url", default=None, help="Server URL (http, unix, sse)")
    add_p.add_argument("--command", default=None, help="Command to run (stdio)")
    add_p.add_argument("--args", nargs="*", default=None, help="Command arguments (stdio)")
    add_p.add_argument("--socket-path", default=None, help="Unix socket path")
    add_p.add_argument("--description", default="", help="Server description")
    add_p.add_argument("--from", dest="from_manifest", default=None, help="Path to manifest.json")
    add_p.set_defaults(func=cmd_mcp_add)

    # ── remove ──
    remove_p = mcp_sub.add_parser("remove", help="Remove an installed server")
    remove_p.add_argument("name", help="Server name")
    remove_p.set_defaults(func=cmd_mcp_remove)

    # ── enable ──
    enable_p = mcp_sub.add_parser("enable", help="Enable a disabled server")
    enable_p.add_argument("name", help="Server name")
    enable_p.set_defaults(func=cmd_mcp_enable)

    # ── disable ──
    disable_p = mcp_sub.add_parser("disable", help="Disable a server without removing it")
    disable_p.add_argument("name", help="Server name")
    disable_p.set_defaults(func=cmd_mcp_disable)

    # ── list ──
    list_p = mcp_sub.add_parser("list", help="List servers")
    list_p.add_argument(
        "--available", action="store_true", help="Show available servers from registry"
    )
    list_p.add_argument("--json", dest="output_json", action="store_true", help="Output as JSON")
    list_p.set_defaults(func=cmd_mcp_list)

    # ── info ──
    info_p = mcp_sub.add_parser("info", help="Show server details")
    info_p.add_argument("name", help="Server name")
    info_p.add_argument("--json", dest="output_json", action="store_true", help="Output as JSON")
    info_p.set_defaults(func=cmd_mcp_info)

    # ── config ──
    config_p = mcp_sub.add_parser("config", help="Set server configuration overrides")
    config_p.add_argument("name", help="Server name")
    config_p.add_argument(
        "--set",
        dest="set_env",
        nargs="+",
        metavar="KEY=VAL",
        help="Set environment variable overrides",
    )
    config_p.add_argument(
        "--set-header", dest="set_header", nargs="+", metavar="KEY=VAL", help="Set header overrides"
    )
    config_p.set_defaults(func=cmd_mcp_config)

    # ── search ──
    search_p = mcp_sub.add_parser("search", help="Search the registry")
    search_p.add_argument("query", help="Search term (name, tag, description, tool name)")
    search_p.add_argument("--json", dest="output_json", action="store_true", help="Output as JSON")
    search_p.set_defaults(func=cmd_mcp_search)

    # ── health ──
    health_p = mcp_sub.add_parser("health", help="Check server health")
    health_p.add_argument("name", nargs="?", default=None, help="Server name (all if omitted)")
    health_p.add_argument("--json", dest="output_json", action="store_true", help="Output as JSON")
    health_p.set_defaults(func=cmd_mcp_health)

    # ── update ──
    update_p = mcp_sub.add_parser(
        "update", help="Update installed servers or refresh the registry index"
    )
    update_p.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Server name to update (omit to update all registry servers)",
    )
    update_p.set_defaults(func=cmd_mcp_update)

    # ── init (contributor tooling) ──
    init_p = mcp_sub.add_parser("init", help="Scaffold a new MCP server manifest")
    init_p.add_argument(
        "--server-url", default=None, help="URL of running server to introspect for tools"
    )
    init_p.add_argument("--output-dir", default=".", help="Directory to write manifest.json and README.md")
    init_p.set_defaults(func=cmd_mcp_init)

    # ── validate (contributor tooling) ──
    validate_p = mcp_sub.add_parser("validate", help="Validate an MCP server manifest")
    validate_p.add_argument("path", help="Path to manifest.json or directory containing it")
    validate_p.set_defaults(func=cmd_mcp_validate)

    # ── test (contributor tooling) ──
    test_p = mcp_sub.add_parser("test", help="Test an MCP server against its manifest")
    test_p.add_argument("path", help="Path to manifest.json or directory containing it")
    test_p.set_defaults(func=cmd_mcp_test)


# ── P0 command handlers ────────────────────────────────────────────


def cmd_mcp_install(args) -> int:
    """Install a server from the registry index."""
    registry = _get_registry()
    _print_security_notice_if_first_use(registry._base)
    if not _ensure_index_available(registry):
        return 1

    try:
        entry = registry.install(
            args.name,
            transport=args.transport,
            version=args.version,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _mark_security_notice_shown(registry._base)

    version_str = entry.get("manifest_version", "")
    transport = entry.get("transport", "")
    print(f"✓ Installed {args.name} v{version_str} ({transport})")

    # Prompt for credentials defined in the manifest
    manifest = entry.get("manifest", {})
    _prompt_for_missing_credentials(registry, args.name, manifest)

    print("\nNext steps:")
    print(f"  hive mcp health {args.name}    Check that the server is reachable")
    print(f"  hive mcp info {args.name}      View server details")
    return 0


def cmd_mcp_add(args) -> int:
    """Register a local/running MCP server."""
    registry = _get_registry()

    # Handle --from manifest.json
    if args.from_manifest:
        return _cmd_mcp_add_from_manifest(registry, args.from_manifest)

    if not args.name:
        print(
            "Error: --name is required.\n"
            "Usage: hive mcp add --name my-server --transport http --url http://localhost:8080\n"
            "   or: hive mcp add --from manifest.json",
            file=sys.stderr,
        )
        return 1

    if not args.transport:
        print(
            f"Error: --transport is required.\n"
            f"Supported transports: stdio, http, unix, sse\n"
            f"Example: hive mcp add --name {args.name} --transport http --url http://localhost:8080",
            file=sys.stderr,
        )
        return 1

    try:
        entry = registry.add_local(
            name=args.name,
            transport=args.transport,
            url=args.url,
            command=args.command,
            args=args.args,
            socket_path=args.socket_path,
            description=args.description,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"✓ Registered {args.name} ({entry['transport']})")
    return 0


def _cmd_mcp_add_from_manifest(registry, manifest_path: str) -> int:
    """Register a server from a manifest.json file."""
    path = Path(manifest_path)
    if not path.exists():
        print(
            f"Error: manifest file not found: {manifest_path}\nCheck the path and try again.",
            file=sys.stderr,
        )
        return 1

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(
            f"Error: invalid JSON in {manifest_path}: {exc}\n"
            f"Validate with: python -m json.tool {manifest_path}",
            file=sys.stderr,
        )
        return 1

    name = manifest.get("name")
    if not name:
        print(
            f"Error: manifest missing 'name' field.\nAdd a 'name' field to {manifest_path}.",
            file=sys.stderr,
        )
        return 1

    try:
        entry = registry.add_local(name=name, manifest=manifest)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"✓ Registered {name} from {manifest_path} ({entry['transport']})")
    return 0


def cmd_mcp_remove(args) -> int:
    """Remove an installed server."""
    registry = _get_registry()
    try:
        registry.remove(args.name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"✓ Removed {args.name}")
    return 0


def cmd_mcp_enable(args) -> int:
    """Enable a disabled server."""
    registry = _get_registry()
    try:
        registry.enable(args.name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"✓ Enabled {args.name}")
    return 0


def cmd_mcp_disable(args) -> int:
    """Disable a server without removing it."""
    registry = _get_registry()
    try:
        registry.disable(args.name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"✓ Disabled {args.name}")
    return 0


def cmd_mcp_list(args) -> int:
    """List installed or available servers."""
    registry = _get_registry()

    if args.available:
        if not _ensure_index_available(registry):
            return 1
        entries = registry.list_available()
        if args.output_json:
            _emit_json(entries)
        else:
            _render_available_table(entries)
    else:
        entries = registry.list_installed()
        if args.output_json:
            safe_entries = []
            for entry in entries:
                safe = dict(entry)
                safe["overrides"] = _mask_overrides(safe.get("overrides", {}))
                safe_entries.append(safe)
            _emit_json(safe_entries)
        else:
            _render_installed_table(entries)

    return 0


def cmd_mcp_info(args) -> int:
    """Show full details for a server."""
    registry = _get_registry()
    server = registry.get_server(args.name)

    if server is None:
        print(
            f"Error: server '{args.name}' is not installed.\n"
            f"Run 'hive mcp list' to see installed servers.\n"
            f"Run 'hive mcp install {args.name}' to install from registry.",
            file=sys.stderr,
        )
        return 1

    # Enrich with agent usage for both JSON and human output
    agents = _find_agents_using_server(registry, args.name)
    if agents:
        server["used_by_agents"] = agents

    if args.output_json:
        safe = dict(server)
        safe["overrides"] = _mask_overrides(safe.get("overrides", {}))
        _emit_json(safe)
        return 0

    manifest = server.get("manifest", {})
    overrides = _mask_overrides(server.get("overrides", {}))
    tools = manifest.get("tools", [])
    status = manifest.get("status", "community")
    hive_block = manifest.get("hive", {})

    print(f"{server['name']}")
    print("=" * 50)

    # Core info
    print(f"  Source:     {server.get('source', '')}")
    print(f"  Transport:  {server.get('transport', '')}")
    print(f"  Version:    {server.get('manifest_version', 'unknown')}")
    print(f"  Trust tier: {status}")
    print(f"  Enabled:    {'yes' if server.get('enabled', True) else 'no'}")

    # Description
    desc = manifest.get("description", "")
    if desc:
        print(f"  Description: {desc}")

    # Health
    health = server.get("last_health_status")
    if health:
        health_sym = {"healthy": "✓", "unhealthy": "✗"}.get(health, "●")
        print(f"  Health:     {health_sym} {health}")
        last_check = server.get("last_health_check_at")
        if last_check:
            print(f"  Last check: {last_check}")
    last_error = server.get("last_error")
    if last_error:
        print(f"  Last error: {last_error}")

    # Tools
    if tools:
        print(f"\n  Tools ({len(tools)}):")
        for tool in tools:
            if isinstance(tool, dict):
                tool_name = tool.get("name", "")
                tool_desc = tool.get("description", "")
                print(f"    • {tool_name}: {tool_desc}" if tool_desc else f"    • {tool_name}")
            else:
                print(f"    • {tool}")

    # Overrides
    env_overrides = overrides.get("env", {})
    header_overrides = overrides.get("headers", {})
    if env_overrides or header_overrides:
        print("\n  Overrides:")
        for key in env_overrides:
            print(f"    env.{key} = <set>")
        for key in header_overrides:
            print(f"    header.{key} = <set>")

    # Hive block
    if hive_block:
        profiles = hive_block.get("profiles", [])
        if profiles:
            print(f"\n  Profiles: {', '.join(profiles)}")
        min_ver = hive_block.get("min_version")
        if min_ver:
            print(f"  Min Hive version: {min_ver}")

    # Agent usage
    if agents:
        print("\n  Used by agents:")
        for agent in agents:
            print(f"    • {agent}")

    # Timestamps
    print(f"\n  Installed:  {server.get('installed_at', 'unknown')}")
    print(f"  Installed by: {server.get('installed_by', 'unknown')}")

    return 0


def cmd_mcp_config(args) -> int:
    """Set env or header overrides for a server."""
    registry = _get_registry()

    if not args.set_env and not args.set_header:
        # Show current config
        server = registry.get_server(args.name)
        if server is None:
            print(
                f"Error: server '{args.name}' is not installed.\n"
                f"Run 'hive mcp list' to see installed servers.",
                file=sys.stderr,
            )
            return 1
        masked = _mask_overrides(server.get("overrides", {}))
        env_o = masked.get("env", {})
        header_o = masked.get("headers", {})
        if not env_o and not header_o:
            print(f"No overrides set for {args.name}.")
            print(f"Set one with: hive mcp config {args.name} --set KEY=VALUE")
        else:
            print(f"Overrides for {args.name}:")
            for key in env_o:
                print(f"  env.{key} = <set>")
            for key in header_o:
                print(f"  header.{key} = <set>")
        return 0

    try:
        if args.set_env:
            pairs = _parse_key_value_pairs(args.set_env)
            for key, value in pairs.items():
                registry.set_override(args.name, key, value, override_type="env")
            print(f"✓ Set {len(pairs)} env override(s) for {args.name}")

        if args.set_header:
            pairs = _parse_key_value_pairs(args.set_header)
            for key, value in pairs.items():
                registry.set_override(args.name, key, value, override_type="headers")
            print(f"✓ Set {len(pairs)} header override(s) for {args.name}")

    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


# ── P1 command handlers ────────────────────────────────────────────


def cmd_mcp_search(args) -> int:
    """Search the registry index."""
    registry = _get_registry()
    if not _ensure_index_available(registry):
        return 1

    results = registry.search(args.query)

    if args.output_json:
        _emit_json(results)
        return 0

    if not results:
        print(f"No servers matching '{args.query}'.")
        return 0

    print(f"Found {len(results)} server(s) matching '{args.query}':\n")
    _render_available_table(results)
    return 0


def cmd_mcp_health(args) -> int:
    """Check server health."""
    registry = _get_registry()

    try:
        results = registry.health_check(name=args.name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Single server returns a flat dict, all-servers returns name->dict
    if args.name:
        results = {args.name: results}

    if args.output_json:
        _emit_json(results)
        return 0

    for name, result in results.items():
        status = result.get("status", "unknown")
        tools = result.get("tools", 0)
        error = result.get("error")
        sym = {"healthy": "✓", "unhealthy": "✗"}.get(status, "●")

        print(f"  {sym} {name}: {status}", end="")
        if status == "healthy" and tools:
            print(f" ({tools} tools)")
        elif error:
            print(f"\n    Error: {error}")
        else:
            print()

    return 0


def cmd_mcp_update(args) -> int:
    """Update a single server, or refresh the index and update all registry servers."""
    registry = _get_registry()

    if args.name:
        return _cmd_mcp_update_server(args.name, registry)

    # Step 1: refresh the registry index
    try:
        count = registry.update_index()
    except Exception as exc:
        print(
            f"Error: failed to update registry index: {exc}\n"
            f"Check your network connection and try again.",
            file=sys.stderr,
        )
        return 1

    print(f"✓ Registry index updated ({count} servers available)")

    # Step 2: update all installed registry servers (skip local/pinned)
    installed = registry.list_installed()
    registry_servers = [
        s for s in installed if s.get("source") == "registry" and not s.get("pinned")
    ]

    if not registry_servers:
        return 0

    print(f"\nUpdating {len(registry_servers)} installed server(s)...")
    errors = 0
    for server in registry_servers:
        name = server["name"]
        rc = _cmd_mcp_update_server(name, registry)
        if rc != 0:
            errors += 1

    return 1 if errors else 0


def _cmd_mcp_update_server(name: str, registry=None) -> int:
    """Bridge: reinstall a server from the latest index.

    This is a temporary bridge until #6355 adds proper version diffing,
    tool-signature change detection, and --dry-run support.
    """
    if registry is None:
        registry = _get_registry()

    server = registry.get_server(name)
    if server is None:
        print(
            f"Error: server '{name}' is not installed.\n"
            f"Run 'hive mcp install {name}' to install it.",
            file=sys.stderr,
        )
        return 1

    if server.get("source") != "registry":
        print(
            f"Error: '{name}' is a local server and cannot be updated from the registry.\n"
            f"Use 'hive mcp remove {name}' and 'hive mcp add' to re-register it.",
            file=sys.stderr,
        )
        return 1

    if server.get("pinned"):
        print(
            f"Error: '{name}' is pinned to v{server.get('manifest_version', '?')}.\n"
            f"To update a pinned server, remove and reinstall:\n"
            f"  hive mcp remove {name} && hive mcp install {name}",
            file=sys.stderr,
        )
        return 1

    # Refresh index, then reinstall
    if not _ensure_index_available(registry):
        return 1

    old_version = server.get("manifest_version", "unknown")
    transport = server.get("transport")
    overrides = server.get("overrides", {})
    was_enabled = server.get("enabled", True)

    # Save the full entry before removing so we can restore on failure
    saved_entry = dict(server)
    saved_entry.pop("name", None)

    try:
        registry.remove(name)
        entry = registry.install(name, transport=transport)
    except ValueError as exc:
        # Restore the original entry so update doesn't become an uninstall
        data = registry._read_installed()
        data["servers"][name] = saved_entry
        registry._write_installed(data)
        print(
            f"Error: {exc}\nServer '{name}' has been restored to its previous state.",
            file=sys.stderr,
        )
        return 1

    new_version = entry.get("manifest_version", "unknown")

    # Restore prior state from the previous installation
    for key, value in overrides.get("env", {}).items():
        registry.set_override(name, key, value, override_type="env")
    for key, value in overrides.get("headers", {}).items():
        registry.set_override(name, key, value, override_type="headers")
    if not was_enabled:
        registry.disable(name)

    if old_version == new_version:
        print(f"✓ {name} is already at v{new_version}")
    else:
        print(f"✓ Updated {name}: v{old_version} → v{new_version}")

    return 0


# ── Contributor tooling command handlers ──────────────────────────


def cmd_mcp_validate(args) -> int:
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


def cmd_mcp_init(args) -> int:
    """Scaffold a new MCP server manifest."""
    import httpx

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


def cmd_mcp_test(args) -> int:
    """Test an MCP server against its manifest."""
    from framework.runner.mcp_client import MCPClient, MCPServerConfig
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
                import httpx

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
