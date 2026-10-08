"""ColonyRuntime._build_worker wiring for worker tool tiering.

Exercises the real spawn construction path (not just the ToolTierState
engine): keep-set on → tier + providers wired and split computed against the
colony's MCP name set; keep-set empty → dark (no tier, no providers);
preload_tools promoted at spawn; loaded set persisted and restored across a
rebuild of the same worker.
"""

from pathlib import Path

from framework.agent_loop.types import AgentSpec
from framework.host.colony_runtime import ColonyConfig, ColonyRuntime
from framework.host.event_bus import EventBus
from framework.llm.provider import Tool
from framework.schemas.goal import Goal


def _tool(name: str) -> Tool:
    return Tool(name=name, description=f"desc of {name}", parameters={"type": "object"})


_POOL = [
    _tool("browser_interact"),
    _tool("browser_upload"),
    _tool("send_email"),
    _tool("task_update"),
]
_MCP_NAMES = {"browser_interact", "browser_upload", "send_email"}


def _make_colony(tmp_path: Path) -> ColonyRuntime:
    colony = ColonyRuntime(
        agent_spec=AgentSpec(
            id="t",
            name="t",
            description="t",
            system_prompt="t",
            agent_type="event_loop",
            output_keys=[],
            tool_access_policy="all",
        ),
        goal=Goal(id="g", name="g", description="g"),
        storage_path=tmp_path / "colony",
        llm=None,
        tools=list(_POOL),
        tool_executor=lambda tu: None,
        event_bus=EventBus(),
        stream_id="tier_test",
        pipeline_stages=[],
        config=ColonyConfig(max_concurrent_workers=1),
    )
    colony.set_tool_allowlist(None, _MCP_NAMES)
    return colony


def _spawn(colony, tmp_path: Path, worker_id: str = "w1", **kw):
    return colony._build_worker(
        worker_id=worker_id,
        worker_storage=tmp_path / worker_id,
        task="do the thing",
        input_data=None,
        spawn_spec=colony._agent_spec,
        spawn_tools=list(_POOL),
        spawn_executor=colony._tool_executor,
        spawn_catalog="",
        spawn_skill_dirs=[],
        profile_name_resolved="default",
        profile_integrations={},
        profile_browser="default",
        explicit_stream_id=None,
        loop_config_overrides=None,
        **kw,
    )


def test_keep_set_wires_tier_and_providers(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "framework.agents.queen.queen_tools_defaults.worker_always_enabled_tool_names",
        lambda mcp_catalog=None: {"browser_interact"},
    )
    worker = _spawn(_make_colony(tmp_path), tmp_path)
    ctx = worker._context
    tier = ctx.tool_tier_state
    assert tier is not None
    assert ctx.dynamic_tools_provider.__self__ is tier
    assert ctx.searchable_tools_provider.__self__ is tier
    assert set(ctx.loaded_tool_names_provider()) == set()
    eager = {t.name for t in tier.get_current_tools()}
    searchable = {t.name for t in tier.get_searchable_tools()}
    # keep-set + non-MCP (task_update) eager; MCP tail searchable.
    assert eager == {"browser_interact", "task_update"}
    assert searchable == {"browser_upload", "send_email"}


def test_empty_keep_set_is_dark(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "framework.agents.queen.queen_tools_defaults.worker_always_enabled_tool_names",
        lambda mcp_catalog=None: set(),
    )
    worker = _spawn(_make_colony(tmp_path), tmp_path)
    ctx = worker._context
    assert ctx.tool_tier_state is None
    assert ctx.dynamic_tools_provider is None
    assert ctx.searchable_tools_provider is None
    assert {t.name for t in ctx.available_tools} == {t.name for t in _POOL}


def test_preload_tools_promoted_at_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "framework.agents.queen.queen_tools_defaults.worker_always_enabled_tool_names",
        lambda mcp_catalog=None: {"browser_interact"},
    )
    worker = _spawn(_make_colony(tmp_path), tmp_path, preload_tools=["send_email", "not_a_tool"])
    tier = worker._context.tool_tier_state
    assert "send_email" in {t.name for t in tier.get_current_tools()}
    assert tier.loaded_tool_names == ["send_email"]
    # Unknown names are dropped, not promoted.
    assert "not_a_tool" not in tier.loaded_tool_names


def test_loaded_tools_persist_across_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "framework.agents.queen.queen_tools_defaults.worker_always_enabled_tool_names",
        lambda mcp_catalog=None: {"browser_interact"},
    )
    colony = _make_colony(tmp_path)
    worker = _spawn(colony, tmp_path, worker_id="w2")
    worker._context.tool_tier_state.promote_searched_tools(["browser_upload"])
    # Same worker_storage → resume path reconstructs the worker; the loaded
    # set must be restored from the tool_tiers.json sidecar.
    rebuilt = _spawn(colony, tmp_path, worker_id="w2")
    tier = rebuilt._context.tool_tier_state
    assert "browser_upload" in {t.name for t in tier.get_current_tools()}
