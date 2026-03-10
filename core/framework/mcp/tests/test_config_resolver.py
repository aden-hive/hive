from __future__ import annotations

import os
from pathlib import Path

from framework.mcp.config.resolver import resolve_stdio_server_config


def test_non_stdio_config_unchanged(tmp_path: Path):
    config = {"name": "http-server", "transport": "http", "url": "https://example.com/mcp"}
    result = resolve_stdio_server_config(config, tmp_path)
    assert result == config


def test_resolve_stdio_relative_cwd_and_script(tmp_path: Path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "server.py").write_text("print('ok')", encoding="utf-8")

    config = {
        "name": "local-tools",
        "transport": "stdio",
        "cwd": "tools",
        "args": ["server.py"],
    }

    result = resolve_stdio_server_config(config, tmp_path)

    if os.name == "nt":
        assert result["cwd"] is None
        assert Path(result["args"][0]).is_absolute()
        assert result["args"][0].endswith("server.py")
    else:
        assert result["cwd"] == str(tools_dir.resolve())
        assert result["args"][0] == "server.py"


def test_resolve_stdio_injects_project_root_for_coder_tools(tmp_path: Path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "coder_tools_server.py").write_text("print('ok')", encoding="utf-8")

    config = {
        "name": "coder-tools",
        "transport": "stdio",
        "cwd": "tools",
        "args": ["coder_tools_server.py"],
    }

    result = resolve_stdio_server_config(config, tmp_path)

    assert "--project-root" in result["args"]
