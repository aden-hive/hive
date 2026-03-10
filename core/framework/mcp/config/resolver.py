"""Config resolution helpers for MCP server entries."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def resolve_stdio_server_config(
    server_config: dict[str, Any], base_dir: Path
) -> dict[str, Any]:
    """Resolve cwd/script paths for stdio MCP configs (Windows-safe)."""
    config = dict(server_config)
    if config.get("transport") != "stdio":
        return config

    cwd = config.get("cwd")
    args = list(config.get("args", []))
    if not cwd and not args:
        return config

    resolved_cwd: Path | None = None
    if cwd:
        if Path(cwd).is_absolute():
            resolved_cwd = Path(cwd)
        else:
            resolved_cwd = (base_dir / cwd).resolve()

    script_name = None
    script_idx = -1
    for i, arg in enumerate(args):
        if isinstance(arg, str) and arg.endswith(".py"):
            script_name = arg
            script_idx = i
            break

    if resolved_cwd is None:
        return config

    tools_fallback = Path.cwd() / "tools"
    need_fallback = not resolved_cwd.is_dir()
    if script_name and not need_fallback:
        need_fallback = not (resolved_cwd / script_name).exists()
    if need_fallback:
        fallback_ok = tools_fallback.is_dir()
        if script_name:
            fallback_ok = fallback_ok and (tools_fallback / script_name).exists()
        if fallback_ok:
            resolved_cwd = tools_fallback
        else:
            config["cwd"] = str(resolved_cwd)
            return config

    if not script_name:
        config["cwd"] = str(resolved_cwd)
        return config

    if "coder_tools" in script_name:
        project_root = str(resolved_cwd.parent.resolve())
        args = list(args)
        if "--project-root" not in args:
            args.extend(["--project-root", project_root])
        config["args"] = args

    if os.name == "nt":
        config["cwd"] = None
        abs_script = str((resolved_cwd / script_name).resolve())
        args = list(config["args"])
        args[script_idx] = abs_script
        config["args"] = args
    else:
        config["cwd"] = str(resolved_cwd)

    return config
