from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_INDEX_PATH = Path.home() / ".hive" / "mcp_registry" / "cache" / "registry_index.json"
_FIXTURE_INDEX_PATH = Path(__file__).resolve().parent / "fixtures" / "registry_index.json"


def resolve_registry_servers(
    *,
    include: list[str] | None = None,
    tags: list[str] | None = None,
    exclude: list[str] | None = None,
    profile: str | None = None,
    max_tools: int | None = None,
    versions: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Resolve registry-sourced MCP servers for `mcp_registry.json` selection.

    This function is written to be mock-friendly during early development:
    - If the real `MCPRegistry` core module is present, delegate to it.
    - Otherwise, fall back to a cached local index (`~/.hive/.../registry_index.json`)
      and then to the repo fixture index.
    """

    # `max_tools` is enforced by ToolRegistry. We keep it in the resolver
    # signature to match the PRD and future MCPRegistry interfaces.
    _ = max_tools

    try:
        from framework.runner.mcp_registry import MCPRegistry  # type: ignore

        registry = MCPRegistry()
        resolved = registry.resolve_for_agent(
            include=include or [],
            tags=tags or [],
            exclude=exclude or [],
            profile=profile,
            max_tools=max_tools,
            versions=versions or {},
        )
        # Future-proof: normalize both dicts and typed objects to dicts.
        return [_normalize_server_config(x) for x in resolved]
    except ImportError:
        # Expected while #6349/#6574 is not merged locally.
        pass
    except Exception as e:
        logger.warning("MCPRegistry resolution failed; falling back to cache/fixtures: %s", e)

    return _resolve_from_local_index(
        include=include,
        tags=tags,
        exclude=exclude,
        profile=profile,
        versions=versions or {},
    )


def _resolve_from_local_index(
    *,
    include: list[str] | None,
    tags: list[str] | None,
    exclude: list[str] | None,
    profile: str | None,
    versions: dict[str, str],
) -> list[dict[str, Any]]:
    index = _load_index_json()
    servers = _coerce_index_servers(index)
    servers_by_name: dict[str, dict[str, Any]] = {
        s["name"]: s for s in servers if isinstance(s, dict) and "name" in s
    }

    include_list = include or []
    tags_list = tags or []
    exclude_set = set(exclude or [])

    def _profiles_of(entry: dict[str, Any]) -> set[str]:
        if isinstance(entry.get("profiles"), list):
            return set(entry["profiles"])
        hive = entry.get("hive")
        if isinstance(hive, dict) and isinstance(hive.get("profiles"), list):
            return set(hive["profiles"])
        return set()

    def _tags_of(entry: dict[str, Any]) -> set[str]:
        if isinstance(entry.get("tags"), list):
            return set(entry["tags"])
        return set()

    def _entry_version(entry: dict[str, Any]) -> str | None:
        # Prefer flat `version`, but support a few common shapes.
        v = entry.get("version")
        if isinstance(v, str):
            return v
        v2 = entry.get("manifest_version")
        if isinstance(v2, str):
            return v2
        hive = entry.get("manifest")
        if isinstance(hive, dict) and isinstance(hive.get("version"), str):
            return hive["version"]
        return None

    def _version_allows(server_name: str) -> bool:
        if server_name not in versions:
            return True
        pinned = versions[server_name]
        entry = servers_by_name.get(server_name)
        if not entry:
            return False
        return _entry_version(entry) == pinned

    resolved_names: list[str] = []
    resolved_set: set[str] = set()

    # 1) Include-order first
    for name in include_list:
        if name in exclude_set:
            continue
        if name in servers_by_name and _version_allows(name) and name not in resolved_set:
            resolved_names.append(name)
            resolved_set.add(name)

    # 2) Then tag/profile matches, alphabetical
    profile_candidates = set()
    if profile:
        for name, entry in servers_by_name.items():
            if name in exclude_set or not _version_allows(name):
                continue
            if profile in _profiles_of(entry):
                profile_candidates.add(name)

    tag_candidates = set()
    if tags_list:
        tags_set = set(tags_list)
        for name, entry in servers_by_name.items():
            if name in exclude_set or not _version_allows(name):
                continue
            if _tags_of(entry).intersection(tags_set):
                tag_candidates.add(name)

    tag_profile_names = sorted((profile_candidates | tag_candidates) - resolved_set)
    resolved_names.extend(tag_profile_names)

    # Missing requested servers should warn (FR-54).
    for name in include_list:
        if name in exclude_set:
            continue
        if name not in resolved_set:
            if name not in servers_by_name:
                logger.warning(
                    "Server '%s' requested by mcp_registry.json but not found in index. "
                    "Run: hive mcp install %s",
                    name,
                    name,
                )
            elif name in versions:
                logger.warning(
                    "Server '%s' was requested but pinned version '%s' was not found in index. "
                    "Run: hive mcp update %s or change the pin in mcp_registry.json",
                    name,
                    versions[name],
                    name,
                )
            else:
                logger.warning(
                    "Server '%s' requested by mcp_registry.json was not selected. "
                    "Check selection filters/exclude lists.",
                    name,
                )

    resolved_configs: list[dict[str, Any]] = []
    repo_root = Path(__file__).resolve().parents[3]
    for name in resolved_names:
        entry = servers_by_name.get(name)
        if not entry:
            continue
        config = entry.get("mcp_config")
        if not isinstance(config, dict):
            # Best-effort: allow a direct MCP config shape at top-level.
            config = {
                k: v
                for k, v in entry.items()
                if k
                in {
                    "name",
                    "transport",
                    "command",
                    "args",
                    "env",
                    "cwd",
                    "url",
                    "headers",
                    "description",
                }
            }
        mcp_config = dict(config)
        mcp_config["name"] = name
        if mcp_config.get("transport") == "stdio":
            _absolutize_stdio_config_in_place(repo_root, mcp_config)
        resolved_configs.append(mcp_config)

    return resolved_configs


def _load_index_json() -> Any:
    if _CACHE_INDEX_PATH.exists():
        return json.loads(_CACHE_INDEX_PATH.read_text(encoding="utf-8"))
    if _FIXTURE_INDEX_PATH.exists():
        logger.info("Using local fixture index because registry cache is missing")
        return json.loads(_FIXTURE_INDEX_PATH.read_text(encoding="utf-8"))
    logger.warning("No local MCP registry index found (cache and fixture missing)")
    return {"servers": []}


def _coerce_index_servers(index: Any) -> list[dict[str, Any]]:
    if isinstance(index, list):
        return [x for x in index if isinstance(x, dict)]
    if isinstance(index, dict):
        servers = index.get("servers", [])
        if isinstance(servers, list):
            return [x for x in servers if isinstance(x, dict)]
    return []


def _normalize_server_config(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)

    # Future-proof object-to-dict normalization.
    for attr in ("to_dict", "model_dump"):
        maybe = getattr(raw, attr, None)
        if callable(maybe):
            return dict(maybe())

    return dict(getattr(raw, "__dict__", {}))


def _absolutize_stdio_config_in_place(repo_root: Path, config: dict[str, Any]) -> None:
    cwd = config.get("cwd")
    if isinstance(cwd, str) and not Path(cwd).is_absolute():
        config["cwd"] = str((repo_root / cwd).resolve())

    # We intentionally do not absolutize `args` here.
    # For stdio servers, arguments may include the script name relative to
    # `cwd` (e.g. "coder_tools_server.py" with cwd="tools"). ToolRegistry's
    # stdio resolution logic handles script path checks and platform quirks.
