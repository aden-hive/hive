"""Hive's bundled tools run in-process as harness groups, not MCP servers."""

from __future__ import annotations

import json
import os

import pytest

from framework.llm.provider import ToolUse
from framework.loader.tool_registry import ToolRegistry
from framework.tools.harness_tools import HARNESS_GROUP_NAMES, build_harness_group, build_harness_tool


@pytest.fixture
def registry(tmp_path):
    reg = ToolRegistry()
    reg.set_mcp_extra_env({"HIVE_QUEEN_ID": "queen_test"})
    reg.load_registry_servers([{"name": name, "transport": "harness"} for name in ("terminal-tools", "hive_tools", "memory-tools")])
    reg.set_session_context(session_cwd=str(tmp_path), principal="agent:test", profile="sess-1")
    return reg


def _call(reg: ToolRegistry, name: str, **inputs):
    return reg.get_executor()(ToolUse(id="t", name=name, input=inputs))


@pytest.mark.parametrize("group", sorted(HARNESS_GROUP_NAMES))
def test_every_group_builds(group):
    tools = build_harness_group(group)
    assert tools, f"{group} produced no tools"
    for t in tools:
        assert t.input_schema["type"] == "object"
        assert "title" not in t.input_schema


def test_bundled_server_config_never_spawns_a_subprocess(tmp_path):
    """An old-style stdio config for a bundled name still resolves in-process."""
    config = tmp_path / "mcp_servers.json"
    config.write_text(json.dumps({"terminal-tools": {"transport": "stdio", "command": "definitely-not-a-binary", "args": ["x"]}}))
    reg = ToolRegistry()
    reg.load_mcp_config(config)
    assert reg._mcp_clients == []
    assert "terminal_exec" in reg.get_tools()
    assert reg.get_server_tool_names("terminal-tools") >= {"terminal_exec", "terminal_rg"}


def test_context_params_hidden_from_schema_and_injected(registry, tmp_path):
    schema = registry.get_tools()["terminal_exec"].parameters
    assert "session_cwd" not in schema["properties"]

    out = json.loads(_call(registry, "terminal_exec", command="echo $HIVE_PRINCIPAL $HIVE_QUEEN_ID $HIVE_BROWSER_SESSION", shell=True).content)
    assert out["stdout"].split() == ["agent:test", "queen_test", "sess-1"]

    out = json.loads(_call(registry, "terminal_exec", command='python -c "import os; print(os.getcwd())"').content)
    assert os.path.samefile(out["stdout"].strip(), tmp_path)


def test_image_results_become_image_content(registry, tmp_path):
    jpg = tmp_path / "shot.jpg"
    jpg.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")

    attached = _call(registry, "attach_file", paths=str(jpg))
    assert attached.image_content and attached.image_content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    # A hive-browser screenshot printed through terminal_exec is re-inlined.
    (tmp_path / "out.json").write_text(json.dumps({"ok": True, "_image": {"path": str(jpg)}}))
    shot = _call(registry, "terminal_exec", command="cat out.json", shell=True)
    assert shot.image_content


def test_memory_search_is_scoped_to_the_owning_registry(registry):
    out = json.loads(_call(registry, "search_messages", pattern="x").content)
    # The queen dir doesn't exist in the test home — but the scope it looked
    # for is this registry's queen, not whatever os.environ happens to say.
    assert out["error"] == "scope_not_found"
    assert "queen_test" in out["message"]


def test_bad_arguments_return_an_error_result(registry):
    out = json.loads(_call(registry, "terminal_exec", timeout_sec="soon").content)
    assert "Invalid arguments for terminal_exec" in out["error"]


@pytest.mark.asyncio
async def test_async_tools_return_awaitables():
    async def fetch(url: str, retries: int = 1) -> dict:
        return {"url": url, "retries": retries}

    ht = build_harness_tool("fetch", "Fetch.", fetch)
    assert ht.input_schema["required"] == ["url"]
    assert json.loads(await ht.invoke({"url": "u", "retries": "3"})) == {"url": "u", "retries": 3}


def test_group_registration_is_idempotent_and_survives_resync(registry, monkeypatch):
    before = set(registry.get_tools())
    assert registry.register_mcp_server({"name": "terminal-tools", "transport": "stdio"}) == 0
    assert set(registry.get_tools()) == before

    # A credential resync wipes and rebuilds MCP bookkeeping. Harness groups
    # must keep theirs, or allowlists stop gating terminal_* tools.
    registry._mcp_clients = [object()]
    registry._mcp_config_path = registry._mcp_config_path or __file__
    monkeypatch.setattr(registry, "_cleanup_mcp_clients", lambda *_a, **_k: None)
    monkeypatch.setattr(registry, "load_mcp_config", lambda _p: None)
    try:
        assert registry.resync_mcp_servers_if_needed(force=True)
    finally:
        registry._mcp_clients = []
    assert "terminal_exec" in registry.get_server_tool_names("terminal-tools")
    assert "terminal-tools" in registry.get_full_mcp_catalog()


def test_memory_scope_follows_a_live_colony_binding(_isolate_hive_home_autouse, monkeypatch):
    """A DM that binds to a colony mid-session searches the colony's memory on
    its next call; its workers share the registry, so they do too."""
    home = _isolate_hive_home_autouse
    monkeypatch.setenv("HIVE_HOME", str(home))

    def write(session_dir, text):
        session_dir.mkdir(parents=True)
        event = {"type": "client_input_received", "data": {"content": text}}
        (session_dir / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")

    write(home / "queens" / "queen_ops" / "sessions" / "session_20260601_080000_aaaa", "DM_FACT")
    write(home / "colonies" / "acme" / "queens" / "queen_ops" / "sessions" / "session_20260601_090000_bbbb", "COLONY_FACT")

    session = {"colony_id": None}
    reg = ToolRegistry()
    reg.set_identity_env_provider(lambda: {"HIVE_COLONY_NAME": session["colony_id"]} if session["colony_id"] else {"HIVE_QUEEN_ID": "queen_ops"})
    reg.load_registry_servers([{"name": "memory-tools", "transport": "harness"}])

    def hits(pattern):
        return json.loads(_call(reg, "search_messages", pattern=pattern).content).get("total_matches")

    assert (hits("DM_FACT"), hits("COLONY_FACT")) == (1, 0)
    session["colony_id"] = "acme"
    assert (hits("DM_FACT"), hits("COLONY_FACT")) == (0, 1)


@pytest.mark.parametrize("openpyxl_installed", [True, False])
def test_excel_tools_only_appear_with_openpyxl(monkeypatch, openpyxl_installed):
    """Without the optional extra every excel_* call answered "pip install
    openpyxl", inviting the agent to modify the user's environment."""
    import importlib.util

    from framework.tools import harness_tools

    real_find_spec = importlib.util.find_spec

    def find_spec(name, *args, **kwargs):
        if name == "openpyxl":
            return object() if openpyxl_installed else None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(harness_tools.importlib.util, "find_spec", find_spec)
    names = {t.name for t in build_harness_group("hive_tools")}

    assert ("excel_read" in names) is openpyxl_installed
    assert "csv_sql" in names
