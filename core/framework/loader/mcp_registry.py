"""MCP Server Registry: local state management for installed MCP servers."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import tomllib
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

import httpx

from framework.loader.mcp_client import MCPClient, MCPServerConfig
from framework.loader.mcp_connection_manager import MCPConnectionManager
from framework.loader.mcp_errors import (
    MCPError,
    MCPErrorCode,
    MCPInstallError,
)

logger = logging.getLogger(__name__)

DEFAULT_INDEX_URL = (
    "https://raw.githubusercontent.com/aden-hive/hive-mcp-registry/main/registry_index.json"
)
DEFAULT_REFRESH_INTERVAL_HOURS = 24
_LAST_FETCHED_FILENAME = "last_fetched"
_LEGACY_LAST_FETCHED_FILENAME = "last_fetched.json"

_DEFAULT_CONFIG = {
    "index_url": DEFAULT_INDEX_URL,
    "refresh_interval_hours": DEFAULT_REFRESH_INTERVAL_HOURS,
}

# Default local MCP servers that ship with Hive. Seeded on first startup so
# fresh users get working file I/O, browser automation, and the hive tool
# suite without having to run `hive mcp add` manually. ``cwd`` is filled in
# at registration time with the absolute path to the ``tools/`` directory.
_DEFAULT_LOCAL_SERVERS: dict[str, dict[str, Any]] = {
    "hive_tools": {
        "description": "Hive tools: web search, email, CRM, calendar, and 100+ integrations",
        "args": ["run", "python", "mcp_server.py", "--stdio"],
    },
    "gcu-tools": {
        "description": "Browser automation: click, type, navigate, screenshot, snapshot",
        "args": ["run", "python", "-m", "gcu.server", "--stdio"],
    },
    "files-tools": {
        "description": "File I/O: read, write, edit, search, list, run commands",
        "args": ["run", "python", "files_server.py", "--stdio"],
    },
}

# Aliases that earlier versions of ensure_defaults wrote under the wrong name.
# When we see one of these stale entries, drop it before seeding the canonical
# name so the active agents (queen, credential_tester) can find their tools.
_STALE_DEFAULT_ALIASES: dict[str, str] = {
    "hive_tools": "hive-tools",
}


class MCPRegistry:
    """Manages local MCP server state in ~/.hive/mcp_registry/."""

    def __init__(self, base_path: Path | None = None):
        self._base = base_path or Path.home() / ".hive" / "mcp_registry"
        self._installed_path = self._base / "installed.json"
        self._config_path = self._base / "config.json"
        self._cache_dir = self._base / "cache"

    # ── Initialization ──────────────────────────────────────────────

    def initialize(self) -> None:
        """Create directory structure and default files if missing."""
        self._base.mkdir(parents=True, exist_ok=True)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        if not self._config_path.exists():
            self._write_json(self._config_path, _DEFAULT_CONFIG)

        if not self._installed_path.exists():
            self._write_json(self._installed_path, {"servers": {}})

    def ensure_defaults(self) -> list[str]:
        """Seed the built-in local MCP servers (hive-tools, gcu-tools, files-tools).

        Idempotent — servers already present are left untouched. Skips seeding
        entirely when the source-tree ``tools/`` directory cannot be located
        (e.g. when Hive is installed from a wheel rather than a checkout).

        Returns the list of names that were newly registered.
        """
        self.initialize()

        # parents: [0]=loader, [1]=framework, [2]=core, [3]=repo root
        tools_dir = Path(__file__).resolve().parents[3] / "tools"
        if not tools_dir.is_dir():
            logger.debug(
                "MCPRegistry.ensure_defaults: tools dir %s missing; skipping default seed",
                tools_dir,
            )
            return []

        cwd = str(tools_dir)
        data = self._read_installed()
        existing = data.get("servers", {})
        added: list[str] = []

        # Drop stale aliases (from earlier versions that wrote the wrong name).
        # Only remove the alias when the canonical name isn't already installed,
        # so we never clobber a hand-edited entry the user cares about.
        mutated = False
        for canonical, stale in _STALE_DEFAULT_ALIASES.items():
            if stale in existing and canonical not in existing:
                logger.info(
                    "MCPRegistry.ensure_defaults: removing stale alias '%s' (canonical: '%s')",
                    stale,
                    canonical,
                )
                del existing[stale]
                mutated = True
        if mutated:
            self._write_installed(data)

        for name, spec in _DEFAULT_LOCAL_SERVERS.items():
            if name in existing:
                continue
            try:
                self.add_local(
                    name=name,
                    transport="stdio",
                    command="uv",
                    args=list(spec["args"]),
                    cwd=cwd,
                    description=spec["description"],
                )
                added.append(name)
            except MCPError as exc:
                logger.warning(
                    "MCPRegistry.ensure_defaults: failed to seed '%s': %s", name, exc
                )

        if added:
            logger.info("MCPRegistry: seeded default local servers: %s", added)
        return added

    # ── Internal I/O ────────────────────────────────────────────────

    def _read_installed(self) -> dict:
        """Read installed.json, initializing if needed."""
        if not self._installed_path.exists():
            self.initialize()
        return json.loads(self._installed_path.read_text(encoding="utf-8"))

    def _write_installed(self, data: dict) -> None:
        """Write installed.json."""
        self._write_json(self._installed_path, data)

    def _read_config(self) -> dict:
        """Read config.json."""
        if not self._config_path.exists():
            self.initialize()
        return json.loads(self._config_path.read_text(encoding="utf-8"))

    def _read_cached_index(self) -> dict:
        """Read cached registry_index.json."""
        index_path = self._cache_dir / "registry_index.json"
        if not index_path.exists():
            return {"servers": {}}
        return json.loads(index_path.read_text(encoding="utf-8"))

    def _get_effective_manifest(
        self,
        name: str,
        entry: dict,
        cached_index: dict | None = None,
    ) -> dict:
        """Return the manifest currently in effect for an installed entry."""
        manifest = entry.get("manifest", {})
        if entry.get("source") != "registry":
            return manifest

        index = cached_index or self._read_cached_index()
        cached_manifest = index.get("servers", {}).get(name)
        if cached_manifest is not None:
            return cached_manifest

        # Fall back to persisted manifest data when the cache is unavailable.
        if isinstance(manifest, dict) and manifest:
            return manifest
        return {}

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        """Write JSON to file atomically (write to temp, fsync, rename)."""
        content = json.dumps(data, indent=2) + "\n"
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ── add_local ───────────────────────────────────────────────────

    def add_local(
        self,
        name: str,
        transport: str | None = None,
        manifest: dict | None = None,
        url: str | None = None,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        cwd: str | None = None,
        socket_path: str | None = None,
        description: str = "",
    ) -> dict:
        """Register a local/running MCP server.

        Can be called with an inline manifest dict, or with individual
        transport/url/command params that build a manifest automatically.
        """
        data = self._read_installed()
        if name in data["servers"]:
            raise MCPError(
                code=MCPErrorCode.MCP_INSTALL_FAILED,
                what=f"Server '{name}' already exists",
                why="A server with this name is already registered locally.",
                fix=f"Run: hive mcp remove {name}  — then add it again.",
            )

        if manifest is not None:
            # Inline manifest provided directly
            manifest = {**manifest, "name": name}
            transport_config = manifest.get("transport", {})
            transport = transport or transport_config.get("default", "stdio")
            if "transport" not in manifest:
                manifest["transport"] = {"supported": [transport], "default": transport}
        else:
            # Build manifest from individual params
            if not transport:
                raise MCPError(
                    code=MCPErrorCode.MCP_INSTALL_FAILED,
                    what=f"Cannot register server '{name}'",
                    why="transport is required when manifest is not provided.",
                    fix="Pass --transport stdio|http|unix|sse when using hive mcp add.",
                )
            manifest = {
                "name": name,
                "description": description,
                "transport": {"supported": [transport], "default": transport},
            }
            match transport:
                case "http":
                    if not url:
                        raise MCPError(
                            code=MCPErrorCode.MCP_INSTALL_FAILED,
                            what=f"Cannot register server '{name}' with http transport",
                            why="url is required for http transport.",
                            fix="Pass --url https://your-server to hive mcp add.",
                        )
                    manifest["http"] = {"url": url, "headers": headers or {}}
                case "stdio":
                    if not command:
                        raise MCPError(
                            code=MCPErrorCode.MCP_INSTALL_FAILED,
                            what=f"Cannot register server '{name}' with stdio transport",
                            why="command is required for stdio transport.",
                            fix="Pass --command <executable> to hive mcp add.",
                        )
                    manifest["stdio"] = {
                        "command": command,
                        "args": args or [],
                        "env": env or {},
                        "cwd": cwd,
                    }
                case "unix":
                    if not socket_path:
                        raise MCPError(
                            code=MCPErrorCode.MCP_INSTALL_FAILED,
                            what=f"Cannot register server '{name}' with unix transport",
                            why="socket_path is required for unix transport.",
                            fix="Pass --socket-path /path/to/socket to hive mcp add.",
                        )
                    manifest["unix"] = {"socket_path": socket_path}
                    manifest["http"] = {"url": url or "http://localhost"}
                case "sse":
                    if not url:
                        raise MCPError(
                            code=MCPErrorCode.MCP_INSTALL_FAILED,
                            what=f"Cannot register server '{name}' with sse transport",
                            why="url is required for sse transport.",
                            fix="Pass --url https://your-server to hive mcp add.",
                        )
                    manifest["sse"] = {"url": url}
                case _:
                    raise MCPError(
                        code=MCPErrorCode.MCP_INSTALL_FAILED,
                        what=f"Cannot register server '{name}'",
                        why=f"Unsupported transport: '{transport}'.",
                        fix="Use one of: stdio, http, unix, sse.",
                    )

        entry = self._make_entry(
            source="local",
            manifest=manifest,
            transport=transport,
            installed_by="hive mcp add",
        )

        data["servers"][name] = entry
        self._write_installed(data)
        logger.info("Registered local MCP server '%s' (%s)", name, transport)
        return entry

    # ── install ─────────────────────────────────────────────────────

    def install(self, name: str, transport: str | None = None, version: str | None = None) -> dict:
        """Install a server from the cached remote registry index."""
        data = self._read_installed()
        if name in data["servers"]:
            raise MCPInstallError(
                server=name,
                why=f"Server '{name}' already exists in the registry.",
                fix=f"Run: hive mcp remove {name}  — then install again.",
            )

        index = self._read_cached_index()
        manifest = index.get("servers", {}).get(name)
        if manifest is None:
            raise MCPInstallError(
                server=name,
                why=f"Server '{name}' not found in registry index.",
                fix="Run: hive mcp update  — then try again.",
            )

        # Validate version if specified
        if version is not None:
            index_version = manifest.get("version")
            if index_version is None:
                raise MCPError(
                    code=MCPErrorCode.MCP_VERSION_CONFLICT,
                    what=f"Cannot pin version for '{name}'",
                    why="The registry manifest has no version field.",
                    fix="Run: hive mcp update  — then omit --version to use latest.",
                )
            if index_version != version:
                raise MCPError(
                    code=MCPErrorCode.MCP_VERSION_CONFLICT,
                    what=f"Version mismatch for '{name}'",
                    why=f"Requested {version} but index has {index_version}.",
                    fix="Run: hive mcp update  — or omit --version to use latest.",
                )

        transport_config = manifest.get("transport", {})
        supported = transport_config.get("supported", [])
        if transport is not None:
            if supported and transport not in supported:
                raise MCPError(
                    code=MCPErrorCode.MCP_INSTALL_FAILED,
                    what=f"Transport '{transport}' not supported by '{name}'",
                    why=f"Server supports: {supported}.",
                    fix=f"Use one of the supported transports: {supported}.",
                )
            resolved_transport = transport
        else:
            resolved_transport = transport_config.get("default", "stdio")

        entry = self._make_entry(
            source="registry",
            manifest=self._make_registry_manifest_snapshot(name, manifest),
            transport=resolved_transport,
            installed_by="hive mcp install",
            pinned=version is not None,
            auto_update=version is None,
            resolved_package_version=manifest.get("version"),
        )

        data["servers"][name] = entry
        self._write_installed(data)
        logger.info(
            "Installed MCP server '%s' v%s from registry",
            name,
            entry["manifest_version"],
        )
        return entry

    # ── remove / enable / disable ───────────────────────────────────

    def remove(self, name: str) -> None:
        """Remove a server from the registry."""
        data = self._read_installed()
        if name not in data["servers"]:
            raise MCPError(
                code=MCPErrorCode.MCP_INSTALL_FAILED,
                what=f"Cannot remove server '{name}'",
                why="Server is not installed.",
                fix="Run: hive mcp list  — to see installed servers.",
            )
        del data["servers"][name]
        self._write_installed(data)
        logger.info("Removed MCP server '%s'", name)

    def enable(self, name: str) -> None:
        """Enable a disabled server."""
        self._set_enabled(name, enabled=True)

    def disable(self, name: str) -> None:
        """Disable a server without removing it."""
        self._set_enabled(name, enabled=False)

    def _set_enabled(self, name: str, *, enabled: bool) -> None:
        data = self._read_installed()
        if name not in data["servers"]:
            raise MCPError(
                code=MCPErrorCode.MCP_INSTALL_FAILED,
                what=f"Cannot {'enable' if enabled else 'disable'} server '{name}'",
                why="Server is not installed.",
                fix="Run: hive mcp list  — to see installed servers.",
            )
        data["servers"][name]["enabled"] = enabled
        self._write_installed(data)
        logger.info("%s MCP server '%s'", "Enabled" if enabled else "Disabled", name)

    # ── list / get ──────────────────────────────────────────────────

    def list_installed(self) -> list[dict]:
        """Return all installed servers as a list of dicts with name included."""
        data = self._read_installed()
        return [{"name": name, **entry} for name, entry in data["servers"].items()]

    def get_server(self, name: str) -> dict | None:
        """Get a single installed server entry by name, or None if not found."""
        data = self._read_installed()
        entry = data["servers"].get(name)
        if entry is None:
            return None
        return {"name": name, **entry}

    def list_available(self) -> list[dict]:
        """List all servers from cached remote index."""
        index = self._read_cached_index()
        return [{"name": name, **m} for name, m in index.get("servers", {}).items()]

    # ── set_override ────────────────────────────────────────────────

    def set_override(
        self,
        name: str,
        key: str,
        value: str,
        override_type: Literal["env", "headers"] = "env",
    ) -> None:
        """Set an env or header override for a server."""
        data = self._read_installed()
        if name not in data["servers"]:
            raise MCPError(
                code=MCPErrorCode.MCP_INSTALL_FAILED,
                what=f"Cannot set override for server '{name}'",
                why="Server is not installed.",
                fix="Run: hive mcp list  — to see installed servers.",
            )
        if override_type not in ("env", "headers"):
            raise MCPError(
                code=MCPErrorCode.MCP_INSTALL_FAILED,
                what=f"Invalid override type '{override_type}' for server '{name}'",
                why="Override type must be 'env' or 'headers'.",
                fix="Use --type env or --type headers.",
            )
        data["servers"][name]["overrides"][override_type][key] = value
        self._write_installed(data)
        logger.info("Set %s override %s for MCP server '%s'", override_type, key, name)

    # ── search ──────────────────────────────────────────────────────

    def search(self, query: str) -> list[dict]:
        """Search registry index by name, tag, description, or tool name."""
        query_lower = query.lower()
        index = self._read_cached_index()
        matches = []

        for name, manifest in index.get("servers", {}).items():
            if self._matches_query(name, manifest, query_lower):
                matches.append({"name": name, **manifest})

        return matches

    @staticmethod
    def _matches_query(name: str, manifest: dict, query: str) -> bool:
        """Check if a manifest matches a search query."""
        if query in name.lower():
            return True

        description = manifest.get("description", "")
        if query in description.lower():
            return True

        for tag in manifest.get("tags", []):
            if query in tag.lower():
                return True

        for tool in manifest.get("tools", []):
            tool_name = tool.get("name", "") if isinstance(tool, dict) else str(tool)
            if query in tool_name.lower():
                return True

        return False

    # ── update_index ────────────────────────────────────────────────

    def is_index_stale(self) -> bool:
        """Check if the cached registry index needs refreshing."""
        last_fetched_path = self._cache_dir / _LAST_FETCHED_FILENAME
        legacy_path = self._cache_dir / _LEGACY_LAST_FETCHED_FILENAME
        if not last_fetched_path.exists() and not legacy_path.exists():
            return True

        try:
            path = last_fetched_path if last_fetched_path.exists() else legacy_path
            data = json.loads(path.read_text(encoding="utf-8"))
            last_fetched = datetime.fromisoformat(data["timestamp"])
            config = self._read_config()
            interval_hours = config.get("refresh_interval_hours", DEFAULT_REFRESH_INTERVAL_HOURS)
            age_hours = (datetime.now(UTC) - last_fetched).total_seconds() / 3600
            return age_hours >= interval_hours
        except (KeyError, ValueError, OSError):
            return True

    def update_index(self) -> int:
        """Fetch the latest registry index from remote and cache it.

        Returns the number of servers in the index.
        """
        config = self._read_config()
        url = config.get("index_url", DEFAULT_INDEX_URL)

        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        index = response.json()

        self._write_json(self._cache_dir / "registry_index.json", index)
        # Write last_fetched atomically too
        self._write_json(
            self._cache_dir / _LAST_FETCHED_FILENAME,
            {"timestamp": datetime.now(UTC).isoformat()},
        )

        server_count = len(index.get("servers", {}))
        logger.info("Updated registry index: %d servers available", server_count)
        return server_count

    # ── load_agent_selection ────────────────────────────────────────

    def load_agent_selection(self, agent_path: Path) -> tuple[list[dict[str, Any]], int | None]:
        """Load mcp_registry.json from an agent directory and resolve servers.

        Returns:
            (server_config_dicts, max_tools) for :meth:`ToolRegistry.load_registry_servers`.
            ``max_tools`` is ``None`` when omitted or invalid in JSON.
        """
        registry_json_path = agent_path / "mcp_registry.json"
        if not registry_json_path.exists():
            return [], None

        selection = json.loads(registry_json_path.read_text(encoding="utf-8"))

        # Validate types at the JSON boundary. Bad fields are dropped with a
        # warning so the agent still starts (graceful degradation).
        expected_types: dict[str, type] = {
            "include": list,
            "tags": list,
            "exclude": list,
            "profile": str,
            "max_tools": int,
            "versions": dict,
        }
        validated: dict[str, Any] = {}
        for field, expected in expected_types.items():
            value = selection.get(field)
            if value is None:
                continue
            if not isinstance(value, expected):
                logger.warning(
                    "mcp_registry.json: '%s' must be %s, got %s; ignoring",
                    field,
                    expected.__name__,
                    type(value).__name__,
                )
                continue
            validated[field] = value

        max_tools = validated.get("max_tools")
        configs = self.resolve_for_agent(
            include=validated.get("include"),
            tags=validated.get("tags"),
            exclude=validated.get("exclude"),
            profile=validated.get("profile"),
            max_tools=max_tools,
            versions=validated.get("versions"),
        )
        return [self._server_config_to_dict(c) for c in configs], max_tools

    # ── resolve_for_agent ───────────────────────────────────────────

    def resolve_for_agent(
        self,
        include: list[str] | None = None,
        tags: list[str] | None = None,
        exclude: list[str] | None = None,
        profile: str | None = None,
        max_tools: int | None = None,
        versions: dict[str, str] | None = None,
    ) -> list[MCPServerConfig]:
        """Resolve installed servers matching agent selection criteria.

        Selection precedence per PRD section 7.2:
        1. profile expands to server names (union with include + tags)
        2. include adds explicit servers
        3. tags adds servers whose tags overlap
        4. exclude removes (always wins)
        5. Load order: include-order first, then alphabetical for tag/profile matches

        Returns list of MCPServerConfig objects ready for ToolRegistry.
        """
        data = self._read_installed()
        servers = data.get("servers", {})
        cached_index = self._read_cached_index()
        exclude_set = set(exclude or [])

        # Phase 1: collect profile-matched servers (alphabetical)
        profile_matched: list[str] = []
        if profile:
            for name, entry in sorted(servers.items()):
                if name in exclude_set:
                    continue
                if profile == "all":
                    profile_matched.append(name)
                else:
                    manifest = self._get_effective_manifest(name, entry, cached_index)
                    profiles = manifest.get("hive", {}).get("profiles", [])
                    if profile in profiles:
                        profile_matched.append(name)

        # Phase 2: collect tag-matched servers (alphabetical)
        tag_matched: list[str] = []
        if tags:
            tag_set = set(tags)
            for name, entry in sorted(servers.items()):
                if name in exclude_set:
                    continue
                manifest = self._get_effective_manifest(name, entry, cached_index)
                server_tags = set(manifest.get("tags", []))
                if tag_set & server_tags:
                    tag_matched.append(name)

        # Phase 3: build final ordered list
        # include-order first, then alphabetical for profile/tag matches
        selected: list[str] = []
        seen: set[str] = set()

        for name in include or []:
            if name not in seen and name not in exclude_set:
                selected.append(name)
                seen.add(name)

        for name in profile_matched:
            if name not in seen:
                selected.append(name)
                seen.add(name)

        for name in tag_matched:
            if name not in seen:
                selected.append(name)
                seen.add(name)

        # Build configs, tracking aggregate tool count for max_tools cap (FR-56)
        configs: list[MCPServerConfig] = []
        total_tools = 0
        for name in selected:
            entry = servers.get(name)
            if entry is None:
                logger.warning(
                    "Server '%s' requested but not installed. Run: hive mcp install %s",
                    name,
                    name,
                )
                continue
            if not entry.get("enabled", True):
                continue

            manifest = self._get_effective_manifest(name, entry, cached_index)

            # Check version pin (VC-6)
            if versions and name in versions:
                installed_version = entry.get("manifest_version", "0.0.0")
                pinned_version = versions[name]
                if installed_version != pinned_version:
                    logger.warning(
                        "Server '%s' version mismatch: installed=%s, pinned=%s. "
                        "Run: hive mcp update %s",
                        name,
                        installed_version,
                        pinned_version,
                        name,
                    )
                    continue

            # Check tool count cap before adding (FR-56), using manifest tool list when present.
            # When ``tools`` is empty (e.g. ``add_local``), counts are unknown here—callers should
            # pass the same ``max_tools`` to ToolRegistry.load_registry_servers to cap registration.
            manifest_tools = manifest.get("tools", [])
            server_tool_count = len(manifest_tools)
            if max_tools is not None and server_tool_count == 0:
                logger.debug(
                    "Server '%s' has no tools list in manifest; max_tools enforced at registration",
                    name,
                )
            elif max_tools is not None and total_tools + server_tool_count > max_tools:
                logger.info(
                    "Skipping server '%s' (%d tools): would exceed max_tools=%d",
                    name,
                    server_tool_count,
                    max_tools,
                )
                continue

            config = self._manifest_to_server_config(
                name,
                manifest,
                entry.get("overrides", {}),
                transport_override=entry.get("transport"),
            )
            if config is not None:
                configs.append(config)
                total_tools += server_tool_count

        return configs

    def _manifest_to_server_config(
        self,
        name: str,
        manifest: dict,
        overrides: dict | None = None,
        transport_override: str | None = None,
    ) -> MCPServerConfig | None:
        """Convert a manifest and overrides to MCPServerConfig."""
        overrides = overrides or {}
        transport_config = manifest.get("transport", {})
        transport = transport_override or transport_config.get("default", "stdio")
        description = manifest.get("description", "")

        match transport:
            case "stdio":
                stdio_config = manifest.get("stdio", {})
                merged_env = {
                    **stdio_config.get("env", {}),
                    **overrides.get("env", {}),
                }
                return MCPServerConfig(
                    name=name,
                    transport="stdio",
                    command=stdio_config.get("command"),
                    args=stdio_config.get("args", []),
                    env=merged_env,
                    cwd=stdio_config.get("cwd"),
                    description=description,
                )
            case "http":
                http_config = manifest.get("http", {})
                url = http_config.get("url", "")
                merged_headers = {
                    **http_config.get("headers", {}),
                    **overrides.get("headers", {}),
                }
                return MCPServerConfig(
                    name=name,
                    transport="http",
                    url=url,
                    headers=merged_headers,
                    description=description,
                )
            case "unix":
                unix_config = manifest.get("unix", {})
                http_config = manifest.get("http", {})
                merged_headers = {
                    **http_config.get("headers", {}),
                    **overrides.get("headers", {}),
                }
                return MCPServerConfig(
                    name=name,
                    transport="unix",
                    socket_path=unix_config.get("socket_path"),
                    url=http_config.get("url") or "http://localhost",
                    headers=merged_headers,
                    description=description,
                )
            case "sse":
                sse_config = manifest.get("sse", {})
                merged_headers = {
                    **sse_config.get("headers", {}),
                    **overrides.get("headers", {}),
                }
                return MCPServerConfig(
                    name=name,
                    transport="sse",
                    url=sse_config.get("url", ""),
                    headers=merged_headers,
                    description=description,
                )
            case _:
                logger.warning(
                    "Unsupported transport '%s' for server '%s'",
                    transport,
                    name,
                )
                return None

    @staticmethod
    def _server_config_to_dict(config: MCPServerConfig) -> dict[str, Any]:
        """Convert MCPServerConfig to plain dict for ToolRegistry.register_mcp_server()."""
        return {
            "name": config.name,
            "transport": config.transport,
            "command": config.command,
            "args": config.args,
            "env": config.env,
            "cwd": config.cwd,
            "url": config.url,
            "headers": config.headers,
            "socket_path": config.socket_path,
            "description": config.description,
        }

    # ── run_health_check ────────────────────────────────────────────

    def health_check(self, name: str | None = None) -> dict | dict[str, dict]:
        """Check health of installed server(s). Updates telemetry fields.

        If name is None, checks all installed servers and returns
        a dict mapping server names to their health results.

        """
        if name is None:
            results = {}
            for server in self.list_installed():
                results[server["name"]] = self.health_check(server["name"])
            return results

        data = self._read_installed()
        if name not in data["servers"]:
            raise MCPError(
                code=MCPErrorCode.MCP_HEALTH_FAILED,
                what=f"Cannot health-check server '{name}'",
                why="Server is not installed.",
                fix="Run: hive mcp list  — to see installed servers.",
            )

        entry = data["servers"][name]
        manifest = self._get_effective_manifest(name, entry)
        config = self._manifest_to_server_config(
            name,
            manifest,
            entry.get("overrides", {}),
            transport_override=entry.get("transport"),
        )
        now = datetime.now(UTC).isoformat()

        result: dict[str, Any] = {
            "name": name,
            "status": "unknown",
            "tools": 0,
            "error": None,
        }

        if config is None:
            transport = entry.get("transport", "unknown")
            result["status"] = "unhealthy"
            result["error"] = f"Unsupported transport '{transport}'"
            entry["last_health_status"] = "unhealthy"
            entry["last_error"] = result["error"]
            entry["last_health_check_at"] = now
            self._write_installed(data)
            return result

        manager = MCPConnectionManager.get_instance()

        try:
            if manager.has_connection(name):
                is_healthy = manager.health_check(name)
                if not is_healthy:
                    raise MCPError(
                        code=MCPErrorCode.MCP_HEALTH_FAILED,
                        what=f"Health check failed for server '{name}'",
                        why="Shared MCP connection reported unhealthy.",
                        fix=f"Run: hive mcp doctor {name}  — for diagnostics.",
                    )
                pooled_client = manager.acquire(config)
                try:
                    tools = pooled_client.list_tools()
                finally:
                    manager.release(name)
            else:
                with MCPClient(config) as client:
                    tools = client.list_tools()

            result["status"] = "healthy"
            result["tools"] = len(tools)
            entry["last_health_status"] = "healthy"
            entry["last_error"] = None
            entry["last_validated_with_hive_version"] = self._get_hive_version()
        except Exception as exc:
            result["status"] = "unhealthy"
            result["error"] = str(exc)
            entry["last_health_status"] = "unhealthy"
            entry["last_error"] = str(exc)

        entry["last_health_check_at"] = now
        self._write_installed(data)
        return result

    def run_health_check(self, name: str | None = None) -> dict | dict[str, dict]:
        """Backward-compatible wrapper for the public health_check API."""
        return self.health_check(name)

    @staticmethod
    def _get_hive_version() -> str:
        """Get the current Hive version."""
        try:
            return version("framework")
        except PackageNotFoundError:
            project_toml = Path(__file__).resolve().parents[2] / "pyproject.toml"
            if not project_toml.exists():
                return "unknown"
            try:
                with project_toml.open("rb") as f:
                    data = tomllib.load(f)
                return data.get("project", {}).get("version", "unknown")
            except (tomllib.TOMLDecodeError, OSError):
                return "unknown"

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _make_entry(
        *,
        source: str,
        manifest: dict,
        transport: str,
        installed_by: str,
        pinned: bool = False,
        auto_update: bool = False,
        resolved_package_version: str | None = None,
    ) -> dict:
        """Build a standard installed server entry."""
        now = datetime.now(UTC).isoformat()
        return {
            "source": source,
            "manifest_version": manifest.get("version", "0.0.0"),
            "manifest": manifest,
            "installed_at": now,
            "installed_by": installed_by,
            "transport": transport,
            "enabled": True,
            "pinned": pinned,
            "auto_update": auto_update,
            "resolved_package_version": resolved_package_version,
            "overrides": {"env": {}, "headers": {}},
            "last_health_check_at": None,
            "last_health_status": None,
            "last_error": None,
            "last_used_at": None,
            "last_validated_with_hive_version": None,
        }

    @staticmethod
    def _make_registry_manifest_snapshot(name: str, manifest: dict) -> dict[str, Any]:
        """Persist a full manifest snapshot for registry-installed servers."""
        manifest_snapshot = dict(manifest)
        manifest_snapshot["name"] = name
        return manifest_snapshot
