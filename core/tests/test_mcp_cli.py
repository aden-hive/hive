"""MCP servers in CLI mode: run from the terminal through mcp2cli, never loaded as tools."""

from __future__ import annotations

import json
import os
import sys
import textwrap
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from framework.loader.mcp_cli import cli_servers_prompt, mcp2cli_invocation
from framework.loader.mcp_client import MCPServerConfig
from framework.loader.mcp_errors import MCPError
from framework.loader.mcp_registry import MCPRegistry
from framework.loader.mcp_registry_cli import cmd_mcp_add, cmd_mcp_run, register_mcp_commands

_ECHO_SERVER = textwrap.dedent(
    """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("echo")

    @mcp.tool()
    def shout(text: str) -> str:
        \"\"\"Say text louder.\"\"\"
        return text.upper()

    @mcp.tool()
    def getenv(name: str) -> str:
        \"\"\"An environment variable of this server, or <unset>.\"\"\"
        import os
        return os.environ.get(name, "<unset>")

    mcp.run()
    """
)


@pytest.fixture()
def registry(tmp_path):
    reg = MCPRegistry(base_path=tmp_path / "mcp_registry")
    reg.initialize()
    return reg


def _add(reg: MCPRegistry, name: str, mode: str = "tools") -> None:
    reg.add_local(name=name, transport="stdio", command="srv", args=[name], description=f"{name} things", mode=mode)


def test_a_cli_mode_server_is_never_loaded_as_tools(registry):
    _add(registry, "plain")
    _add(registry, "comfy", mode="cli")

    configs = registry.resolve_for_agent(include=["plain", "comfy"])

    assert [c.name for c in configs] == ["plain"]


def test_cli_servers_lists_the_enabled_servers_in_cli_mode(registry):
    _add(registry, "plain")
    _add(registry, "comfy", mode="cli")
    _add(registry, "paused", mode="cli")
    registry.disable("paused")
    registry.set_mode("plain", "cli")

    assert registry.cli_servers() == [
        {"name": "plain", "description": "plain things", "tool_count": None},
        {"name": "comfy", "description": "comfy things", "tool_count": None},
    ]


def test_setting_the_mode_of_an_unknown_server_is_refused(registry):
    with pytest.raises(MCPError, match="Cannot set the mode of server 'ghost'"):
        registry.set_mode("ghost", "cli")


def test_a_stdio_server_becomes_one_command_line_mcp2cli_splits_back():
    from mcp2cli import split_shell_command

    command = [sys.executable, "-m", "my server", "--from", "comfy-mcp", "comfy-cli>=1.14.0"]
    config = MCPServerConfig(name="s", transport="stdio", command=command[0], args=command[1:], env={"TOKEN": "t0p"}, cwd="/srv")

    argv, env, cwd = mcp2cli_invocation(config)

    assert argv[0] == "--mcp-stdio"
    assert split_shell_command(argv[1]) == command
    assert env == {"TOKEN": "t0p"}
    assert cwd == "/srv"
    assert "t0p" not in " ".join(argv)


def test_headers_reach_mcp2cli_through_the_environment():
    config = MCPServerConfig(name="s", transport="sse", url="https://mcp.example/sse", headers={"Authorization": "Bearer t0p"})

    argv, env, _ = mcp2cli_invocation(config)

    assert argv[:4] == ["--mcp", "https://mcp.example/sse", "--transport", "sse"]
    assert argv[4:6] == ["--auth-header", "Authorization:env:HIVE_MCP_HEADER_0"]
    assert env == {"HIVE_MCP_HEADER_0": "Bearer t0p"}
    assert "t0p" not in " ".join(argv)


def test_a_unix_socket_server_cant_run_from_the_terminal():
    config = MCPServerConfig(name="s", transport="unix", socket_path="/tmp/s.sock")

    with pytest.raises(MCPError, match="unix transport"):
        mcp2cli_invocation(config)


def test_the_prompt_names_each_server_and_how_to_run_it():
    block = cli_servers_prompt([{"name": "comfy", "description": "ComfyUI image generation", "tool_count": 39}])

    assert "- comfy: ComfyUI image generation (39 commands)" in block
    assert "hive mcp run <server> --list" in block
    assert cli_servers_prompt([]) == ""


def test_the_queen_prompt_carries_the_block():
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    state = QueenPhaseState(mcp_cli_prompt="Command-line MCP servers: comfy")

    assert "Command-line MCP servers: comfy" in state.get_static_prompt()


def test_hive_mcp_add_takes_a_command_after_double_dash(registry, monkeypatch):
    import argparse

    monkeypatch.setattr("framework.loader.mcp_registry_cli._get_registry", lambda base_path=None: registry)
    parser = argparse.ArgumentParser()
    register_mcp_commands(parser.add_subparsers())
    args = parser.parse_args(
        ["mcp", "add", "--name", "comfy", "--transport", "stdio", "--as-cli", "--env", "COMFYUI_URL=http://127.0.0.1:8000"]
        + ["--", "uvx", "--from", "comfy-mcp", "comfy-mcp"]
    )

    assert cmd_mcp_add(args) == 0
    entry = registry.get_server("comfy")
    assert entry["mode"] == "cli"
    assert entry["manifest"]["stdio"] == {
        "command": "uvx",
        "args": ["--from", "comfy-mcp", "comfy-mcp"],
        "env": {"COMFYUI_URL": "http://127.0.0.1:8000"},
        "cwd": None,
    }


def test_hive_mcp_run_calls_a_real_server(registry, tmp_path, monkeypatch, capfd):
    pytest.importorskip("mcp.server.fastmcp")
    script = tmp_path / "echo_server.py"
    script.write_text(_ECHO_SERVER, encoding="utf-8")
    registry.add_local(name="echo", transport="stdio", command=sys.executable, args=[str(script)], env={"ECHO_MOOD": "loud"}, mode="cli")
    monkeypatch.setattr("framework.loader.mcp_registry_cli._get_registry", lambda base_path=None: registry)
    before = (dict(os.environ), list(sys.argv), os.getcwd())

    listed = cmd_mcp_run(SimpleNamespace(name="echo", mcp2cli_args=["--list"]))
    listing = capfd.readouterr().out
    called = cmd_mcp_run(SimpleNamespace(name="echo", mcp2cli_args=["--json", "shout", "--text", "hello hive"]))
    result = json.loads(capfd.readouterr().out)
    cmd_mcp_run(SimpleNamespace(name="echo", mcp2cli_args=["--json", "getenv", "--name", "ECHO_MOOD"]))
    mood = json.loads(capfd.readouterr().out)

    assert listed == 0
    assert "shout" in listing
    assert called == 0
    assert result["content"][0]["text"] == "HELLO HIVE"
    assert mood["content"][0]["text"] == "loud"
    # mcp2cli runs in this process; it must leave the process as it found it.
    assert (dict(os.environ), list(sys.argv), os.getcwd()) == before


def test_hive_mcp_run_names_an_unknown_server(registry, monkeypatch, capsys):
    monkeypatch.setattr("framework.loader.mcp_registry_cli._get_registry", lambda base_path=None: registry)

    assert cmd_mcp_run(SimpleNamespace(name="ghost", mcp2cli_args=[])) == 1
    assert "no MCP server named 'ghost'" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_the_routes_add_a_server_in_cli_mode_and_switch_it():
    from framework.server.app import create_app

    body = {"name": "comfy", "transport": "stdio", "command": "uvx", "args": ["comfy-mcp"], "mode": "cli"}
    async with TestClient(TestServer(create_app())) as client:
        added = await (await client.post("/api/mcp/servers", json=body)).json()
        switched = await client.post("/api/mcp/servers/comfy/mode", json={"mode": "tools"})
        listed = await (await client.get("/api/mcp/servers")).json()

    assert added["server"]["mode"] == "cli"
    assert switched.status == 200
    assert {s["name"]: s.get("mode") for s in listed["servers"]}["comfy"] == "tools"
